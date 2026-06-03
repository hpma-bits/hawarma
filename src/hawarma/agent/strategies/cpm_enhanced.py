"""
CPMEnhancedCascadeStrategy: 贪心瀑布 - CPM 增强变体（当前最优）

覆写 _prioritized_orders：CP 排序 + visibility 跨越奖励 + 单食材订单优先（CP -0.3s）。
继承自 VisibilityAwareCascadeStrategy。

基准测试（100局配对）：
  CPMEnhancedCascadeStrategy:  3934 avg reward
  VisibilityAwareCascadeStrategy: 3923 avg reward
  Δ = +11 (n.s.)
"""

from __future__ import annotations

from hawarma.core.state import UnifiedState
from hawarma.agent.strategies.visibility_aware import VisibilityAwareCascadeStrategy


class CPMEnhancedCascadeStrategy(VisibilityAwareCascadeStrategy):
    """贪心瀑布变体：CP + visibility + 单食材优先（当前最优）"""

    SINGLE_INGREDIENT_BONUS = 0.3

    def _prioritized_orders(self, state: UnifiedState):
        """CPM 排序 + visibility 跨越奖励 + 单食材优先 + Rush tiebreaker"""
        active = [(i, o) for i, o in enumerate(state.orders) if o and not o.done]
        scored = []
        for slot_idx, order in active:
            cp = self._get_critical_path(state, order)
            if self._will_cross_threshold(state, order):
                cp -= self.CROSSING_BONUS
            ics = self._recipe_ingredient_cooker.get(order.recipe_slug, [])
            if len(ics) == 1:
                cp -= self.SINGLE_INGREDIENT_BONUS
            rush_priority = 0 if order.is_rush else 1
            scored.append((cp, rush_priority, slot_idx, order))
        scored.sort(key=lambda x: (x[0], x[1]))
        for _, _, slot_idx, order in scored:
            yield slot_idx, order

    def _get_order_id_for_ingredient(self, state: UnifiedState, ingredient: str) -> int | None:
        best_order = None
        best_cp = float('inf')
        for _, order in self._prioritized_orders(state):
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe:
                if ingredient in recipe.raw_ingredients:
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


# 向后兼容别名
CPMEnhancedStrategy = CPMEnhancedCascadeStrategy
