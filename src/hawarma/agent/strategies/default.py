"""
DefaultStrategy: 默认策略（主动预烹饪 + 决策优先级优化）

核心优化（基于CookingFirstV2Strategy）：
1. 调料优先：组装站食材齐全时立即添加（更快释放组装站）
2. 最长烹饪优先：按时长降序排列（最大化并行重叠）
3. 主动预烹饪：灶台空闲时预烹饪活跃订单的未来食材
4. 快速存储：非必要食材2秒后存储（更快释放灶台）
5. 过期优先移动：优先移动接近过期的食材到组装站
6. 库存优先取用：为组装站目标优先拉取库存

决策优先级：
1. 清理组装站（超时订单）
2. 送餐
3. 清理过期食材
4. 添加调料（食材齐全时优先）
5. 移动完成食材到组装站（过期优先）
6. 从库存取用（为组装站目标）
7. 开始烹饪（最长优先）
8. 添加调料（回退）
9. 主动预烹饪
10. 存入库存（2秒快速存储）
11. 从库存取用

输入: UnifiedState
输出: Action | None
"""

from __future__ import annotations

from loguru import logger

from hawarma.core.actions import (
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
from hawarma.core.state import UnifiedState
from hawarma.agent.strategy import Strategy


class DefaultStrategy(Strategy):
    """默认策略：主动预烹饪 + 决策优先级优化"""

    EXPIRED_THRESHOLD = 5.0
    WARN_THRESHOLD = 4.0
    PRECOOK_STORE_THRESHOLD = 2.0
    MAX_PRECOOK_STOCKPILE = 3

    def __init__(self):
        self._recipe_by_slug: dict[str, object] = {}
        self._recipe_condiments: dict[str, dict[str, int]] = {}
        self._ingredient_info: dict[str, tuple[str, float]] = {}
        self._recipe_ingredient_cooker: dict[str, list[tuple[str, str, float]]] = {}

    def on_game_start(self, recipes: dict[str, object]) -> None:
        self._recipe_by_slug = recipes
        self._recipe_condiments = {}
        self._ingredient_info = {}
        self._recipe_ingredient_cooker = {}

        for slug, recipe in recipes.items():
            condiments = self._get_recipe_attr(recipe, "condiments", [])
            if isinstance(condiments, list):
                self._recipe_condiments[slug] = {c: 1 for c in condiments}
            elif isinstance(condiments, dict):
                self._recipe_condiments[slug] = dict(condiments)
            else:
                self._recipe_condiments[slug] = {}

            raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
            cookers = self._get_recipe_attr(recipe, "cookers", [])
            durations = self._get_recipe_attr(recipe, "cook_durations", [])

            ics = []
            for i, ing in enumerate(raw):
                cooker = cookers[i] if i < len(cookers) else None
                duration = durations[i] if i < len(durations) else 3.0
                if cooker:
                    self._ingredient_info[ing] = (cooker, duration)
                    ics.append((ing, cooker, duration))
            self._recipe_ingredient_cooker[slug] = ics

    def decide(self, state: UnifiedState) -> Action | None:
        assembly_ings = [
            ing[0] if isinstance(ing, tuple) else ing
            for ing in state.assembly.ingredients_cookers
        ]

        if action := self._try_clear_assembly(state, assembly_ings):
            return action
        if action := self._try_serve(state, assembly_ings):
            return action
        if action := self._try_clear_expired(state):
            return action
        # 优先移动已完成食材（防止过期），然后立即启动烹饪
        # cooking 排在 add_cond 之前，让灶台在 add_cond/serve 期间也能工作
        if action := self._try_move_to_assembly(state, assembly_ings):
            return action
        if action := self._try_parallel_cooking(state, assembly_ings):
            return action
        if action := self._try_add_condiment_urgent(state, assembly_ings):
            return action
        if action := self._try_pull_from_stockpile_urgent(state):
            return action
        if action := self._try_add_condiment(state, assembly_ings):
            return action
        if action := self._try_precook(state, assembly_ings):
            return action
        if action := self._try_store_to_stockpile(state):
            return action
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
        assembly = state.assembly
        if not assembly.ingredients_cookers:
            return None
        target_slug = assembly.target_recipe_slug
        if target_slug:
            has_active = any(
                o and not o.done and o.recipe_slug == target_slug
                for o in state.orders
            )
            if not has_active:
                return ClearAssemblyAction()
            # target_slug 匹配活跃订单，但还要验证 assembly 中的食材真的属于该配方
            ics = self._recipe_ingredient_cooker.get(target_slug, [])
            recipe_pairs = {(n, c) for n, c, _ in ics}
            assembly_pairs = set()
            for ing in assembly.ingredients_cookers:
                if isinstance(ing, tuple):
                    assembly_pairs.add((ing[0], ing[1] if len(ing) > 1 else None))
                else:
                    assembly_pairs.add((ing, None))
            if not assembly_pairs.issubset(recipe_pairs):
                # assembly 里有不属于 target recipe 的食材 → 死锁，清理
                return ClearAssemblyAction()
            return None

        # target_slug 为 None：严格检查 assembly 是否可能匹配任何活跃订单
        # 1) 先尝试完整匹配（食材 + cooker 完全一致）
        inferred = self._infer_recipe_from_assembly(state)
        if inferred and any(
            o and not o.done and o.recipe_slug == inferred for o in state.orders
        ):
            return None

        # 2) 再检查是否是某个活跃订单的部分组装（真子集）
        assembly_pairs = set()
        for ing in assembly.ingredients_cookers:
            if isinstance(ing, tuple):
                assembly_pairs.add((ing[0], ing[1] if len(ing) > 1 else None))
            else:
                assembly_pairs.add((ing, None))

        for order in state.orders:
            if not order or order.done:
                continue
            ics = self._recipe_ingredient_cooker.get(order.recipe_slug, [])
            recipe_pairs = {(n, c) for n, c, _ in ics}
            if assembly_pairs.issubset(recipe_pairs):
                return None  # 部分组装中，保留等待后续食材

        # 既不完全匹配，也不是任何活跃订单的部分组装 → 死锁，清理
        return ClearAssemblyAction()

    # ====================================================================
    # 调料优先
    # ====================================================================

    def _try_add_condiment_urgent(self, state: UnifiedState, assembly_ings: list[str]) -> AddCondimentAction | None:
        assembly = state.assembly
        if not assembly.ingredients_cookers:
            return None
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

    def _try_add_condiment(self, state: UnifiedState, assembly_ings: list[str]) -> AddCondimentAction | None:
        return self._try_add_condiment_urgent(state, assembly_ings)

    # ====================================================================
    # 移动完成食材（过期优先）
    # ====================================================================

    def _try_move_to_assembly(self, state: UnifiedState, assembly_ings: list[str]) -> MoveToAssemblyAction | None:
        needed = self._get_needed_ingredients(state)
        all_needed_with_cooker: list[tuple[str, str]] = []
        for order in state.orders:
            if order and not order.done:
                ics = self._recipe_ingredient_cooker.get(order.recipe_slug, [])
                for ing_name, cooker, _ in ics:
                    all_needed_with_cooker.append((ing_name, cooker))
        effective_needed: set[tuple[str, str]] = set(needed) | set(all_needed_with_cooker)
        if not effective_needed:
            return None

        done_items = []
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
            time_since_done = state.time - cooker.done_at
            done_items.append((-time_since_done, cooker_name, cooker))

        if done_items:
            done_items.sort()
            _, best_cooker_name, best_cooker = done_items[0]
            order_id = self._get_order_id_for_ingredient_with_cooker(
                state, best_cooker.ingredient_name, best_cooker.cooker_type)
            return MoveToAssemblyAction(cooker=best_cooker_name, order_id=order_id)

        return None

    # ====================================================================
    # 库存取用：紧急
    # ====================================================================

    def _try_pull_from_stockpile_urgent(self, state: UnifiedState) -> PullFromStockpileAction | None:
        assembly = state.assembly
        if not assembly.target_recipe_slug:
            if assembly.ingredients_cookers:
                return None
            return self._try_pull_from_stockpile(state)
        has_active = any(
            o and not o.done and o.recipe_slug == assembly.target_recipe_slug
            for o in state.orders
        )
        if not has_active:
            return None
        needed = self._get_needed_ingredient_names(state)
        if not needed:
            return None
        for slot_name, slot in state.stockpile.items():
            if slot.ingredient_name in needed and slot.count > 0:
                if self._can_add_to_assembly(state, slot.ingredient_name, slot.cooker_type):
                    return PullFromStockpileAction(slot=slot_name, ingredient=slot.ingredient_name)
        return None

    def _try_pull_from_stockpile(self, state: UnifiedState) -> PullFromStockpileAction | None:
        assembly = state.assembly
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
    # 烹饪：最长优先
    # ====================================================================

    def _try_parallel_cooking(self, state: UnifiedState, assembly_ings: list[str]) -> CookAction | None:
        free_cookers = [name for name, c in state.cookers.items() if not c.busy]
        if not free_cookers:
            return None
        assembly = state.assembly

        # 如果 assembly 已被某个活跃订单占用，只烹饪该订单需要的食材
        # 避免为其他订单烹饪的食材完成后无法进入 assembly 而浪费
        if assembly.target_recipe_slug:
            has_active = any(
                o and not o.done and o.recipe_slug == assembly.target_recipe_slug
                for o in state.orders
            )
            if has_active:
                ics = self._recipe_ingredient_cooker.get(assembly.target_recipe_slug, [])
                for ing_name, cooker, duration in ics:
                    if ing_name in assembly_ings:
                        continue
                    if cooker not in free_cookers:
                        continue
                    if self._is_cooking(state, ing_name, cooker):
                        continue
                    if self._has_in_stockpile(state, ing_name, cooker):
                        continue
                    order_id = self._get_order_id_for_ingredient(state, ing_name)
                    return CookAction(ingredient=ing_name, cooker=cooker, duration=duration, order_id=order_id)
                return None

        # assembly 为空：只烹饪最高优先级订单的食材
        # 避免同时烹饪多个不兼容订单的食材，导致后续 assembly 被占用时
        # 其他食材无处存放而浪费
        needed_current: list[tuple[str, str, float]] = []
        for _, order in self._prioritized_orders(state):
            ics = self._recipe_ingredient_cooker.get(order.recipe_slug, [])
            for ing_name, cooker, duration in ics:
                if (ing_name, cooker) not in [(n, c) for n, c, _ in needed_current]:
                    needed_current.append((ing_name, cooker, duration))
            break

        needed_current.sort(key=lambda x: x[2], reverse=True)

        for ing_name, cooker_type, duration in needed_current:
            if cooker_type not in free_cookers:
                continue
            if self._is_cooking(state, ing_name, cooker_type):
                continue
            if ing_name in assembly_ings:
                continue
            if self._has_in_stockpile(state, ing_name, cooker_type):
                continue
            order_id = self._get_order_id_for_ingredient(state, ing_name)
            return CookAction(ingredient=ing_name, cooker=cooker_type, duration=duration, order_id=order_id)

        return None

    # ====================================================================
    # 主动预烹饪
    # ====================================================================

    def _try_precook(self, state: UnifiedState, assembly_ings: list[str]) -> CookAction | None:
        free_cookers = [name for name, c in state.cookers.items() if not c.busy]
        if not free_cookers:
            return None

        total_in_stockpile = sum(slot.count for slot in state.stockpile.values())
        if total_in_stockpile >= self.MAX_PRECOOK_STOCKPILE:
            return None

        remaining_time = state.game_duration - state.time
        if remaining_time < 20:
            return None

        cooking_combos: set[tuple[str, str]] = set()
        for cooker in state.cookers.values():
            if cooker.busy:
                cooking_combos.add((cooker.ingredient_name, cooker.cooker_type))

        assembly = state.assembly
        # 如果 assembly 已被某个活跃订单占用，只预烹饪该订单的食材
        if assembly.target_recipe_slug:
            has_active = any(
                o and not o.done and o.recipe_slug == assembly.target_recipe_slug
                for o in state.orders
            )
            if has_active:
                active_order_slugs = {assembly.target_recipe_slug}
            else:
                active_order_slugs = {o.recipe_slug for o in state.orders if o and not o.done}
        else:
            active_order_slugs = {o.recipe_slug for o in state.orders if o and not o.done}

        candidates: list[tuple[str, str, float, float]] = []
        for slug in active_order_slugs:
            ics = self._recipe_ingredient_cooker.get(slug, [])
            for ing_name, cooker, duration in ics:
                combo = (ing_name, cooker)
                if combo in cooking_combos:
                    continue
                if ing_name in assembly_ings:
                    continue
                if self._has_in_stockpile(state, ing_name, cooker):
                    continue
                if cooker not in free_cookers:
                    continue
                score = 10.0 - duration
                candidates.append((ing_name, cooker, duration, score))

        # 当 assembly 被活跃订单占用时，不允许 fallback 到其他订单
        # 防止为不兼容订单烹饪的食材完成后无法进入 assembly
        assembly_locked = (
            assembly.target_recipe_slug
            and any(
                o and not o.done and o.recipe_slug == assembly.target_recipe_slug
                for o in state.orders
            )
        )

        if not candidates and not assembly_locked:
            for slug, ics in self._recipe_ingredient_cooker.items():
                for ing_name, cooker, duration in ics:
                    combo = (ing_name, cooker)
                    if combo in cooking_combos:
                        continue
                    if ing_name in assembly_ings:
                        continue
                    if self._has_in_stockpile(state, ing_name, cooker):
                        continue
                    if cooker not in free_cookers:
                        continue
                    score = 1.0 - duration
                    candidates.append((ing_name, cooker, duration, score))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[3], reverse=True)
        ing_name, cooker, duration, _ = candidates[0]
        actual_duration = self._ingredient_info.get(ing_name, (None, 3.0))[1]
        order_id = self._get_order_id_for_ingredient(state, ing_name)
        return CookAction(ingredient=ing_name, cooker=cooker, duration=actual_duration, order_id=order_id)

    # ====================================================================
    # 清理过期食材
    # ====================================================================

    def _try_clear_expired(self, state: UnifiedState) -> ClearCookerAction | None:
        for cooker_name, cooker in state.cookers.items():
            if cooker.busy and cooker.is_expired(state.time):
                return ClearCookerAction(cooker=cooker_name)
        return None

    # ====================================================================
    # 存入库存（快速存储）
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
                if time_since_done > self.WARN_THRESHOLD:
                    slot = self._try_increment_stockpile(state, ing_name, cooker_type)
                    if slot is None:
                        slot = self._find_available_slot(state, ing_name, cooker_type)
                    if slot:
                        return MoveToStockpileAction(cooker=cooker_name, slot=slot)
            else:
                if time_since_done > self.PRECOOK_STORE_THRESHOLD:
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
                    time_since_done = state.time - cooker.done_at
                    if time_since_done > self.PRECOOK_STORE_THRESHOLD:
                        slot = self._try_increment_stockpile(state, cooker.ingredient_name, cooker.cooker_type)
                        if slot is None:
                            slot = self._find_available_slot(state, cooker.ingredient_name, cooker.cooker_type)
                        if slot:
                            return MoveToStockpileAction(cooker=cooker_name, slot=slot)

        for cooker_name, cooker in state.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            if state.time < cooker.done_at:
                continue
            if cooker.ingredient_name in needed:
                continue
            time_since_done = state.time - cooker.done_at
            if time_since_done > self.PRECOOK_STORE_THRESHOLD:
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
            ics = self._recipe_ingredient_cooker.get(target_slug, [])
            present_pairs = set()
            for ing in present:
                if isinstance(ing, tuple):
                    present_pairs.add((ing[0], ing[1] if len(ing) > 1 else None))
                else:
                    present_pairs.add((ing, None))
            result = []
            for ing_name, cooker, _ in ics:
                if (ing_name, cooker) not in present_pairs:
                    result.append((ing_name, cooker))
            return result

        present_ing_names = set()
        for ing in present:
            name = ing[0] if isinstance(ing, tuple) else ing
            present_ing_names.add(name)

        if not present_ing_names:
            for _, order in self._prioritized_orders(state):
                ics = self._recipe_ingredient_cooker.get(order.recipe_slug, [])
                return [(n, c) for n, c, _ in ics]
            return []

        for _, order in self._prioritized_orders(state):
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if not recipe:
                continue
            raw_ings = set(self._get_recipe_attr(recipe, "raw_ingredients", []))
            if present_ing_names.issubset(raw_ings):
                ics = self._recipe_ingredient_cooker.get(order.recipe_slug, [])
                return [(n, c) for n, c, _ in ics if n not in present_ing_names]

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
                ics = self._recipe_ingredient_cooker.get(slug, [])
                for ing_name, ck, _ in ics:
                    if ing_name == ingredient and ck == cooker_type:
                        return True
            return False

        ics = self._recipe_ingredient_cooker.get(target_slug, [])
        found = False
        for ing_name, ck, _ in ics:
            if ing_name == ingredient:
                if ck != cooker_type:
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
            ics = self._recipe_ingredient_cooker.get(order.recipe_slug, [])
            for ing_name, ck, _ in ics:
                if ing_name == ingredient and ck == cooker_type:
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
            ics = self._recipe_ingredient_cooker.get(order.recipe_slug, [])
            recipe_pairs = {(n, c) for n, c, _ in ics}
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
