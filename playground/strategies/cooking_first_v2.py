"""
CookingFirstV2Strategy: 旧版 Cooking First v2 策略

这是旧版策略，已被 DefaultStrategy 取代。
接收 UnifiedState，返回 Action，不直接接触环境。

决策优先级：
1. 送餐（动画窗口期间跳过）
2. 清理过期食材
3. 移动完成食材到组装站
4. 开始烹饪（多订单并行）
5. 添加调料
6. 存入 stockpile
7. 从库存取用

输入: UnifiedState
输出: Action | None
"""

from __future__ import annotations

from loguru import logger

from hawarma.agent.agent import (
    Action,
    CookAction,
    MoveToAssemblyAction,
    MoveToStockpileAction,
    PullFromStockpileAction,
    AddCondimentAction,
    ServeOrderAction,
    ClearCookerAction,
    ClearAssemblyAction,
)
from playground.env.unified_state import UnifiedState
from playground.strategies.base import Strategy


class CookingFirstV2Strategy(Strategy):
    """
    默认多订单并行策略。

    从当前 CookingAgent 的决策逻辑提取，保持行为一致。
    """

    EXPIRED_THRESHOLD = 5.0
    WARN_THRESHOLD = 4.0

    def __init__(self):
        self._recipe_by_slug: dict[str, object] = {}
        self._recipe_condiments: dict[str, dict[str, int]] = {}
        self._ingredient_info: dict[str, tuple[str, float]] = {}

    def on_game_start(self, recipes: dict[str, object]) -> None:
        """初始化配方相关数据"""
        self._recipe_by_slug = recipes
        self._recipe_condiments = {}
        self._ingredient_info = {}

        for slug, recipe in recipes.items():
            # 调料
            condiments = self._get_recipe_attr(recipe, "condiments", [])
            if isinstance(condiments, list):
                self._recipe_condiments[slug] = {c: 1 for c in condiments}
            elif isinstance(condiments, dict):
                self._recipe_condiments[slug] = dict(condiments)
            else:
                self._recipe_condiments[slug] = {}

            # 食材信息
            raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
            cookers = self._get_recipe_attr(recipe, "cookers", [])
            durations = self._get_recipe_attr(recipe, "cook_durations", [])
            for i, ing in enumerate(raw):
                if ing not in self._ingredient_info:
                    cooker = cookers[i] if i < len(cookers) else None
                    duration = durations[i] if i < len(durations) else 3.0
                    if cooker:
                        self._ingredient_info[ing] = (cooker, duration)

    # ====================================================================
    # 决策入口
    # ====================================================================

    def decide(self, state: UnifiedState) -> Action | None:
        """单步决策：多订单并行策略"""
        assembly_ings = [
            ing[0] if isinstance(ing, tuple) else ing
            for ing in state.assembly.ingredients_cookers
        ]

        # 0. 检查组装站是否需要清理（超时订单/长时间停滞）
        if action := self._try_clear_assembly(state, assembly_ings):
            return action

        # 1. 送餐
        if action := self._try_serve(state, assembly_ings):
            return action

        # 2. 清理过期食材
        if action := self._try_clear_expired(state):
            return action

        # 3. 移动完成食材到组装站
        if action := self._try_move_to_assembly(state, assembly_ings):
            return action

        # 4. 开始烹饪
        if action := self._try_parallel_cooking(state, assembly_ings):
            return action

        # 5. 添加调料
        if action := self._try_add_condiment(state, assembly_ings):
            return action

        # 6. 存入 stockpile
        if action := self._try_store_to_stockpile(state):
            return action

        # 7. 从库存取用
        if action := self._try_pull_from_stockpile(state):
            return action

        return None

    # ====================================================================
    # 送餐
    # ====================================================================

    def _try_serve(self, state: UnifiedState, assembly_ings: list[str]) -> ServeOrderAction | None:
        if state.is_in_animation_window:
            return None

        assembly = state.assembly
        if not assembly.ingredients_cookers:
            return None

        target_slug = assembly.target_recipe_slug

        for slot_idx, order in self._prioritized_orders(state):
            if order is None or order.done:
                continue

            if target_slug and target_slug != order.recipe_slug:
                continue

            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe and self._ingredients_match(assembly.ingredients_cookers, recipe):
                condiments_needed = self._recipe_condiments.get(order.recipe_slug, {})
                if self._condiments_complete(assembly.condiments, condiments_needed):
                    return ServeOrderAction(slot_idx=slot_idx)

        return None

    # ====================================================================
    # 组装站清理
    # ====================================================================

    def _try_clear_assembly(self, state: UnifiedState, assembly_ings: list[str]) -> ClearAssemblyAction | None:
        """检查组装站食材是否属于已超时订单或长时间停滞"""
        assembly = state.assembly
        if not assembly.ingredients_cookers:
            return None

        # 检查 1：assembly 的 target_recipe 对应订单已不存在
        target_slug = assembly.target_recipe_slug
        if target_slug:
            has_active = any(
                o and not o.done and o.recipe_slug == target_slug
                for o in state.orders
            )
            if not has_active:
                return ClearAssemblyAction()

        # 检查 2：没有 target_recipe，但食材不匹配任何活跃订单
        if not target_slug:
            active_slugs = {o.recipe_slug for o in state.orders if o and not o.done}
            if not active_slugs:
                return ClearAssemblyAction()

            for order in state.orders:
                if order and not order.done:
                    recipe = self._recipe_by_slug.get(order.recipe_slug)
                    if recipe:
                        recipe_ings = set(self._get_recipe_attr(recipe, "raw_ingredients", []))
                        if all(ing in recipe_ings for ing in assembly_ings):
                            return None
            return ClearAssemblyAction()

        return None

    # ====================================================================
    # 添加调料
    # ====================================================================

    def _try_add_condiment(self, state: UnifiedState, assembly_ings: list[str]) -> AddCondimentAction | None:
        assembly = state.assembly
        target_slug = assembly.target_recipe_slug

        if not target_slug:
            target_slug = self._infer_recipe_from_assembly(state)
            if not target_slug:
                return None

        recipe = self._recipe_by_slug.get(target_slug)
        if not recipe:
            return None

        if not self._ingredients_match(assembly.ingredients_cookers, recipe):
            return None

        condiments_needed = self._recipe_condiments.get(target_slug, {})
        if not condiments_needed:
            return None

        for condiment, required in condiments_needed.items():
            current = assembly.condiments.get(condiment, 0)
            if current < required:
                return AddCondimentAction(condiment=condiment)

        return None

    # ====================================================================
    # 移动完成食材
    # ====================================================================

    def _try_move_to_assembly(self, state: UnifiedState, assembly_ings: list[str]) -> MoveToAssemblyAction | None:
        needed = self._get_needed_ingredients(state)

        all_needed_with_cooker: list[tuple[str, str]] = []
        for order in state.orders:
            if order and not order.done:
                recipe = self._recipe_by_slug.get(order.recipe_slug)
                if recipe:
                    raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
                    cookers = self._get_recipe_attr(recipe, "cookers", [])
                    for i, ing in enumerate(raw):
                        cooker = cookers[i] if i < len(cookers) else None
                        if cooker:
                            all_needed_with_cooker.append((ing, cooker))

        effective_needed: set[tuple[str, str]] = set(needed) | set(all_needed_with_cooker)

        if not effective_needed:
            return None

        for cooker_name, cooker in state.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            if state.time < cooker.done_at:
                continue
            if cooker.is_expired(state.time):
                continue
            ing_key = (cooker.ingredient_name, cooker.cooker_type)
            if ing_key not in effective_needed:
                continue
            if not self._can_add_to_assembly(state, cooker.ingredient_name, cooker.cooker_type):
                continue
            order_id = self._get_order_id_for_ingredient_with_cooker(state, cooker.ingredient_name, cooker.cooker_type)
            return MoveToAssemblyAction(cooker=cooker_name, order_id=order_id)

        return None

    # ====================================================================
    # 从库存取用
    # ====================================================================

    def _try_pull_from_stockpile(self, state: UnifiedState) -> PullFromStockpileAction | None:
        assembly = state.assembly

        if assembly.ingredients_cookers and not assembly.target_recipe_slug:
            return None

        if assembly.target_recipe_slug:
            has_active = any(
                o and not o.done and o.recipe_slug == assembly.target_recipe_slug
                for o in state.orders
            )
            if not has_active:
                return None

        needed_ings = self._get_needed_ingredient_names(state)
        if not needed_ings:
            return None

        for slot_name, slot in state.stockpile.items():
            if slot.ingredient_name in needed_ings and slot.count > 0:
                if self._can_add_to_assembly(state, slot.ingredient_name, slot.cooker_type):
                    return PullFromStockpileAction(slot=slot_name, ingredient=slot.ingredient_name)

        return None

    # ====================================================================
    # 开始烹饪
    # ====================================================================

    def _try_parallel_cooking(self, state: UnifiedState, assembly_ings: list[str]) -> CookAction | None:
        free_cookers = [name for name, c in state.cookers.items() if not c.busy]
        if not free_cookers:
            return None

        assembly = state.assembly

        # 组装站缺失的食材排最前
        assembly_missing = []
        if assembly.target_recipe_slug:
            recipe = self._recipe_by_slug.get(assembly.target_recipe_slug)
            if recipe:
                raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
                cookers = self._get_recipe_attr(recipe, "cookers", [])
                for i, ing_name in enumerate(raw):
                    cooker = cookers[i] if i < len(cookers) else None
                    if cooker and ing_name not in assembly_ings:
                        assembly_missing.append((ing_name, cooker))

        # 当前订单需要的食材
        needed_current = []
        for _, order in self._prioritized_orders(state):
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe:
                raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
                cookers = self._get_recipe_attr(recipe, "cookers", [])
                for i, ing_name in enumerate(raw):
                    cooker = cookers[i] if i < len(cookers) else None
                    if cooker and ing_name not in [n for n, _ in needed_current]:
                        needed_current.append((ing_name, cooker))
                break

        needed_current = assembly_missing + [item for item in needed_current if item not in assembly_missing]

        # 所有订单需要的食材
        needed_all = []
        seen = set()
        for order in state.orders:
            if order and not order.done:
                recipe = self._recipe_by_slug.get(order.recipe_slug)
                if recipe:
                    raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
                    cookers = self._get_recipe_attr(recipe, "cookers", [])
                    for i, ing_name in enumerate(raw):
                        cooker = cookers[i] if i < len(cookers) else None
                        if cooker and (ing_name, cooker) not in seen:
                            seen.add((ing_name, cooker))
                            needed_all.append((ing_name, cooker))

        # stockpile 计数
        stockpile_counts = {}
        for slot in state.stockpile.values():
            if slot.count > 0 and slot.ingredient_name:
                stockpile_counts[slot.ingredient_name] = stockpile_counts.get(slot.ingredient_name, 0) + slot.count

        # 优先烹饪当前订单需要的食材
        for ing_name, cooker_type in needed_current:
            if cooker_type not in free_cookers:
                continue
            if self._is_cooking(state, ing_name, cooker_type):
                continue
            if ing_name in assembly_ings:
                continue
            if self._has_in_stockpile(state, ing_name, cooker_type):
                continue

            _, duration = self._ingredient_info.get(ing_name, (None, 3.0))
            order_id = self._get_order_id_for_ingredient(state, ing_name)
            return CookAction(ingredient=ing_name, cooker=cooker_type, duration=duration, order_id=order_id)

        # 然后烹饪其他订单需要的食材
        for ing_name, cooker_type in needed_all:
            if cooker_type not in free_cookers:
                continue
            if self._is_cooking(state, ing_name, cooker_type):
                continue
            if ing_name in assembly_ings:
                continue
            if stockpile_counts.get(ing_name, 0) > 0:
                continue

            _, duration = self._ingredient_info.get(ing_name, (None, 3.0))
            order_id = self._get_order_id_for_ingredient(state, ing_name)
            return CookAction(ingredient=ing_name, cooker=cooker_type, duration=duration, order_id=order_id)

        return None

    # ====================================================================
    # 清理过期食材
    # ====================================================================

    def _try_clear_expired(self, state: UnifiedState) -> ClearCookerAction | None:
        for cooker_name, cooker in state.cookers.items():
            if cooker.busy and cooker.is_expired(state.time):
                return ClearCookerAction(cooker=cooker_name)
        return None

    # ====================================================================
    # 存入库存
    # ====================================================================

    def _try_store_to_stockpile(self, state: UnifiedState) -> MoveToStockpileAction | None:
        assembly = state.assembly
        needed = self._get_needed_ingredient_names(state)

        for cooker_name, cooker in state.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            if state.time < cooker.done_at:
                continue

            ing_name = cooker.ingredient_name
            cooker_type = cooker.cooker_type
            time_since_done = state.time - cooker.done_at

            if ing_name in needed:
                continue

            if time_since_done > self.WARN_THRESHOLD:
                slot = self._try_increment_stockpile(state, ing_name, cooker_type)
                if slot is None:
                    slot = self._find_available_slot(state, ing_name, cooker_type)
                if slot:
                    return MoveToStockpileAction(cooker=cooker_name, slot=slot)

            if time_since_done > self.EXPIRED_THRESHOLD:
                slot = self._try_increment_stockpile(state, ing_name, cooker_type)
                if slot is None:
                    slot = self._find_available_slot(state, ing_name, cooker_type)
                if slot:
                    return MoveToStockpileAction(cooker=cooker_name, slot=slot)

        if assembly.is_free:
            for cooker_name, cooker in state.cookers.items():
                if not cooker.busy or cooker.done_at is None:
                    continue
                if state.time < cooker.done_at:
                    continue
                if cooker.ingredient_name not in needed:
                    slot = self._try_increment_stockpile(state, cooker.ingredient_name, cooker.cooker_type)
                    if slot is None:
                        slot = self._find_available_slot(state, cooker.ingredient_name, cooker.cooker_type)
                    if slot:
                        return MoveToStockpileAction(cooker=cooker_name, slot=slot)
            return None

        for cooker_name, cooker in state.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            if state.time < cooker.done_at:
                continue
            if cooker.ingredient_name in needed:
                continue
            slot = self._try_increment_stockpile(state, cooker.ingredient_name, cooker.cooker_type)
            if slot is None:
                slot = self._find_available_slot(state, cooker.ingredient_name, cooker.cooker_type)
            if slot:
                return MoveToStockpileAction(cooker=cooker_name, slot=slot)

        return None

    # ====================================================================
    # 订单优先级
    # ====================================================================

    def _prioritized_orders(self, state: UnifiedState) -> list[tuple[int, object]]:
        orders_with_idx = []
        for i, order in enumerate(state.orders):
            if order is not None and not order.done:
                orders_with_idx.append((i, order))

        def sort_key(item):
            _, order = item
            rush_priority = 0 if order.is_rush else 1
            timeout_remaining = order.timeout_at - state.time
            created_at = order.created_at
            return (rush_priority, timeout_remaining, created_at)

        orders_with_idx.sort(key=sort_key)
        return orders_with_idx

    # ====================================================================
    # 辅助方法
    # ====================================================================

    def _get_needed_ingredients(self, state: UnifiedState) -> list[tuple[str, str]]:
        assembly = state.assembly
        target_slug = assembly.target_recipe_slug
        present = set(assembly.ingredients_cookers)

        if target_slug:
            recipe = self._recipe_by_slug.get(target_slug)
            if recipe:
                raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
                cookers = self._get_recipe_attr(recipe, "cookers", [])
                result = []
                for i, ing in enumerate(raw):
                    if (ing, cookers[i]) not in present and (ing,) not in present:
                        cooker = cookers[i] if i < len(cookers) else None
                        if cooker:
                            result.append((ing, cooker))
                return result

        for _, order in self._prioritized_orders(state):
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe:
                raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
                cookers = self._get_recipe_attr(recipe, "cookers", [])
                result = []
                for i, ing in enumerate(raw):
                    cooker = cookers[i] if i < len(cookers) else None
                    if cooker:
                        result.append((ing, cooker))
                return result

        return []

    def _get_needed_ingredient_names(self, state: UnifiedState) -> set[str]:
        return {ing for ing, _ in self._get_needed_ingredients(state)}

    def _can_add_to_assembly(self, state: UnifiedState, ingredient: str, cooker_type: str | None = None) -> bool:
        assembly = state.assembly
        present_with_cooker = assembly.ingredients_cookers
        target_slug = assembly.target_recipe_slug

        if not present_with_cooker and not target_slug:
            return True

        if not target_slug:
            present_ing_combos = {(t[0], t[1]) if isinstance(t, tuple) else (t, None) for t in present_with_cooker}

            compatible_slugs = []
            for order in state.orders:
                if not order or order.done:
                    continue
                recipe = self._recipe_by_slug.get(order.recipe_slug)
                if not recipe:
                    continue
                raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
                cookers = self._get_recipe_attr(recipe, "cookers", [])
                all_match = True
                for ing_name, ck_type in present_ing_combos:
                    ing_matched = False
                    for i, r_ing in enumerate(raw):
                        r_ck = cookers[i] if i < len(cookers) else None
                        if r_ing == ing_name and r_ck == ck_type:
                            ing_matched = True
                            break
                    if not ing_matched:
                        all_match = False
                        break
                if all_match:
                    compatible_slugs.append(order.recipe_slug)

            if not compatible_slugs:
                return False

            new_key = (ingredient, cooker_type)
            if new_key in present_ing_combos:
                return False

            for slug in compatible_slugs:
                recipe = self._recipe_by_slug.get(slug)
                if recipe:
                    raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
                    cookers = self._get_recipe_attr(recipe, "cookers", [])
                    for i, r_ing in enumerate(raw):
                        r_ck = cookers[i] if i < len(cookers) else None
                        if r_ing == ingredient and r_ck == cooker_type:
                            return True
            return False

        recipe = self._recipe_by_slug.get(target_slug)
        if not recipe:
            return False

        raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
        cookers = self._get_recipe_attr(recipe, "cookers", [])
        found = False
        for i, ing in enumerate(raw):
            if ing == ingredient:
                cooker_needed = cookers[i] if i < len(cookers) else None
                if cooker_needed != cooker_type:
                    return False
                found = True
        if not found:
            return False

        present_combinations = {
            (ing[0], ing[1]) if isinstance(ing, tuple) else (ing, None)
            for ing in present_with_cooker
        }
        return (ingredient, cooker_type) not in present_combinations

    def _is_cooking(self, state: UnifiedState, ingredient: str, cooker_type: str | None = None) -> bool:
        for cooker in state.cookers.values():
            if cooker.busy and cooker.ingredient_name == ingredient:
                if cooker_type is None or cooker.cooker_type == cooker_type:
                    return True
        return False

    def _has_in_stockpile(self, state: UnifiedState, ingredient: str, cooker_type: str | None = None) -> bool:
        for slot in state.stockpile.values():
            if slot.ingredient_name == ingredient and slot.count > 0:
                if cooker_type is None or slot.cooker_type == cooker_type:
                    return True
        return False

    def _find_available_slot(self, state: UnifiedState, ingredient: str, cooker_type: str) -> str | None:
        for slot_name, slot in state.stockpile.items():
            if slot.ingredient_name is None or (slot.ingredient_name == ingredient and slot.cooker_type == cooker_type):
                if slot.count < 5:
                    return slot_name
        return None

    def _try_increment_stockpile(self, state: UnifiedState, ingredient: str, cooker_type: str) -> str | None:
        for slot_name, slot in state.stockpile.items():
            if slot.ingredient_name == ingredient and slot.cooker_type == cooker_type:
                if slot.count < 5:
                    return slot_name
        return None

    def _get_order_id_for_ingredient(self, state: UnifiedState, ingredient: str) -> int | None:
        for _, order in self._prioritized_orders(state):
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe:
                raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
                if ingredient in raw:
                    return order.order_id
        return None

    def _get_order_id_for_ingredient_with_cooker(self, state: UnifiedState, ingredient: str, cooker_type: str) -> int | None:
        for _, order in self._prioritized_orders(state):
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe:
                raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
                cookers = self._get_recipe_attr(recipe, "cookers", [])
                for i, ing in enumerate(raw):
                    if ing == ingredient:
                        cooker_needed = cookers[i] if i < len(cookers) else None
                        if cooker_needed == cooker_type:
                            return order.order_id
        return None

    def _infer_recipe_from_assembly(self, state: UnifiedState) -> str | None:
        assembly = state.assembly
        if not assembly.ingredients_cookers:
            return None

        assembly_pairs = set()
        for ing in assembly.ingredients_cookers:
            if isinstance(ing, tuple):
                assembly_pairs.add((ing[0], ing[1] if len(ing) > 1 else None))
            else:
                assembly_pairs.add((ing, None))

        for _, order in self._prioritized_orders(state):
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe:
                raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
                cookers = self._get_recipe_attr(recipe, "cookers", [])
                recipe_pairs = set()
                for i, ing in enumerate(raw):
                    cooker = cookers[i] if i < len(cookers) else None
                    recipe_pairs.add((ing, cooker))
                if assembly_pairs == recipe_pairs:
                    return order.recipe_slug
        return None

    def _ingredients_match(self, actual: list, recipe) -> bool:
        expected_raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
        expected_cookers = self._get_recipe_attr(recipe, "cookers", [])

        if len(actual) != len(expected_raw):
            return False

        expected_pairs = set()
        for i, ing in enumerate(expected_raw):
            cooker = expected_cookers[i] if i < len(expected_cookers) else None
            expected_pairs.add((ing, cooker))

        actual_pairs = set()
        for ing in actual:
            if isinstance(ing, tuple):
                actual_pairs.add((ing[0], ing[1] if len(ing) > 1 else None))
            else:
                actual_pairs.add((ing, None))

        return actual_pairs == expected_pairs

    def _condiments_complete(self, applied: dict[str, int], needed: dict[str, int]) -> bool:
        for condiment, count in needed.items():
            if applied.get(condiment, 0) < count:
                return False
        return True

    def _get_recipe_attr(self, recipe, attr_name, default=None):
        if hasattr(recipe, "ingredients") and attr_name == "raw_ingredients":
            return [ing.name for ing in recipe.ingredients]
        if hasattr(recipe, "ingredients") and attr_name == "cookers":
            return [ing.cooker_type for ing in recipe.ingredients]
        if hasattr(recipe, "ingredients") and attr_name == "cook_durations":
            return [ing.duration for ing in recipe.ingredients]
        if hasattr(recipe, attr_name):
            return getattr(recipe, attr_name)
        if isinstance(recipe, dict):
            return recipe.get(attr_name, default)
        return default
