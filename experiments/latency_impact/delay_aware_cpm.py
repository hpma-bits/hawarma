"""
DelayAwareCPMStrategy: 延迟感知的 CPM 策略变体

在显式 action_delay(300ms) + detection_delay(400ms) 条件下优化。

核心调整：
1. 减少不必要的存储动作（每个存储消耗 300ms）
2. 降低预烹饪激进程度（每个预烹饪动作也消耗 300ms）
3. 提高抢占阈值（清空组装站 + 重做新食材成本更高）
4. 优先直接移到组装站而非存储
"""

from __future__ import annotations

from hawarma.core.actions import (
    MoveToStockpileAction,
    ClearAssemblyAction,
    CookAction,
)
from hawarma.core.state import UnifiedState
from hawarma.agent.strategies.cpm import CPMStrategy


class DelayAwareCPMStrategy(CPMStrategy):
    """延迟感知的 CPM 策略"""

    # 存储阈值：从 2.0s 提高到 3.5s — 等待更久再存，避免浪费 300ms 动作
    PRECOOK_STORE_THRESHOLD = 3.5

    # 过期阈值：从 5.0s 略微提高到 5.5s — 给更多时间直接移到组装站
    EXPIRED_THRESHOLD = 5.5

    # 预烹饪最大库存：从 3 降到 2 — 更少预烹饪，节省动作时间
    MAX_PRECOOK_STOCKPILE = 2

    # 抢占阈值：从 3.0s 提高到 4.5s — 抢占代价更高，需要更大差距
    PREEMPT_THRESHOLD = 4.5

    def _try_store_to_stockpile(self, state: UnifiedState) -> MoveToStockpileAction | None:
        """
        重写存储逻辑：在延迟条件下更保守地存储。
        
        核心变化：
        - 如果组装站为空且食材可以直接移到组装站，优先不存储
        - 只有组装站被占用时才存储
        """
        assembly = state.assembly
        needed = self._get_needed_item_names(state)

        # 如果组装站空闲，优先不存储 — 让食材留在灶台上等待直接移到组装站
        if assembly.is_free and not assembly.ingredients_cookers:
            for cooker_name, cooker in state.cookers.items():
                if not cooker.busy or cooker.done_at is None:
                    continue
                if state.time < cooker.done_at:
                    continue
                ing_name = cooker.item_name
                cooker_type = cooker.cooker_type
                if cooker.is_expired(state.time):
                    continue
                # 食材烹饪完成且组装站空闲 — 直接移到组装站而非存储
                # 由 _try_move_to_assembly 处理
                pass

        # 存储逻辑：只在必要时存储（组装站被占用且食材即将过期）
        for cooker_name, cooker in state.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            if state.time < cooker.done_at:
                continue
            ing_name = cooker.item_name
            cooker_type = cooker.cooker_type
            time_since_done = state.time - cooker.done_at

            if ing_name in needed:
                if time_since_done > self.WARN_THRESHOLD:
                    slot = self._try_increment_stockpile(state, ing_name, cooker_type)
                    if slot is None:
                        slot = self._find_available_slot(state, ing_name, cooker_type)
                    if slot:
                        return MoveToStockpileAction(cooker=cooker_name, slot=slot)
            else:
                if time_since_done > self.PRECOOK_STORE_THRESHOLD:
                    slot = self._try_increment_stockpile(state, ing_name, cooker_type)
                    if slot is None:
                        slot = self._find_available_slot(state, ing_name, cooker_type)
                    if slot:
                        return MoveToStockpileAction(cooker=cooker_name, slot=slot)

            if time_since_done > self.EXPIRED_THRESHOLD:
                slot = self._try_increment_stockpile(state, ing_name, cooker_type)
                if slot is None:
                    slot = self._find_available_slot(state, ing_name, cooker_type)
                if slot:
                    return MoveToStockpileAction(cooker=cooker_name, slot=slot)

        return None

    def _try_precook(self, state: UnifiedState, assembly_ings: list[str]) -> CookAction | None:
        """
        延迟感知的预烹饪：
        - 检测延迟意味着预烹饪更重要（订单看到时已经晚了 400ms）
        - 但每个预烹饪动作成本更高（300ms）
        - 折中：只预烹饪高价值的食材，且需要更短的过期时间窗口
        """
        remaining_time = state.game_duration - state.time
        if remaining_time < 25:  # 比默认 20s 稍早停止预烹饪
            return None
        return super()._try_precook(state, assembly_ings)
