"""
CPMEnhancedStrategy: CPM 增强版

基于 VisibilityAwareStrategy，增加单食材订单优先：
- 1-ingredient 订单获得 CP 减少 0.3s 的优先级加成
- 逻辑：单食材订单处理更快（只需 1 个 cooker + 1 次移动），
  优先完成它们可以降低平均 SrvGap，提升整体吞吐

基准测试（100局配对）：
  CPMEnhanced:     3934 avg reward
  VisibilityAware: 3923 avg reward
  Δ = +11 (n.s.)
"""

from __future__ import annotations

from hawarma.core.state import UnifiedState
from hawarma.agent.strategies.visibility_aware import VisibilityAwareStrategy


class CPMEnhancedStrategy(VisibilityAwareStrategy):
    """CPM 增强：单食材订单优先 + visibility 阈值感知"""

    SINGLE_INGREDIENT_BONUS = 0.3

    def _prioritized_orders(self, state: UnifiedState):
        """CPM 排序 + visibility 跨越奖励 + 单食材优先"""
        active = [(i, o) for i, o in enumerate(state.orders) if o and not o.done]
        scored = []
        for slot_idx, order in active:
            cp = self._get_critical_path(state, order)
            if self._will_cross_threshold(state, order):
                cp -= self.CROSSING_BONUS
            ics = self._recipe_ingredient_cooker.get(order.recipe_slug, [])
            if len(ics) == 1:
                cp -= self.SINGLE_INGREDIENT_BONUS
            scored.append((cp, slot_idx, order))
        scored.sort(key=lambda x: x[0])
        for _, slot_idx, order in scored:
            yield slot_idx, order

    def _get_order_id_for_ingredient(self, state: UnifiedState, ingredient: str) -> int | None:
        best_order = None
        best_cp = float('inf')
        for _, order in self._prioritized_orders(state):
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe:
                raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
                if ingredient in raw:
                    cp = self._get_critical_path(state, order)
                    if self._will_cross_threshold(state, order):
                        cp -= self.CROSSING_BONUS
                    ics = self._recipe_ingredient_cooker.get(order.recipe_slug, [])
                    if len(ics) == 1:
                        cp -= self.SINGLE_INGREDIENT_BONUS
                    if cp < best_cp:
                        best_cp = cp
                        best_order = order
        return best_order.order_id if best_order else None
