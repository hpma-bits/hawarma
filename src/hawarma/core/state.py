"""
UnifiedState: 环境对 Strategy 暴露的统一观测

frozen=True 确保 Strategy 不会意外修改状态。
Strategy 的唯一输入，由 Env 的 get_unified_state() 构造。
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    AssemblyState,
    CookerState,
    OrderInfo,
    StockpileSlot,
)


@dataclass(frozen=True)
class UnifiedState:
    """
    统一观测状态。

    包含 Strategy 做决策所需的全部信息。
    frozen=True 保证 Strategy 无法修改环境状态。
    """

    time: float
    """当前游戏时间（秒）"""

    orders: tuple[OrderInfo | None, ...]
    """4个订单槽位的状态"""

    cookers: dict[str, CookerState]
    """灶台名称 -> 状态的映射"""

    assembly: AssemblyState
    """组装站状态（gastronome 专用）"""

    stockpile: dict[str, StockpileSlot]
    """库存槽位名称 -> 状态的映射"""

    recipes: dict[str, object]
    """当前局可用配方 slug -> Recipe 的映射"""

    game_duration: float
    """本局游戏总时长（秒）"""

    is_in_animation_window: bool
    """是否处于动画窗口期间"""

    total_visibility: float = 0.0
    """已完成订单的总 visibility（用于得分加成）"""

    @property
    def remaining_time(self) -> float:
        """剩余游戏时间"""
        return max(0.0, self.game_duration - self.time)