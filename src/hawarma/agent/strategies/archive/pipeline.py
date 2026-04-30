"""
PipelineBaselineStrategy: 流水线 JIT baseline

核心洞察（源于用户反馈）：
  - Assembly 吞吐是真正的瓶颈（~20 orders/90s game）
  - 烹饪"对的食材"并在 assembly 需要时及时供应，比盲目 cooker 利用率更重要
  - 每局最多 ~20 单，cooking 产能过剩，assembly 才是限速器

设计：
  1. 锁定当前订单（不变），按 timeout 顺序
  2. 为当前订单并行启动所有食材 cooking（长时长优先）
  3. 食材完成 → 立即移入 assembly
  4. Assembly 完整 → 调味 serve 的同时，锁定下一订单并启动所有慢食材 cooking
  5. 不使用 stockpile（食材 cooker → assembly 直达，零库存堆积）
  6. 预测精度高（只烹饪已锁定的订单），不会浪费

与 Baseline 的关键区别：
  - Baseline: serve 前只 cooking 下一个订单的一个食材
  - Pipeline: serve 前 cooking 下一个订单的所有食材（并行启动多个 cooker）
"""

from __future__ import annotations

from hawarma.agent.agent import (
    Action,
    CookAction,
    MoveToAssemblyAction,
    AddCondimentAction,
    ServeOrderAction,
    ClearCookerAction,
    ClearAssemblyAction,
)
from hawarma.agent.unified_state import UnifiedState
from hawarma.agent.strategies.default import DefaultStrategy


class PipelineBaselineStrategy(DefaultStrategy):
    """流水线 JIT baseline"""

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

        if asm_slug and asm_slug != target_slug:
            return ClearAssemblyAction()

        if state.time >= target.timeout_at and state.assembly.ingredients_cookers:
            self._current_target_slug = None
            return ClearAssemblyAction()

        if action := self._try_clear_expired(state):
            return action

        # Assembly 完整 → 处理
        recipe = self._recipe_by_slug.get(target_slug)
        if recipe and self._ingredients_match(state.assembly.ingredients_cookers, recipe):
            return self._handle_assembly_complete(state, target)

        # Assembly 不完整 → 移入食材或烹饪
        if action := self._try_move_done_to_assembly(state, target_slug, assembly_ing_names):
            return action

        if action := self._try_cook_for_target(state, target, assembly_ing_names):
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
    # Assembly 完整：调味 serve + 并行启动下一订单所有烹饪
    # ================================================================

    def _handle_assembly_complete(self, state: UnifiedState, target):
        target_slug = target.recipe_slug

        # 先烹饪下一个订单的所有食材（使用所有空闲 cooker，长时长优先）
        cook_action = self._try_pipeline_cook_next(state, target)
        if cook_action:
            return cook_action

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

    def _try_pipeline_cook_next(self, state: UnifiedState, current_target) -> CookAction | None:
        """
        为下一个订单启动烹饪。
        使用所有空闲 cooker，长时长的食材优先（最大化并行覆盖）。
        """
        next_target = self._get_next_target(state, current_target)
        if not next_target:
            return None

        free_cookers = [name for name, c in state.cookers.items() if not c.busy]
        if not free_cookers:
            return None

        ics = self._recipe_ingredient_cooker.get(next_target.recipe_slug, [])
        candidates = []
        for ing_name, cooker_type, duration in ics:
            if cooker_type not in free_cookers:
                continue
            if self._is_cooking(state, ing_name, cooker_type):
                continue
            candidates.append((ing_name, cooker_type, duration))

        if not candidates:
            return None

        # 优先烹饪时间最长的
        candidates.sort(key=lambda x: x[2], reverse=True)
        ing_name, cooker_type, duration = candidates[0]
        return CookAction(ingredient=ing_name, cooker=cooker_type, duration=duration,
                          order_id=next_target.order_id)

    # ================================================================
    # 烹饪当前订单的缺失食材
    # ================================================================

    def _try_cook_for_target(self, state: UnifiedState, target, assembly_ing_names: list[str]) -> CookAction | None:
        free_cookers = [name for name, c in state.cookers.items() if not c.busy]
        if not free_cookers:
            return None

        ics = self._recipe_ingredient_cooker.get(target.recipe_slug, [])
        candidates = []
        for ing_name, cooker_type, duration in ics:
            if self._assembly_has_ingredient(state, ing_name, cooker_type):
                continue
            if cooker_type not in free_cookers:
                continue
            if self._is_cooking(state, ing_name, cooker_type):
                continue
            candidates.append((ing_name, cooker_type, duration))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[2], reverse=True)
        ing_name, cooker_type, duration = candidates[0]
        return CookAction(ingredient=ing_name, cooker=cooker_type, duration=duration,
                          order_id=target.order_id)

    # ================================================================
    # 移动到 assembly
    # ================================================================

    def _try_move_done_to_assembly(self, state: UnifiedState, target_slug: str, assembly_ing_names: list[str]) -> MoveToAssemblyAction | None:
        target_ics = self._recipe_ingredient_cooker.get(target_slug, [])
        # Check (name, cooker) pairs, not just names
        target_ing_cooker_pairs = {(n, c) for n, c, _ in target_ics}

        for cooker_name, cooker in state.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            if state.time < cooker.done_at:
                continue
            if cooker.is_expired(state.time):
                continue
            ing = cooker.ingredient_name
            if (ing, cooker.cooker_type) not in target_ing_cooker_pairs:
                continue
            if self._assembly_has_ingredient(state, ing, cooker.cooker_type):
                continue
            return MoveToAssemblyAction(cooker=cooker_name, order_id=None)

        return None

    def _assembly_has_ingredient(self, state: UnifiedState, ing_name: str, cooker_type: str) -> bool:
        """检查 assembly 中是否已有指定 (ingredient, cooker) 组合"""
        for ing in state.assembly.ingredients_cookers:
            if isinstance(ing, tuple):
                # Some assembly states store (name, cooker) tuples
                stored_name = ing[0]
                stored_cooker = ing[1] if len(ing) > 1 else None
                if stored_name == ing_name and stored_cooker == cooker_type:
                    return True
            elif isinstance(ing, str) and ing == ing_name:
                # Fallback: string-only ingredients (prefer false positive to avoid blocking)
                return True
        return False

    def _is_cooking(self, state: UnifiedState, ingredient: str, cooker_type: str) -> bool:
        for c in state.cookers.values():
            if c.busy and c.ingredient_name == ingredient and c.cooker_type == cooker_type:
                return True
        return False
