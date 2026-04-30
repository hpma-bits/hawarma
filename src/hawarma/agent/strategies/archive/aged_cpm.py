"""
AgedCPMStrategy: 带老化机制的 CPM 调度

核心洞察：
  - SPT（最短处理时间优先）导致单食材快订单永远霸占最高优先级
  - 多食材高价值订单（feast, newYearJiaozi）被不断地新来的快订单"插队"
  - 后期 grill/pot 闲置 80% 是因为这些多 cooker 订单排不上号

解决方案：老化调度（Aging Schedule）
  类似操作系统进程调度的 multi-level feedback queue：
  - 新订单按 CP 排序（SPT 优先）
  - 等待时间每超过 grace_period 1 秒，CP 减少 aging_rate 秒
  - 等价于：订单越老，"虚拟 CP" 越短，优先级越高
  - 参数：aging_rate=0.3, grace_period=10s
"""

from __future__ import annotations

from hawarma.agent.unified_state import UnifiedState
from hawarma.agent.strategies.cpm import CPMStrategy


class AgedCPMStrategy(CPMStrategy):
    """老化 CPM：SPT + 老化因子，防止短订单饥饿长订单"""

    # 老化系数：每等待 1 秒，CP 减少 0.3 秒（优先级提高）
    AGING_RATE = 0.3
    # 宽限期：前 10s 内不受老化影响
    GRACE_PERIOD = 10.0
    # rush 订单的宽限期更短（更早获得优先级提升）
    RUSH_GRACE_PERIOD = 5.0
    # rush 订单的老化系数更高（更快提升优先级）
    RUSH_AGING_RATE = 0.5

    def _prioritized_orders(self, state: UnifiedState):
        """按 老化CP 排序：CP - aging_bonus，值越小优先级越高"""
        active = [(i, o) for i, o in enumerate(state.orders) if o and not o.done]
        scored = []
        for slot_idx, order in active:
            cp = self._get_critical_path(state, order)
            # 计算老化时间
            wait_time = state.time - order.created_at
            if order.is_rush:
                grace = self.RUSH_GRACE_PERIOD
                rate = self.RUSH_AGING_RATE
            else:
                grace = self.GRACE_PERIOD
                rate = self.AGING_RATE

            aging_bonus = max(0, wait_time - grace) * rate
            aged_cp = max(0.5, cp - aging_bonus)
            scored.append((aged_cp, slot_idx, order))
        scored.sort(key=lambda x: x[0])
        for _, slot_idx, order in scored:
            yield slot_idx, order
