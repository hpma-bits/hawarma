"""
BaselineStrategy: 按超时顺序串行处理 + 不使用 stockpile

设计原则（最简洁的基线策略）：
  1. 按订单过期时间从早到晚依次处理（锁定当前订单，完成前不切换）
  2. 每次只烹饪一道菜品的食材（聚焦式，不并行多订单）
  3. 不使用 stockpile（食材从不移到库存，也不从库存取用）
  4. 所有在同一时刻正在烹饪的食材都属于同一个订单
  5. 烹饪完成就移到 assembly 组装
  6. 关键优化：assembly 食材齐全时，先为下一个订单启动 cooking，
     再对当前 assembly 进行调味和 serve（cook 与 add_cond/serve 重叠）

预期行为：
  - 绝不出现食材过期（因为只为一个订单烹饪，完成后立即移入 assembly）
  - assembly 中始终只有一个订单的食材
  - cooker 利用率由订单的食材数量决定（单食材订单只用一个 cooker）
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


class BaselineStrategy(DefaultStrategy):
    """
    基线策略：timeout 优先 + 单订单聚焦 + 无 stockpile + 不切换。

    与 DefaultStrategy/CPM 的关键区别：
    - 锁定当前订单直到完成（不变更 target）
    - 不预烹饪，不为其他订单烹饪食材
    - 不使用 stockpile
    """

    def __init__(self):
        super().__init__()
        self._current_target_slug: str | None = None
        """当前锁定的订单 recipe，serve 前不切换"""

    def reset(self) -> None:
        """新游戏开始时重置状态"""
        super().reset()
        self._current_target_slug = None

    def decide(self, state: UnifiedState) -> Action | None:
        """单订单聚焦决策，锁定 target 直到完成"""

        # ── 1) 确定当前目标订单 ──
        target = self._get_or_lock_target(state)
        if target is None:
            return None

        target_slug = target.recipe_slug

        # ── 2) 如果 assembly 属于其他订单 → 该订单已不在活跃列表中（应该已服务/超时）→ 清空 ──
        asm_slug = state.assembly.target_recipe_slug
        if asm_slug and asm_slug != target_slug:
            return ClearAssemblyAction()

        assembly_ing_names = [ing[0] if isinstance(ing, tuple) else ing for ing in state.assembly.ingredients_cookers]

        # ── 3) 如果目标订单已超时且 assembly 中有食材 → 清空 ──
        if state.time >= target.timeout_at and state.assembly.ingredients_cookers:
            self._current_target_slug = None
            return ClearAssemblyAction()

        # ── 4) 清理过期的 cooker ──
        if action := self._try_clear_expired(state):
            return action

        # ── 5) Assembly 完整 → 调味然后 serve
        #      但在 serve 之前，先为下一个订单启动 cooking
        recipe = self._recipe_by_slug.get(target_slug)
        if recipe and self._ingredients_match(state.assembly.ingredients_cookers, recipe):
            # 先烹饪下一个订单（如果还没开始）
            next_target = self._get_next_target(state, target)
            if next_target:
                cook_action = self._try_cook_for_order(state, next_target)
                if cook_action:
                    return cook_action

            # 加调料
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

        # ── 6) Assembly 不完整：先移入已完成的食材 ──
        if action := self._try_move_done_to_assembly(state, target_slug, assembly_ing_names):
            return action

        # ── 7) 烹饪缺失的食材 ──
        if action := self._try_cook_for_order(state, target):
            return action

        return None

    # ================================================================
    # 订单锁定
    # ================================================================

    def _get_or_lock_target(self, state: UnifiedState):
        """
        获取当前目标订单。
        如果已有锁定的 target 且仍活跃 → 保持不变。
        如果锁定的 target 已不在活跃列表中 → 解锁并重新选择。
        """
        if self._current_target_slug:
            # 检查锁定的订单是否仍在活跃列表中
            for o in state.orders:
                if o and not o.done and o.recipe_slug == self._current_target_slug:
                    return o
            # 锁定的订单已不在活跃列表（已 serve 或 timeout）
            self._current_target_slug = None

        # 选择最早到期的活跃订单并锁定
        target = self._get_earliest_timeout_order(state)
        if target:
            self._current_target_slug = target.recipe_slug
        return target

    def _get_earliest_timeout_order(self, state: UnifiedState):
        """返回最早过期的活跃订单（优先 rush）"""
        active = [o for o in state.orders if o and not o.done]
        if not active:
            return None
        active.sort(key=lambda o: (0 if o.is_rush else 1, o.timeout_at))
        return active[0]

    def _get_next_target(self, state: UnifiedState, current_target):
        """返回下一个最早到期的订单（排除当前 target）"""
        active = [o for o in state.orders if o and not o.done and o is not current_target]
        if not active:
            return None
        active.sort(key=lambda o: (0 if o.is_rush else 1, o.timeout_at))
        return active[0]

    # ================================================================
    # 烹饪（不使用 stockpile，所有 cookers 只为当前目标服务）
    # ================================================================

    def _try_cook_for_order(self, state: UnifiedState, target) -> CookAction | None:
        """为目标订单烹饪一个缺失的食材"""
        target_slug = target.recipe_slug
        ics = self._recipe_ingredient_cooker.get(target_slug, [])
        if not ics:
            return None

        for ing_name, cooker_type, duration in ics:
            if self._assembly_has_ingredient(state, ing_name, cooker_type):
                continue
            if self._is_cooking(state, ing_name, cooker_type):
                continue
            cooker = state.cookers.get(cooker_type)
            if cooker is None or cooker.busy:
                continue
            return CookAction(ingredient=ing_name, cooker=cooker_type, duration=duration, order_id=target.order_id)

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

    def _is_cooking(self, state: UnifiedState, ingredient: str, cooker_type: str) -> bool:
        for c in state.cookers.values():
            if c.busy and c.ingredient_name == ingredient and c.cooker_type == cooker_type:
                return True
        return False

    # ================================================================
    # 移动到 assembly
    # ================================================================

    def _try_move_done_to_assembly(self, state: UnifiedState, target_slug: str, assembly_ing_names: list[str]) -> MoveToAssemblyAction | None:
        target_ics = self._recipe_ingredient_cooker.get(target_slug, [])
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
