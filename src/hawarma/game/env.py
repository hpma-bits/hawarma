"""
游戏环境抽象基类

地位：定义 Agent 与环境交互的统一接口。
      拆分为 Env（共享）+ GastronomeEnv（美食）+ DessertEnv（甜点）。
      GameEnv 同时实现 GastronomeEnv 和 DessertEnv。

输入：无（纯接口定义）
输出：Env / GastronomeEnv / DessertEnv 抽象基类

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hawarma.core.state import UnifiedState

from hawarma.core.models import (
    AssemblyState,
    CookerState,
    MixingBowlState,
    Order,
    StockpileSlot,
)


class Env(ABC):
    """
    游戏环境共享接口

    定义所有 station 共用的方法。
    GameEnv 和 SimulatorEnvironment 都必须实现这些方法。
    """

    @property
    @abstractmethod
    def time(self) -> float:
        """当前游戏时间（秒）"""

    @property
    @abstractmethod
    def orders(self) -> list[Order | None]:
        """当前订单列表（4个槽位）"""

    @property
    @abstractmethod
    def cookers(self) -> dict[str, CookerState]:
        """灶台状态"""

    @abstractmethod
    def is_in_animation_window(self) -> bool:
        """是否在动画窗口期间"""

    @abstractmethod
    def start_cooking(self, ingredient: str, cooker: str, duration: float) -> bool:
        """开始烹饪"""

    @abstractmethod
    def clear_cooker(self, cooker: str) -> bool:
        """清理灶台（丢弃过期食材）"""

    @abstractmethod
    def get_unified_state(self) -> UnifiedState:
        """构建当前状态的 UnifiedState 快照"""

    @abstractmethod
    def get_stats(self) -> dict:
        """获取游戏统计信息"""

    @abstractmethod
    def on_order_served(self, score: int = 1) -> None:
        """订单送餐成功时调用，更新统计"""

    @abstractmethod
    def on_order_timeout(self, order_id: int) -> None:
        """订单超时时调用，更新统计"""

    @abstractmethod
    def on_action_taken(self) -> None:
        """执行动作时调用，更新动作计数"""


class GastronomeEnv(Env):
    """Gastronome 专用接口"""

    @property
    @abstractmethod
    def assembly(self) -> AssemblyState:
        """组装站状态"""

    @property
    @abstractmethod
    def stockpile(self) -> dict[str, StockpileSlot]:
        """库存状态"""

    @abstractmethod
    def move_to_assembly(self, cooker: str) -> bool:
        """将灶台完成的食材移动到组装站"""

    @abstractmethod
    def move_to_stockpile(self, cooker: str, slot: str) -> bool:
        """将灶台完成的食材移动到库存"""

    @abstractmethod
    def pull_from_stockpile(self, slot: str) -> bool:
        """从库存取用食材到组装站"""

    @abstractmethod
    def add_condiment(self, condiment: str) -> bool:
        """添加调料到组装站"""

    @abstractmethod
    def serve_order(self, slot_idx: int) -> bool:
        """送餐"""

    @abstractmethod
    def clear_assembly(self) -> bool:
        """清空组装站"""


class DessertEnv(Env):
    """Dessert 专用接口"""

    @property
    @abstractmethod
    def mixing_bowl(self) -> MixingBowlState:
        """搅拌盆状态"""

    @abstractmethod
    def add_to_mixing_bowl(self, ingredient: str, recipe_slug: str | None = None) -> bool:
        """食材 → 搅拌盆"""

    @abstractmethod
    def add_condiment_to_mixing_bowl(self, condiment: str) -> bool:
        """调料 → 搅拌盆"""

    @abstractmethod
    def stir_mixing_bowl(self) -> bool:
        """搅拌操作"""

    @abstractmethod
    def move_mixing_bowl_to_cooker(self, cooker: str) -> bool:
        """搅拌盆 → 灶台"""

    @abstractmethod
    def serve_from_cooker(self, cooker: str, slot_idx: int) -> bool:
        """灶台 → 取餐台"""

    @abstractmethod
    def clear_mixing_bowl(self) -> bool:
        """清空搅拌盆"""
