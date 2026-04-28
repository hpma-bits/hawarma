"""
BaselineWithStockpileStrategy: 带库存的 baseline

从 baseline 扩展，添加 stockpile 作为"时空缓冲"：
  1. 保留锁定当前订单逻辑（完成前不切换）
  2. cooking 完成后 → 优先移到 assembly → 其次存入 stockpile
  3. assembly 空闲需要食材时 → 优先从 stockpile pull（跳过烹饪等待）
  4. 预测下一订单的食材并预烹饪，缓存在 stockpile 中

核心改进：stockpile 消除了"assembly 忙 → cooker 闲置 → 食材过期"的链条。
"""

from __future__ import annotations

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
from hawarma.agent.unified_state import UnifiedState
from hawarma.agent.strategies.default import DefaultStrategy


class BaselineWithStockpileStrategy(DefaultStrategy):
    """带 stockpile 的阶段式 baseline"""

    def __init__(self):
        super().__init__()
        self._current_target_slug: str | None = None

    def reset(self) -> None:
        super().reset()
        self._current_target_slug = None

    def decide(self, state: UnifiedState) -> Action | None:
        target = self._get_or_lock_target(state)
        if target is None:
            return None

        target_slug = target.recipe_slug
        asm_slug = state.assembly.target_recipe_slug
        assembly_ing_names = [ing[0] if isinstance(ing, tuple) else ing for ing in state.assembly.ingredients_cookers]

        # 清理属于其他订单的 assembly
        if asm_slug and asm_slug != target_slug:
            return ClearAssemblyAction()

        # 目标超时且 assembly 有食材 → 放弃
        if state.time >= target.timeout_at and state.assembly.ingredients_cookers:
            self._current_target_slug = None
            return ClearAssemblyAction()

        # 清理过期 cooker
        if action := self._try_clear_expired(state):
            return action

        # ── Assembly 完整 → serve ──
        recipe = self._recipe_by_slug.get(target_slug)
        if recipe and self._ingredients_match(state.assembly.ingredients_cookers, recipe):
            return self._handle_assembly_complete(state, target)

        # ── Assembly 不完整需要食材 → 优先从 stockpile pull ──
        needed_ings = self._get_missing_ingredients(state, target, assembly_ing_names)

        # 1) 尝试从 stockpile pull
        if action := self._try_pull_needed_from_stockpile(state, needed_ings):
            return action

        # 2) 尝试移动完成的食材到 assembly
        if action := self._try_move_done_to_assembly(state, target_slug, assembly_ing_names):
            return action

        # 3) 如果没有完成的食材 but stockpile 中有 → pull
        # (重复检查，因为 move 优先于 pull，但有时 move 不可行)

        # 4) 烹饪缺失的食材（为本订单，或为下一订单预烹饪）
        if action := self._try_cook_needed(state, target, needed_ings):
            return action

        # 5) 如果 cooker 上有不属于当前订单的完成食材 → 存 stockpile
        if action := self._try_store_done_to_stockpile(state, target_slug):
            return action

        # 6) 预烹饪：为下一订单准备食材
        if action := self._try_precook_next(state, target):
            return action

        return None

    # ================================================================
    # 订单锁定
    # ================================================================

    def _get_or_lock_target(self, state: UnifiedState):
        if self._current_target_slug:
            for o in state.orders:
                if o and not o.done and o.recipe_slug == self._current_target_slug:
                    return o
            self._current_target_slug = None
        target = self._get_earliest_timeout_order(state)
        if target:
            self._current_target_slug = target.recipe_slug
        return target

    def _get_earliest_timeout_order(self, state: UnifiedState):
        active = [o for o in state.orders if o and not o.done]
        if not active:
            return None
        active.sort(key=lambda o: (0 if o.is_rush else 1, o.timeout_at))
        return active[0]

    def _get_next_target(self, state: UnifiedState, current_target):
        active = [o for o in state.orders if o and not o.done and o is not current_target]
        if not active:
            return None
        active.sort(key=lambda o: (0 if o.is_rush else 1, o.timeout_at))
        return active[0]

    # ================================================================
    # Assembly 完整处理：先 cook 下一个订单，再调味 serve
    # ================================================================

    def _handle_assembly_complete(self, state: UnifiedState, target):
        target_slug = target.recipe_slug
        # 优先 cooking 下一个订单
        next_target = self._get_next_target(state, target)
        if next_target:
            needed = self._get_missing_ingredients(state, next_target, [])
            if action := self._try_cook_needed(state, next_target, needed):
                return action

        # 调味
        condiments_needed = self._recipe_condiments.get(target_slug, {})
        if not self._condiments_complete(state.assembly.condiments, condiments_needed):
            for condiment, required in condiments_needed.items():
                current = state.assembly.condiments.get(condiment, 0)
                if current < required:
                    return AddCondimentAction(condiment=condiment)

        # serve
        if not state.is_in_animation_window:
            for slot_idx, order in enumerate(state.orders):
                if order is target:
                    self._current_target_slug = None
                    return ServeOrderAction(slot_idx=slot_idx)
        return None

    # ================================================================
    # 缺失食材检测
    # ================================================================

    def _get_missing_ingredients(self, state: UnifiedState, target, assembly_ing_names: list[str]) -> list[tuple[str, str, float]]:
        """返回目标订单中尚未在 assembly 中的食材列表（检查 name+cooker 组合）"""
        ics = self._recipe_ingredient_cooker.get(target.recipe_slug, [])
        missing = []
        for ing_name, cooker_type, duration in ics:
            if self._assembly_has_ingredient(state, ing_name, cooker_type):
                continue
            missing.append((ing_name, cooker_type, duration))
        return missing

    # ================================================================
    # Stockpile: pull
    # ================================================================

    def _try_pull_needed_from_stockpile(self, state: UnifiedState, needed: list[tuple[str, str, float]]) -> PullFromStockpileAction | None:
        """如果 stockpile 中有需要的食材，pull 到 assembly"""
        for ing_name, cooker_type, duration in needed:
            for slot_name, slot in state.stockpile.items():
                if slot.count > 0 and slot.ingredient_name == ing_name and slot.cooker_type == cooker_type:
                    return PullFromStockpileAction(slot=slot_name)
        return None

    # ================================================================
    # Cooking
    # ================================================================

    def _try_cook_needed(self, state: UnifiedState, target, needed: list[tuple[str, str, float]]) -> CookAction | None:
        """
        烹饪缺失的食材。
        跳过已在 cooking 中、已在 assembly 中、已在 stockpile 中的食材。
        烹饪时长最长的食材优先（最大化并行重叠）。
        """
        free_cookers = [name for name, c in state.cookers.items() if not c.busy]
        if not free_cookers:
            return None

        # 收集所有可以烹饪的候选
        candidates: list[tuple[str, str, float]] = []
        for ing_name, cooker_type, duration in needed:
            if cooker_type not in free_cookers:
                continue
            if self._is_cooking(state, ing_name, cooker_type):
                continue
            if self._has_in_any_stockpile(state, ing_name, cooker_type):
                continue
            candidates.append((ing_name, cooker_type, duration))

        if not candidates:
            return None

        # 优先烹饪时间最长的
        candidates.sort(key=lambda x: x[2], reverse=True)
        ing_name, cooker_type, duration = candidates[0]
        return CookAction(ingredient=ing_name, cooker=cooker_type, duration=duration, order_id=target.order_id)

    def _has_in_any_stockpile(self, state: UnifiedState, ingredient: str, cooker_type: str) -> bool:
        return self._has_in_stockpile(state, ingredient, cooker_type)

    # ================================================================
    # Move to assembly
    # ================================================================

    def _try_move_done_to_assembly(self, state: UnifiedState, target_slug: str, assembly_ing_names: list[str]) -> MoveToAssemblyAction | None:
        target_ics = self._recipe_ingredient_cooker.get(target_slug, [])
        target_pairs = {(n, c) for n, c, _ in target_ics}

        for cooker_name, cooker in state.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            if state.time < cooker.done_at:
                continue
            if cooker.is_expired(state.time):
                continue
            ing = cooker.ingredient_name
            if (ing, cooker.cooker_type) not in target_pairs:
                continue
            if self._assembly_has_ingredient(state, ing, cooker.cooker_type):
                continue
            return MoveToAssemblyAction(cooker=cooker_name, order_id=None)

        return None

    def _assembly_has_ingredient(self, state: UnifiedState, ing_name: str, cooker_type: str) -> bool:
        for ing in state.assembly.ingredients_cookers:
            if isinstance(ing, tuple):
                stored_name = ing[0]
                stored_cooker = ing[1] if len(ing) > 1 else None
                if stored_name == ing_name and stored_cooker == cooker_type:
                    return True
            elif isinstance(ing, str) and ing == ing_name:
                return True
        return False

    # ================================================================
    # Store to stockpile (assembly 忙时释放 cooker)
    # ================================================================

    def _try_store_done_to_stockpile(self, state: UnifiedState, target_slug: str) -> MoveToStockpileAction | None:
        """将不属于当前订单的完成食材存到 stockpile（如果还有用）"""
        target_ics = self._recipe_ingredient_cooker.get(target_slug, [])
        target_ing_names = {n for n, c, _ in target_ics}

        for cooker_name, cooker in state.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            if state.time < cooker.done_at:
                continue
            if cooker.is_expired(state.time):
                continue

            ing = cooker.ingredient_name
            # 跳过匹配当前 target 的食材（应该移到 assembly）
            if ing in target_ing_names:
                continue

            # 检查是否有活跃订单需要该食材
            needed = False
            for order in state.orders:
                if order and not order.done:
                    ics = self._recipe_ingredient_cooker.get(order.recipe_slug, [])
                    order_ings = {n for n, c, _ in ics}
                    if ing in order_ings:
                        needed = True
                        break
            if not needed:
                continue

            # 找到空闲的库存 slot
            for slot_name, slot in state.stockpile.items():
                if slot.count == 0:
                    return MoveToStockpileAction(cooker=cooker_name, slot=slot_name)
                if slot.ingredient_name == ing and slot.cooker_type == cooker.cooker_type and slot.count < 5:
                    return MoveToStockpileAction(cooker=cooker_name, slot=slot_name)

        return None

    # ================================================================
    # 预烹饪
    # ================================================================

    def _try_precook_next(self, state: UnifiedState, current_target) -> CookAction | None:
        """为下一个订单预烹饪食材（如果当前订单的所有 cooker 都忙）"""
        next_target = self._get_next_target(state, current_target)
        if not next_target:
            return None

        needed = self._get_missing_ingredients(state, next_target, [])
        return self._try_cook_needed(state, next_target, needed)

    # ================================================================
    # 辅助
    # ================================================================

    def _is_cooking(self, state: UnifiedState, ingredient: str, cooker_type: str) -> bool:
        for c in state.cookers.values():
            if c.busy and c.ingredient_name == ingredient and c.cooker_type == cooker_type:
                return True
        return False
