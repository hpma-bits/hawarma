"""
游戏环境抽象基类

地位：定义 Agent 与环境交互的统一接口
      确保 GameEnv（真实游戏）和 SimulatorEnvironment（模拟测试）使用相同的数据结构
      避免因数据结构不一致导致的运行时错误

输入：无（纯接口定义）
输出：Env 抽象基类和统一数据结构

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hawarma.core.state import UnifiedState

# ============================================================================
# 统一数据结构
# ============================================================================


# 统一数据结构（从 core/models 导入）
from hawarma.core.models import (
    AssemblyState,
    CookerState,
    OrderInfo,
    StockpileSlot,
)


class Env(ABC):
    """
    游戏环境抽象基类

    定义 Agent 与环境交互的最小接口。
    GameEnv 和 SimulatorEnvironment 都必须实现这些方法。
    """

    @property
    @abstractmethod
    def time(self) -> float:
        """当前游戏时间（秒）"""

    @property
    @abstractmethod
    def orders(self) -> list[OrderInfo | None]:
        """
        当前订单列表（4个槽位）

        Returns:
            订单列表，每个元素为 None 或 OrderInfo 对象
        """

    @property
    @abstractmethod
    def cookers(self) -> dict[str, CookerState]:
        """
        灶台状态

        Returns:
            灶台名称 -> 状态的映射
        """

    @property
    @abstractmethod
    def assembly(self) -> AssemblyState:
        """组装站状态"""

    @property
    @abstractmethod
    def stockpile(self) -> dict[str, StockpileSlot]:
        """
        库存状态

        Returns:
            库存槽位名称 -> 状态的映射
        """

    @abstractmethod
    def is_in_animation_window(self) -> bool:
        """是否在动画窗口期间（禁止送餐操作）"""

    @abstractmethod
    def start_cooking(self, ingredient: str, cooker: str, duration: float) -> bool:
        """
        开始烹饪

        Args:
            ingredient: 食材名称
            cooker: 灶台名称
            duration: 烹饪时长（秒）

        Returns:
            是否成功
        """

    @abstractmethod
    def move_to_assembly(self, cooker: str) -> bool:
        """
        将灶台完成的食材移动到组装站

        Args:
            cooker: 灶台名称

        Returns:
            是否成功
        """

    @abstractmethod
    def move_to_stockpile(self, cooker: str, slot: str) -> bool:
        """
        将灶台完成的食材移动到库存

        Args:
            cooker: 灶台名称
            slot: 库存槽位名称

        Returns:
            是否成功
        """

    @abstractmethod
    def pull_from_stockpile(self, slot: str) -> bool:
        """
        从库存取用食材到组装站

        Args:
            slot: 库存槽位名称

        Returns:
            是否成功
        """

    @abstractmethod
    def add_condiment(self, condiment: str) -> bool:
        """
        添加调料到组装站

        Args:
            condiment: 调料名称

        Returns:
            是否成功
        """

    @abstractmethod
    def serve_order(self, slot_idx: int) -> bool:
        """
        送餐

        Args:
            slot_idx: 订单槽位索引（0-3）

        Returns:
            是否成功
        """

    @abstractmethod
    def clear_cooker(self, cooker: str) -> bool:
        """
        清理灶台（丢弃过期食材）

        Args:
            cooker: 灶台名称

        Returns:
            是否成功
        """

    @abstractmethod
    def clear_assembly(self) -> bool:
        """
        清空组装站（丢弃食材）

        Returns:
            是否成功
        """

    # ========================================================================
    # 统一状态接口
    # ========================================================================

    @abstractmethod
    def get_unified_state(self) -> UnifiedState:
        """
        构建当前状态的 UnifiedState 快照

        Returns:
            UnifiedState: 不可变的状态快照
        """

    @abstractmethod
    def get_stats(self) -> dict:
        """
        获取游戏统计信息

        Returns:
            dict: {orders_served, total_score, orders_timeout, actions_taken}
        """

    @abstractmethod
    def on_order_served(self, score: int = 1) -> None:
        """
        订单送餐成功时调用，更新统计

        Args:
            score: 获得的分数
        """

    @abstractmethod
    def on_order_timeout(self, order_id: int) -> None:
        """
        订单超时时调用，更新统计

        Args:
            order_id: 超时的订单 ID
        """

    @abstractmethod
    def on_action_taken(self) -> None:
        """执行动作时调用，更新动作计数"""# 统一数据结构（从 core/models 导入）
from hawarma.core.models import (
    AssemblyState,
    CookerState,
    OrderInfo,
    StockpileSlot,
)


class Env(ABC):
    """
    游戏环境抽象基类

    定义 Agent 与环境交互的最小接口。
    GameEnv 和 SimulatorEnvironment 都必须实现这些方法。
    """

    @property
    @abstractmethod
    def time(self) -> float:
        """当前游戏时间（秒）"""

    @property
    @abstractmethod
    def orders(self) -> list[OrderInfo | None]:
        """
        当前订单列表（4个槽位）

        Returns:
            订单列表，每个元素为 None 或 OrderInfo 对象
        """

    @property
    @abstractmethod
    def cookers(self) -> dict[str, CookerState]:
        """
        灶台状态

        Returns:
            灶台名称 -> 状态的映射
        """

    @property
    @abstractmethod
    def assembly(self) -> AssemblyState:
        """组装站状态"""

    @property
    @abstractmethod
    def stockpile(self) -> dict[str, StockpileSlot]:
        """
        库存状态

        Returns:
            库存槽位名称 -> 状态的映射
        """

    @abstractmethod
    def is_in_animation_window(self) -> bool:
        """是否在动画窗口期间（禁止送餐操作）"""

    @abstractmethod
    def start_cooking(self, ingredient: str, cooker: str, duration: float) -> bool:
        """
        开始烹饪

        Args:
            ingredient: 食材名称
            cooker: 灶台名称
            duration: 烹饪时长（秒）

        Returns:
            是否成功
        """

    @abstractmethod
    def move_to_assembly(self, cooker: str) -> bool:
        """
        将灶台完成的食材移动到组装站

        Args:
            cooker: 灶台名称

        Returns:
            是否成功
        """

    @abstractmethod
    def move_to_stockpile(self, cooker: str, slot: str) -> bool:
        """
        将灶台完成的食材移动到库存

        Args:
            cooker: 灶台名称
            slot: 库存槽位名称

        Returns:
            是否成功
        """

    @abstractmethod
    def pull_from_stockpile(self, slot: str) -> bool:
        """
        从库存取用食材到组装站

        Args:
            slot: 库存槽位名称

        Returns:
            是否成功
        """

    @abstractmethod
    def add_condiment(self, condiment: str) -> bool:
        """
        添加调料到组装站

        Args:
            condiment: 调料名称

        Returns:
            是否成功
        """

    @abstractmethod
    def serve_order(self, slot_idx: int) -> bool:
        """
        送餐

        Args:
            slot_idx: 订单槽位索引（0-3）

        Returns:
            是否成功
        """

    @abstractmethod
    def clear_cooker(self, cooker: str) -> bool:
        """
        清理灶台（丢弃过期食材）

        Args:
            cooker: 灶台名称

        Returns:
            是否成功
        """

    @abstractmethod
    def clear_assembly(self) -> bool:
        """
        清空组装站（丢弃食材）

        Returns:
            是否成功
        """

    # ========================================================================
    # 统一状态接口
    # ========================================================================

    @abstractmethod
    def get_unified_state(self) -> UnifiedState:
        """
        构建当前状态的 UnifiedState 快照

        Returns:
            UnifiedState: 不可变的状态快照
        """

    @abstractmethod
    def get_stats(self) -> dict:
        """
        获取游戏统计信息

        Returns:
            dict: {orders_served, total_score, orders_timeout, actions_taken}
        """

    @abstractmethod
    def on_order_served(self, score: int = 1) -> None:
        """
        订单送餐成功时调用，更新统计

        Args:
            score: 获得的分数
        """

    @abstractmethod
    def on_order_timeout(self, order_id: int) -> None:
        """
        订单超时时调用，更新统计

        Args:
            order_id: 超时的订单 ID
        """

    @abstractmethod
    def on_action_taken(self) -> None:
        """执行动作时调用，更新动作计数"""
