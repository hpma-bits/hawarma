"""
游戏环境抽象基类

地位：定义 Agent 与环境交互的统一接口
      确保 GameEnvironment（真实游戏）和 SimulatorEnvironment（模拟测试）使用相同的数据结构
      避免因数据结构不一致导致的运行时错误

输入：无（纯接口定义）
输出：BaseEnvironment 抽象基类和统一数据结构

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


# ============================================================================
# 统一数据结构
# ============================================================================

@dataclass
class CookerState:
    """灶台状态"""
    busy: bool = False
    ingredient_name: Optional[str] = None
    cooker_type: Optional[str] = None
    started_at: Optional[float] = None
    done_at: Optional[float] = None

    def reset(self) -> None:
        """重置灶台状态"""
        self.busy = False
        self.ingredient_name = None
        self.cooker_type = None
        self.started_at = None
        self.done_at = None

    def is_done(self, current_time: float) -> bool:
        """检查烹饪是否已完成"""
        return self.done_at is not None and current_time >= self.done_at


@dataclass
class AssemblyState:
    """组装站状态"""
    ingredients: list[str] = field(default_factory=list)
    target_recipe_slug: Optional[str] = None
    owner_order_id: Optional[int] = None
    condiments: dict[str, int] = field(default_factory=dict)

    @property
    def is_free(self) -> bool:
        """组装站是否空闲"""
        return len(self.ingredients) == 0 and self.target_recipe_slug is None

    def reset(self) -> None:
        """重置组装站状态"""
        self.ingredients.clear()
        self.target_recipe_slug = None
        self.owner_order_id = None
        self.condiments.clear()


@dataclass
class StockpileSlot:
    """库存槽位"""
    ingredient_name: Optional[str] = None
    cooker_type: Optional[str] = None
    count: int = 0

    def can_add(self, ingredient: str, cooker: str) -> bool:
        """检查是否可以添加食材"""
        if self.ingredient_name is None:
            return True
        return self.ingredient_name == ingredient and self.cooker_type == cooker

    def add(self, ingredient: str, cooker: str) -> bool:
        """添加食材"""
        if not self.can_add(ingredient, cooker):
            return False
        if self.ingredient_name is None:
            self.ingredient_name = ingredient
            self.cooker_type = cooker
        self.count += 1
        return True

    def remove(self) -> bool:
        """移除一个食材"""
        if self.count <= 0:
            return False
        self.count -= 1
        if self.count == 0:
            self.ingredient_name = None
            self.cooker_type = None
        return True


@dataclass
class OrderInfo:
    """
    订单信息
    
    统一的订单数据结构，用于真实环境和模拟器
    """
    order_id: int
    recipe_slug: str
    is_rush: bool
    created_at: float
    timeout_at: float
    done: bool = False


# ============================================================================
# BaseEnvironment 抽象基类
# ============================================================================

class BaseEnvironment(ABC):
    """
    游戏环境抽象基类
    
    定义 Agent 与环境交互的最小接口。
    GameEnvironment 和 SimulatorEnvironment 都必须实现这些方法。
    """

    @property
    @abstractmethod
    def time(self) -> float:
        """当前游戏时间（秒）"""
        pass

    @property
    @abstractmethod
    def orders(self) -> list[Optional[OrderInfo]]:
        """
        当前订单列表（4个槽位）
        
        Returns:
            订单列表，每个元素为 None 或 OrderInfo 对象
        """
        pass

    @property
    @abstractmethod
    def cookers(self) -> dict[str, CookerState]:
        """
        灶台状态
        
        Returns:
            灶台名称 -> 状态的映射
        """
        pass

    @property
    @abstractmethod
    def assembly(self) -> AssemblyState:
        """组装站状态"""
        pass

    @property
    @abstractmethod
    def stockpile(self) -> dict[str, StockpileSlot]:
        """
        库存状态
        
        Returns:
            库存槽位名称 -> 状态的映射
        """
        pass

    @abstractmethod
    def is_in_animation_window(self) -> bool:
        """是否在动画窗口期间（禁止送餐操作）"""
        pass

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
        pass

    @abstractmethod
    def move_to_assembly(self, cooker: str) -> bool:
        """
        将灶台完成的食材移动到组装站
        
        Args:
            cooker: 灶台名称
            
        Returns:
            是否成功
        """
        pass

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
        pass

    @abstractmethod
    def pull_from_stockpile(self, slot: str) -> bool:
        """
        从库存取用食材到组装站
        
        Args:
            slot: 库存槽位名称
            
        Returns:
            是否成功
        """
        pass

    @abstractmethod
    def add_condiment(self, condiment: str) -> bool:
        """
        添加调料到组装站
        
        Args:
            condiment: 调料名称
            
        Returns:
            是否成功
        """
        pass

    @abstractmethod
    def serve_order(self, slot_idx: int) -> bool:
        """
        送餐
        
        Args:
            slot_idx: 订单槽位索引（0-3）
            
        Returns:
            是否成功
        """
        pass

    @abstractmethod
    def clear_cooker(self, cooker: str) -> bool:
        """
        清理灶台（丢弃过期食材）
        
        Args:
            cooker: 灶台名称
            
        Returns:
            是否成功
        """
        pass
