"""
PreemptScoreStrategy: 分数权重抢占策略

核心洞察（来自效率指标分析）：
  - 后期 cooker idle 80% 的根本原因是 assembly 饱和
  - 当 assembly 被长订单占用时，短高价值订单在排队
  - stockpile 堆积食材，但 assembly 吞吐受限

策略设计：
  1. 订单优先级 = 预估分数 / 关键路径（单位时间收益）
  2. 智能抢占：当 assembly 订单还需 T 秒且已投入少时，
     如果另一订单能在 T 秒内完成且收益更高，抢占 assembly
  3. 抢占门槛：只抢占 assembly 中食材数 <= 1 的订单（避免浪费）
  4. 超时保护：接近 timeout 的订单获得优先保护，不被抢占

与 CPMStrategy 的区别：
  - 优先级从纯 CP 改为 score/CP
  - 抢占逻辑更激进但有安全阀（食材数门槛 + 超时保护）
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


class PreemptScoreStrategy(CPMStrategy):
    """分数感知抢占：score/CP 排序 + 进度感知抢占"""

    # 抢占条件：assembly 中食材数 <= 这个阈值才允许抢占
    MAX_ASSEMBLY_INGREDIENTS_FOR_PREEMPT = 1

    # 超时安全窗：timeout 在 N 秒内的订单不被抢占
    TIMEOUT_SAFE_WINDOW = 8.0

    # 抢占收益比：目标订单的单位收益必须比当前高这么多
    # 1.0 = 只要效率不低就抢占；1.0 配合食材数门槛已经很安全
    PREEMPT_EFFICIENCY_RATIO = 1.0

    def __init__(self):
        super().__init__()
        self._reward_lookup = None

    def on_game_start(self, recipes: dict[str, object]) -> None:
        super().on_game_start(recipes)
        from hawarma.rewards import RecipeRewardLookup
        self._reward_lookup = RecipeRewardLookup()

    # ================================================================
    # 订单优先级：分数 / 关键路径
    # ================================================================

    def _get_order_score(self, state: UnifiedState, order) -> float:
        """预估订单完成后的得分（假设加调料）"""
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
        """按 分数/CP 降序排列（单位时间收益高优先）"""
        active = [(i, o) for i, o in enumerate(state.orders) if o and not o.done]
        scored = []
        for slot_idx, order in active:
            cp = self._get_critical_path(state, order)
            score = self._get_order_score(state, order)
            efficiency = score / max(cp, 0.5)
            scored.append((efficiency, slot_idx, order))
        scored.sort(key=lambda x: x[0], reverse=True)
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
                    eff = self._get_order_score(state, order) / max(self._get_critical_path(state, order), 0.5)
                    if eff > best_eff:
                        best_eff = eff
                        best_order = order
        return best_order.order_id if best_order else None

    # ================================================================
    # 智能抢占：进度感知 + 超时保护
    # ================================================================

    def _try_clear_assembly(self, state: UnifiedState, assembly_ings: list[str]) -> ClearAssemblyAction | None:
        """智能抢占：只在当前投入少且目标收益显著更高时抢占"""
        assembly = state.assembly
        if not assembly.ingredients_cookers:
            return None

        # 1) 先用 DefaultStrategy 检查死锁
        result = super()._try_clear_assembly(state, assembly_ings)
        if result:
            return result

        target_slug = assembly.target_recipe_slug
        if not target_slug:
            return None

        # 2) 检查是否有活跃的 assembly 目标订单
        assembly_order = None
        for o in state.orders:
            if o and not o.done and o.recipe_slug == target_slug:
                assembly_order = o
                break
        if not assembly_order:
            return None

        # 3) 抢占比门槛：只抢 assembly 中食材数少的（投入小）
        if len(assembly.ingredients_cookers) > self.MAX_ASSEMBLY_INGREDIENTS_FOR_PREEMPT:
            return None

        # 4) 计算当前订单的超时情况
        assembly_timeout_remaining = assembly_order.timeout_at - state.time
        assembly_ing_ready = all(
            isinstance(ing, tuple) and ing[0] in assembly_ings
            for ing in assembly.ingredients_cookers
        )

        # 5) 计算当前订单的预计完成时间
        assembly_cp = self._get_critical_path(state, assembly_order)
        assembly_score = self._get_order_score(state, assembly_order)
        assembly_eff = assembly_score / max(assembly_cp, 0.5)

        # 6) 寻找更好的抢占比目标
        for slot_idx, order in self._prioritized_orders(state):
            if order.recipe_slug == target_slug:
                continue

            # 超时保护：目标订单不在即将超时的窗口内才考虑抢占
            order_timeout_remaining = order.timeout_at - state.time
            if order_timeout_remaining < self.TIMEOUT_SAFE_WINDOW:
                continue

            # 检查目标订单是否已准备好 serve（所有食材立即可用）
            if not self._order_is_ready(state, order):
                continue

            # 检查目标订单的收益效率是否显著更高
            order_cp = self._get_critical_path(state, order)
            order_score = self._get_order_score(state, order)
            order_eff = order_score / max(order_cp, 0.5)

            if order_eff > assembly_eff * self.PREEMPT_EFFICIENCY_RATIO:
                return ClearAssemblyAction()

        return None

    def _order_is_ready(self, state: UnifiedState, order) -> bool:
        """检查订单的所有食材是否已可立即获取"""
        ics = self._recipe_ingredient_cooker.get(order.recipe_slug, [])
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

        cooking_done: dict[str, bool] = {}
        for c in state.cookers.values():
            if c.busy and c.ingredient_name:
                done_at = c.done_at
                if done_at is not None and state.time >= done_at:
                    cooking_done[c.ingredient_name] = True

        for ing_name, cooker_type, duration in ics:
            if ing_name in assembly_ing_names:
                continue
            if stockpile_ings.get(ing_name, 0) > 0:
                continue
            if cooking_done.get(ing_name, False):
                continue
            return False
        return True
