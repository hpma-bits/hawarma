"""
CPMCascadeStrategy: 贪心瀑布 - 关键路径法变体（Critical Path Method）

覆写 _prioritized_orders（CP 排序）、_try_clear_assembly（抢占）、
_try_parallel_cooking（CPM 评分），新增 _get_critical_path 计算订单预计剩余时间。

核心思想（运筹学）：
1. 每个订单是一个项目，食材准备是并行活动
2. 关键路径长度 = 完成该订单的预计剩余时间
3. 优先服务关键路径最短的订单（SPT - Shortest Processing Time）
4. 当 assembly 被长订单占用时，如果短订单已准备好，抢占 assembly
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
from hawarma.agent.strategies.default import GreedyCascadeStrategy


class CPMCascadeStrategy(GreedyCascadeStrategy):
    """贪心瀑布变体：CP 排序 + assembly 抢占"""

    # 操作耗时估算（秒）
    MOVE_TIME = 0.3
    CONDIMENT_TIME = 0.3
    SERVE_TIME = 0.3
    
    # 抢占阈值：只有当短订单 CP 比 assembly 订单 CP 短这么多时才抢占
    PREEMPT_THRESHOLD = 3.0

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

    def _get_critical_path(self, state: UnifiedState, order) -> float:
        """
        计算完成该订单的预计剩余时间（关键路径长度）。
        """
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
            if slot.count > 0 and slot.item_name:
                stockpile_ings[slot.item_name] = stockpile_ings.get(slot.item_name, 0) + slot.count

        cooking: dict[str, float] = {}
        for c in state.cookers.values():
            if c.busy and c.item_name:
                cooking[c.item_name] = min(cooking.get(c.item_name, float('inf')), c.done_at or 0)

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
                free_cooker = self._find_free_cooker_for(state, ing_name, cooker_type)
                if free_cooker:
                    t_get = duration + self.MOVE_TIME
                else:
                    soonest_free = self._soonest_free_cooker(state)
                    wait = max(0, soonest_free - state.time)
                    t_get = wait + duration + self.MOVE_TIME

            max_ing_time = max(max_ing_time, t_get)

        condiments = self._recipe_condiments.get(order.recipe_slug, {})
        condiment_count = sum(condiments.values()) if condiments else 0
        condiment_time = condiment_count * self.CONDIMENT_TIME

        return max_ing_time + condiment_time + self.SERVE_TIME

    def _find_free_cooker_for(self, state: UnifiedState, ing_name: str, cooker_type: str) -> bool:
        c = state.cookers.get(cooker_type)
        return c is not None and not c.busy

    def _soonest_free_cooker(self, state: UnifiedState) -> float:
        soonest = float('inf')
        for c in state.cookers.values():
            if not c.busy:
                return state.time
            if c.done_at is not None:
                soonest = min(soonest, c.done_at)
        return soonest if soonest != float('inf') else state.time

    def _order_is_ready(self, state: UnifiedState, order) -> bool:
        """检查订单是否已准备好（所有食材可立即获取）"""
        ics = self._recipe_ingredient_cooker.get(order.recipe_slug, [])
        assembly_ing_names = set()
        for ing in state.assembly.ingredients_cookers:
            if isinstance(ing, tuple):
                assembly_ing_names.add(ing[0])
            else:
                assembly_ing_names.add(ing)
        
        stockpile_ings: dict[str, int] = {}
        for slot in state.stockpile.values():
            if slot.count > 0 and slot.item_name:
                stockpile_ings[slot.item_name] = stockpile_ings.get(slot.item_name, 0) + slot.count
        
        cooking_done: dict[str, bool] = {}
        for c in state.cookers.values():
            if c.busy and c.item_name and c.done_at and state.time >= c.done_at:
                cooking_done[c.item_name] = True
        
        for ing_name, cooker_type, duration in ics:
            if ing_name in assembly_ing_names:
                continue
            if stockpile_ings.get(ing_name, 0) > 0:
                continue
            if cooking_done.get(ing_name, False):
                continue
            return False
        return True

    def _prioritized_orders(self, state: UnifiedState):
        """按关键路径长度排序（短的优先），CP 相同时 Rush 优先"""
        active = [(i, o) for i, o in enumerate(state.orders) if o and not o.done]
        scored = []
        for slot_idx, order in active:
            cp = self._get_critical_path(state, order)
            rush_priority = 0 if order.is_rush else 1
            scored.append((cp, rush_priority, slot_idx, order))
        scored.sort(key=lambda x: (x[0], x[1]))
        for _, _, slot_idx, order in scored:
            yield slot_idx, order

    def _try_clear_assembly(self, state: UnifiedState, assembly_ings: list[str]) -> ClearAssemblyAction | None:
        """CPM 抢占：如果长订单阻塞了短订单，清空 assembly"""
        assembly = state.assembly
        if not assembly.ingredients_cookers:
            return None
        
        # 先执行基类的清理逻辑
        result = super()._try_clear_assembly(state, assembly_ings)
        if result:
            return result
        
        # CPM 抢占逻辑
        target_slug = assembly.target_recipe_slug
        if not target_slug:
            return None
        
        # 计算 assembly 中订单的关键路径
        assembly_order = None
        for o in state.orders:
            if o and not o.done and o.recipe_slug == target_slug:
                assembly_order = o
                break
        
        if not assembly_order:
            return None
        
        assembly_cp = self._get_critical_path(state, assembly_order)
        
        # 查找是否有"已准备好"且关键路径显著更短的订单
        for slot_idx, order in self._prioritized_orders(state):
            if order.recipe_slug == target_slug:
                continue
            
            # 检查订单是否已准备好（所有食材可立即获取）
            if not self._order_is_ready(state, order):
                continue
            
            order_cp = self._get_critical_path(state, order)
            
            # 如果短订单 CP 显著更短，抢占 assembly
            if assembly_cp - order_cp > self.PREEMPT_THRESHOLD:
                return ClearAssemblyAction()
        
        return None

    def _get_order_id_for_ingredient(self, state: UnifiedState, ingredient: str) -> int | None:
        """为指定食材找到关键路径最短的订单"""
        best_order = None
        best_cp = float('inf')
        for _, order in self._prioritized_orders(state):
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe:
                if ingredient in recipe.raw_ingredients:
                    cp = self._get_critical_path(state, order)
                    if cp < best_cp:
                        best_cp = cp
                        best_order = order
        return best_order.order_id if best_order else None

    def _try_parallel_cooking(self, state: UnifiedState, assembly_ings: list[str]) -> CookAction | None:
        """CPM 烹饪：优先为 CP 最短的订单烹饪，但高优先级订单阻塞时 fallback 到其他订单"""
        free_cookers = [name for name, c in state.cookers.items() if not c.busy]
        if not free_cookers:
            return None
        assembly = state.assembly

        # 如果 assembly 已被活跃订单占用，只烹饪该订单需要的食材
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
                # assembly 订单食材全部不可用，fallback 到其他活跃订单
                pass

        # 收集所有活跃订单需要的食材，按 CPM 优先级排序（高优先级在前）
        candidates: list[tuple[str, str, float, float]] = []
        seen: set[tuple[str, str]] = set()
        for _, order in self._prioritized_orders(state):
            ics = self._recipe_ingredient_cooker.get(order.recipe_slug, [])
            for ing_name, cooker, duration in ics:
                combo = (ing_name, cooker)
                if combo in seen:
                    continue
                seen.add(combo)
                if ing_name in assembly_ings:
                    continue
                if cooker not in free_cookers:
                    continue
                if self._is_cooking(state, ing_name, cooker):
                    continue
                if self._has_in_stockpile(state, ing_name, cooker):
                    continue
                cp = self._get_critical_path(state, order)
                # score: CP 越短优先级越高（用负 CP 排序，同时烹饪时长长的优先）
                score = -cp + duration
                candidates.append((ing_name, cooker, duration, score))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[3], reverse=True)
        ing_name, cooker, duration, _ = candidates[0]
        order_id = self._get_order_id_for_ingredient(state, ing_name)
        return CookAction(ingredient=ing_name, cooker=cooker, duration=duration, order_id=order_id)


# 向后兼容别名
CPMStrategy = CPMCascadeStrategy
