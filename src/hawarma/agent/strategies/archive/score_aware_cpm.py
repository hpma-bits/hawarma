"""
ScoreAwareCPMStrategy: 分数感知的关键路径法策略

核心思想（用户洞察）：
- visibility 提升后，所有新订单的分数倍率更高（1.0x -> 1.5x，rush 1.6x -> 4.0x）
- 优先完成高分/高 visibility 的订单，可以快速提升 visibility 区间
- 订单优先级 = 预计分数 / 关键路径长度（单位时间收益最高优先）

与 CPMStrategy 的区别：
- 使用 "分数/时间" 替代 "1/时间" 作为优先级权重
- 高分数订单即使耗时稍长，也可能获得更高优先级
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


class ScoreAwareCPMStrategy(CPMStrategy):
    """分数感知 CPM：按 预计分数/关键路径 排序"""

    MOVE_TIME = 0.3
    CONDIMENT_TIME = 0.3
    SERVE_TIME = 0.3

    def __init__(self):
        super().__init__()
        self._reward_lookup = None

    def on_game_start(self, recipes: dict[str, object]) -> None:
        super().on_game_start(recipes)
        from hawarma.rewards import RecipeRewardLookup
        self._reward_lookup = RecipeRewardLookup()

    def _get_multiplier(self, total_visibility: float, is_rush: bool) -> float:
        """根据 visibility 区间返回倍率（同 RecipeRewardLookup）"""
        if total_visibility < 40:
            return 1.6 if is_rush else 1.0
        if total_visibility < 80:
            return 2.0 if is_rush else 1.1
        if total_visibility < 160:
            return 2.5 if is_rush else 1.2
        if total_visibility < 240:
            return 3.0 if is_rush else 1.3
        if total_visibility < 360:
            return 3.5 if is_rush else 1.4
        return 4.0 if is_rush else 1.5

    def _get_order_score(self, state: UnifiedState, order) -> float:
        """计算订单的预计分数（假设加调料）"""
        if self._reward_lookup is None:
            # fallback: 使用 recipe 的估计值
            return 100.0 * (2.0 if order.is_rush else 1.0)

        row = self._reward_lookup._data.get(order.recipe_slug)
        if not row:
            return 100.0 * (2.0 if order.is_rush else 1.0)

        base = row["base_with_cond"]
        vis = row["visibility_with_cond"]
        total = base + vis
        multiplier = self._get_multiplier(state.total_visibility, order.is_rush)
        return float(total * multiplier)

    def _get_critical_path(self, state: UnifiedState, order) -> float:
        """计算完成该订单的预计剩余时间（同 CPM）"""
        ics = self._recipe_ingredient_cooker.get(order.recipe_slug, [])
        if not ics:
            return float('inf')

        assembly_ing_names = set()
        for ing in state.assembly.ingredients_cookers:
            if isinstance(ing, tuple):
                assembly_ing_names.add(ing[0])
            else:
                assembly_ing_names.add(ing)

        stockpile_ings: dict[str, int] = {}
        for slot in state.stockpile.values():
            if slot.count > 0 and slot.ingredient_name:
                stockpile_ings[slot.ingredient_name] = stockpile_ings.get(slot.ingredient_name, 0) + slot.count

        cooking: dict[str, float] = {}
        for c in state.cookers.values():
            if c.busy and c.ingredient_name:
                cooking[c.ingredient_name] = min(cooking.get(c.ingredient_name, float('inf')), c.done_at or 0)

        max_ing_time = 0.0
        for ing_name, cooker_type, duration in ics:
            if ing_name in assembly_ing_names:
                continue

            t_get = 0.0
            if stockpile_ings.get(ing_name, 0) > 0:
                t_get = self.MOVE_TIME
            elif ing_name in cooking:
                done_at = cooking[ing_name]
                if state.time < done_at:
                    t_get = (done_at - state.time) + self.MOVE_TIME
                else:
                    t_get = self.MOVE_TIME
            else:
                c = state.cookers.get(cooker_type)
                if c is not None and not c.busy:
                    t_get = duration + self.MOVE_TIME
                else:
                    soonest = float('inf')
                    for cc in state.cookers.values():
                        if not cc.busy:
                            soonest = state.time
                            break
                        if cc.done_at is not None:
                            soonest = min(soonest, cc.done_at)
                    wait = max(0, soonest - state.time)
                    t_get = wait + duration + self.MOVE_TIME

            max_ing_time = max(max_ing_time, t_get)

        condiments = self._recipe_condiments.get(order.recipe_slug, {})
        condiment_count = sum(condiments.values()) if condiments else 0
        condiment_time = condiment_count * self.CONDIMENT_TIME

        return max_ing_time + condiment_time + self.SERVE_TIME

    def _prioritized_orders(self, state: UnifiedState):
        """按 分数/关键路径 排序（单位时间收益最高优先）"""
        active = [(i, o) for i, o in enumerate(state.orders) if o and not o.done]
        scored = []
        for slot_idx, order in active:
            cp = self._get_critical_path(state, order)
            score = self._get_order_score(state, order)
            efficiency = score / max(cp, 0.1)  # 避免除零
            scored.append((efficiency, slot_idx, order))
        scored.sort(key=lambda x: x[0], reverse=True)  # 降序：单位时间收益高的优先
        for _, slot_idx, order in scored:
            yield slot_idx, order

    def _get_order_id_for_ingredient(self, state: UnifiedState, ingredient: str) -> int | None:
        """为指定食材找到效率最高的订单"""
        best_order = None
        best_eff = float('-inf')
        for _, order in self._prioritized_orders(state):
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe:
                raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
                if ingredient in raw:
                    eff = self._get_order_score(state, order) / max(self._get_critical_path(state, order), 0.1)
                    if eff > best_eff:
                        best_eff = eff
                        best_order = order
        return best_order.order_id if best_order else None

    def _try_parallel_cooking(self, state: UnifiedState, assembly_ings: list[str]) -> CookAction | None:
        """按分数效率选择最高优先级订单集中烹饪"""
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
