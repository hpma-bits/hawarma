"""
VisibilityAwareStrategy: visibility 区间跨越感知策略

核心思想：
- visibility 倍率在每个阈值（40, 80, 160, 240, 360）处跳跃提升
- 完成一个能让 visibility 跨越阈值的订单，其"真实价值" = 自身分数 + 后续所有订单的额外收益
- 订单优先级 = CP（同 CPM），但跨越阈值的订单获得额外优先级加成

与 CPM 的区别：
- 优先完成那些能让 visibility 进入下一区间的订单
- 这比单纯按分数排序更精准，因为它考虑了 visibility 的阶跃效应
"""

from __future__ import annotations

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
from hawarma.agent.strategies.cpm import CPMStrategy


class VisibilityAwareStrategy(CPMStrategy):
    """visibility 跨越感知：跨越阈值的订单获得额外优先级"""

    # visibility 阈值
    VIS_THRESHOLDS = [40, 80, 160, 240, 360]
    # 跨越阈值的优先级奖励（秒），相当于 CP 减少这么多
    CROSSING_BONUS = 5.0

    def __init__(self):
        super().__init__()
        self._reward_lookup = None

    def on_game_start(self, recipes: dict[str, object]) -> None:
        super().on_game_start(recipes)
        from hawarma.core.reward import RecipeRewardLookup
        self._reward_lookup = RecipeRewardLookup()

    def _get_order_visibility(self, order) -> int:
        """获取订单完成后的 visibility 增量（假设加调料）"""
        if self._reward_lookup is None:
            return 30
        return self._reward_lookup.get_visibility(order.recipe_slug, has_condiments=True)

    def _next_threshold(self, current_vis: float) -> float | None:
        """找到下一个 visibility 阈值"""
        for t in self.VIS_THRESHOLDS:
            if current_vis < t:
                return t
        return None

    def _will_cross_threshold(self, state: UnifiedState, order) -> bool:
        """判断完成该订单是否会让 visibility 跨越阈值"""
        current_vis = state.total_visibility
        order_vis = self._get_order_visibility(order)
        next_threshold = self._next_threshold(current_vis)
        if next_threshold is None:
            return False
        return current_vis + order_vis >= next_threshold

    def _prioritized_orders(self, state: UnifiedState):
        """CPM 排序，但跨越阈值的订单 CP 减少（优先级提升）"""
        active = [(i, o) for i, o in enumerate(state.orders) if o and not o.done]
        scored = []
        for slot_idx, order in active:
            cp = self._get_critical_path(state, order)
            if self._will_cross_threshold(state, order):
                cp -= self.CROSSING_BONUS
            scored.append((cp, slot_idx, order))
        scored.sort(key=lambda x: x[0])
        for _, slot_idx, order in scored:
            yield slot_idx, order

    def _get_order_id_for_ingredient(self, state: UnifiedState, ingredient: str) -> int | None:
        """为指定食材找到优先级最高的订单"""
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
                    if cp < best_cp:
                        best_cp = cp
                        best_order = order
        return best_order.order_id if best_order else None
