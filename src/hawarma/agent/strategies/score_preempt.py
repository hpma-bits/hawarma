"""
ScorePreemptStrategy: 分数抢占策略

用户洞察：visibility 提高后新订单加成更高，所以应该优先高分订单，
必要时可以清空正在组装的低分订单去服务高分订单。

核心思想：
1. 订单优先级：按预计分数降序（高分优先）
2. assembly 抢占：当 assembly 中的订单分数显著低于另一个已准备好的订单时，清空 assembly
3. 烹饪目标：始终为当前最高分的活跃订单准备食材

与 ScoreAwareCPM 的区别：
- ScoreAware 用 分数/CP（效率）排序
- ScorePreempt 用纯分数排序，更激进地追求高分
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
from hawarma.agent.strategies.cpm import CPMStrategy


class ScorePreemptStrategy(CPMStrategy):
    """分数抢占：纯分数优先 + assembly 抢占"""

    # 分数抢占阈值：只有当高分订单比 assembly 订单分数高这么多时才抢占
    SCORE_PREEMPT_THRESHOLD = 30.0

    def __init__(self):
        super().__init__()
        self._reward_lookup = None

    def on_game_start(self, recipes: dict[str, object]) -> None:
        super().on_game_start(recipes)
        from hawarma.rewards import RecipeRewardLookup
        self._reward_lookup = RecipeRewardLookup()

    def _get_order_score(self, state: UnifiedState, order) -> float:
        """计算订单的预计分数（假设加调料）"""
        if self._reward_lookup is None:
            return 100.0 * (2.0 if order.is_rush else 1.0)

        row = self._reward_lookup._data.get(order.recipe_slug)
        if not row:
            return 100.0 * (2.0 if order.is_rush else 1.0)

        base = row["base_with_cond"]
        vis = row["visibility_with_cond"]
        total = base + vis
        multiplier = self._get_multiplier(state.total_visibility, order.is_rush)
        return float(total * multiplier)

    def _prioritized_orders(self, state: UnifiedState):
        """按预计分数降序排列（高分优先）"""
        active = [(i, o) for i, o in enumerate(state.orders) if o and not o.done]
        scored = []
        for slot_idx, order in active:
            score = self._get_order_score(state, order)
            scored.append((score, slot_idx, order))
        scored.sort(key=lambda x: x[0], reverse=True)  # 降序：分数高的优先
        for _, slot_idx, order in scored:
            yield slot_idx, order

    def _try_clear_assembly(self, state: UnifiedState, assembly_ings: list[str]) -> ClearAssemblyAction | None:
        """分数抢占：如果 assembly 中的订单分数显著低于另一个已准备好的订单，清空"""
        assembly = state.assembly
        if not assembly.ingredients_cookers:
            return None

        # 先执行 CPM 的清理逻辑（死锁检测）
        result = super()._try_clear_assembly(state, assembly_ings)
        if result:
            return result

        target_slug = assembly.target_recipe_slug
        if not target_slug:
            return None

        # 计算 assembly 中订单的分数
        assembly_order = None
        for o in state.orders:
            if o and not o.done and o.recipe_slug == target_slug:
                assembly_order = o
                break

        if not assembly_order:
            return None

        assembly_score = self._get_order_score(state, assembly_order)

        # 查找是否有"已准备好"且分数显著更高的订单
        for slot_idx, order in self._prioritized_orders(state):
            if order.recipe_slug == target_slug:
                continue

            # 检查订单是否已准备好
            if not self._order_is_ready(state, order):
                continue

            order_score = self._get_order_score(state, order)

            # 如果高分订单分数显著更高，抢占 assembly
            if order_score - assembly_score > self.SCORE_PREEMPT_THRESHOLD:
                return ClearAssemblyAction()

        return None

    def _get_order_id_for_ingredient(self, state: UnifiedState, ingredient: str) -> int | None:
        """为指定食材找到分数最高的订单"""
        best_order = None
        best_score = float('-inf')
        for _, order in self._prioritized_orders(state):
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe:
                raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
                if ingredient in raw:
                    score = self._get_order_score(state, order)
                    if score > best_score:
                        best_score = score
                        best_order = order
        return best_order.order_id if best_order else None

    def _try_parallel_cooking(self, state: UnifiedState, assembly_ings: list[str]) -> CookAction | None:
        """为最高分订单烹饪食材"""
        free_cookers = [name for name, c in state.cookers.items() if not c.busy]
        if not free_cookers:
            return None
        assembly = state.assembly

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
