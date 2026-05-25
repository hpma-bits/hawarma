"""
DelayAwareCPMStrategyV2: 延迟感知策略 - 预烹饪激进版

核心思路：
- detection_delay(400ms) 意味着 agent 看到订单时已经晚了 400ms
- 解决方案：更激进地预烹饪，通过库存缓冲来抵消检测延迟
- action_delay(300ms) 的成本被预烹饪节省的烹饪时间所覆盖

与 V1 的区别：V1 减少动作，V2 更智能地增加高价值动作。
"""

from __future__ import annotations

from hawarma.core.actions import (
    MoveToStockpileAction,
    CookAction,
)
from hawarma.core.state import UnifiedState
from hawarma.agent.strategies.cpm import CPMStrategy


class DelayAwareCPMStrategyV2(CPMStrategy):
    """
    延迟感知策略 V2 — 激进预烹饪版。

    核心调整：
    1. 预烹饪更激进：检测延迟意味着预烹饪更有价值
    2. 更快存入库存：烹饪完成即存，腾出灶台做更多预烹饪
    3. 更晚停止预烹饪：游戏结束前一直做
    4. 优先从库存取用：库存食材可以立即使用，节省检测+烹饪延迟
    """

    # 存储更快：从 2.0s 降到 1.5s — 更快腾出灶台做更多预烹饪
    PRECOOK_STORE_THRESHOLD = 1.5

    # 警告阈值：从 4.0s 降到 3.0s — 更快决定存储
    WARN_THRESHOLD = 3.0

    # 预烹饪最大库存：从 3 提高到 4 — 更激进地囤货
    MAX_PRECOOK_STOCKPILE = 4

    # 更晚停止预烹饪：剩余 15s 再停（默认 20s）
    # 这样在游戏后期还能多做预烹饪，弥补检测延迟
    PRECOOK_STOP_TIME = 15.0

    def _try_precook(self, state: UnifiedState, assembly_ings: list[str]) -> CookAction | None:
        """
        更激进的预烹饪：
        - 更晚停止（15s 剩余才停，而非 20s）
        - 更宽松的库存检查
        """
        remaining_time = state.game_duration - state.time
        if remaining_time < self.PRECOOK_STOP_TIME:
            return None
        return super()._try_precook(state, assembly_ings)

    def _try_store_to_stockpile(self, state: UnifiedState) -> MoveToStockpileAction | None:
        """
        更积极的存储逻辑：
        烹饪完成就尽快存，不要等 3.5s。
        腾出灶台才能做更多预烹饪。
        """
        assembly = state.assembly
        needed = self._get_needed_item_names(state)

        for cooker_name, cooker in state.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            if state.time < cooker.done_at:
                continue
            ing_name = cooker.item_name
            cooker_type = cooker.cooker_type
            time_since_done = state.time - cooker.done_at

            # 更积极地存储：任何烹饪完成的食材都尽快存
            if time_since_done > self.PRECOOK_STORE_THRESHOLD:
                slot = self._try_increment_stockpile(state, ing_name, cooker_type)
                if slot is None:
                    slot = self._find_available_slot(state, ing_name, cooker_type)
                if slot:
                    return MoveToStockpileAction(cooker=cooker_name, slot=slot)

            # 食材需要的也存储（比默认更快）
            if ing_name in needed and time_since_done > 1.0:
                slot = self._try_increment_stockpile(state, ing_name, cooker_type)
                if slot is None:
                    slot = self._find_available_slot(state, ing_name, cooker_type)
                if slot:
                    return MoveToStockpileAction(cooker=cooker_name, slot=slot)

            # 过期前强制存储
            if time_since_done > self.EXPIRED_THRESHOLD:
                slot = self._try_increment_stockpile(state, ing_name, cooker_type)
                if slot is None:
                    slot = self._find_available_slot(state, ing_name, cooker_type)
                if slot:
                    return MoveToStockpileAction(cooker=cooker_name, slot=slot)

        return None
