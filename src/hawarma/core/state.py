"""
UnifiedState: 环境对 Strategy 暴露的统一观测

Strategy 的唯一输入，由 Env 的 get_unified_state() 构造。

不可变语义（#16）：
- frozen=True 只冻结 UnifiedState 自身的顶层字段（不可重新绑定 time/orders 等）；
- 元素级隔离由 Env 侧保证：orders/cookers/assembly/stockpile/mixing_bowl 均为
  各自 snapshot() 的字段级深拷贝，与 Env 内部状态无共享可变对象，
  Strategy 篡改嵌套对象也不会污染环境；
- recipes 为静态配置数据，Recipe 对象只读共享，仅拷贝 dict 容器。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import (
    AssemblyState,
    CookerState,
    MixingBowlState,
    Order,
    StockpileSlot,
)
from hawarma.recipe import Recipe


@dataclass(frozen=True)
class UnifiedState:
    """
    统一观测状态。

    包含 Strategy 做决策所需的全部信息。
    frozen=True 冻结顶层字段不可重新绑定；嵌套子状态由 Env 的
    get_unified_state() 以 snapshot() 深拷贝提供，观测与内部状态完全隔离。
    """

    time: float
    """当前游戏时间（秒）"""

    orders: tuple[Order | None, ...]
    """4个订单槽位的状态"""

    cookers: dict[str, CookerState]
    """灶台名称 -> 状态的映射"""

    assembly: AssemblyState
    """组装站状态（gastronome 专用）"""

    stockpile: dict[str, StockpileSlot]
    """库存槽位名称 -> 状态的映射"""

    recipes: dict[str, Recipe]
    """当前局可用配方 slug -> Recipe 的映射"""

    game_duration: float
    """本局游戏总时长（秒）"""

    is_in_animation_window: bool
    """是否处于动画窗口期间"""

    total_visibility: float = 0.0
    """已完成订单的总 visibility（用于得分加成）"""

    mixing_bowl: MixingBowlState = field(default_factory=MixingBowlState)
    """搅拌盆状态（dessert 专用）"""

    @property
    def remaining_time(self) -> float:
        """剩余游戏时间"""
        return max(0.0, self.game_duration - self.time)