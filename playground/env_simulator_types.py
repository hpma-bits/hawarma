"""
游戏环境模拟器 - 核心数据结构和类型定义

地位：定义游戏环境模拟器中使用的所有数据类型和结构
输入：无（纯类型定义）
输出：可供其他模块使用的类型和类

真实游戏规则（2026-04-24 更新）：
- 订单刷新间隔：随机 3-5 秒，与 recipe 食材耗时无关
- 订单超时：与 recipe 食材耗时相关，普通 55-75s，rush 30-45s
- 游戏时长：90-110 秒（可配置）

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


# ============================================================================
# 事件类型
# ============================================================================

class EventType(Enum):
    """游戏事件类型枚举"""
    # 订单生命周期
    ORDER_APPEARED = auto()      # 新订单出现
    ORDER_TIMEOUT = auto()       # 订单超时
    ORDER_SERVED = auto()        # 订单完成上菜
    
    # 烹饪过程
    COOKING_STARTED = auto()     # 开始烹饪
    COOKING_COMPLETED = auto()   # 烹饪完成
    INGREDIENT_EXPIRED = auto()  # 食材过期
    
    # 组装站操作
    INGREDIENT_ADDED_TO_ASSEMBLY = auto()  # 食材加入组装站
    CONDIMENT_ADDED = auto()               # 添加调料
    ASSEMBLY_COMPLETED = auto()            # 组装完成
    
    # 移动操作
    INGREDIENT_MOVED_TO_STOCKPILE = auto() # 食材移入库存
    INGREDIENT_MOVED_TO_TRASH = auto()     # 食材丢弃
    
    # 槽位变化
    SLOTS_ADVANCED = auto()      # 订单槽位前移


@dataclass(frozen=True)
class Event:
    """
    游戏事件
    
    使用 frozen=True 确保事件是不可变的，便于追踪和重放
    """
    timestamp: float                    # 事件发生时间
    event_type: EventType               # 事件类型
    details: dict[str, Any] = field(default_factory=dict)  # 附加详情
    
    def __repr__(self) -> str:
        return f"Event({self.timestamp:.2f}s, {self.event_type.name})"


# ============================================================================
# 配方和食材
# ============================================================================

@dataclass(frozen=True)
class IngredientRequirement:
    """
    食材需求
    
    定义一个菜品所需的特定食材及其烹饪方式
    """
    name: str                           # 食材名称
    cooker_type: str                    # 所需厨具类型 (grill, oven, etc.)
    duration: float                     # 烹饪时长（秒）
    
    def __repr__(self) -> str:
        return f"{self.name}({self.cooker_type}, {self.duration}s)"


@dataclass(frozen=True)
class Recipe:
    """
    菜品配方
    
    定义一个完整的菜品，包含所需食材和调料
    """
    name: str                                           # 配方名称
    slug: str                                           # 配方唯一标识
    ingredients: tuple[IngredientRequirement, ...]       # 所需食材列表
    condiments: dict[str, int] = field(default_factory=dict)  # 调料需求 {名称: 数量}
    
    def __post_init__(self):
        """验证配方数据有效性"""
        if not self.ingredients:
            raise ValueError(f"Recipe {self.name} must have at least one ingredient")
        if len(self.ingredients) > 2:
            raise ValueError(f"Recipe {self.name} cannot have more than 2 ingredients")
    
    def __repr__(self) -> str:
        return f"Recipe({self.name}, {len(self.ingredients)} ingredients)"


# ============================================================================
# 游戏状态数据类
# ============================================================================

@dataclass
class Order:
    """
    订单
    
    代表一个客户订单，包含配方、时间限制等信息
    """
    order_id: int                       # 订单唯一ID
    recipe: Recipe                      # 所需配方
    is_rush: bool = False               # 是否为紧急订单
    created_at: float = 0.0             # 订单创建时间
    timeout_at: float = 0.0             # 订单超时时间
    served_at: float | None = None   # 订单完成时间
    condiments_applied: dict[str, int] = field(default_factory=dict)  # 已添加的调料
    spawned_at_visibility: float = 0.0  # 订单生成时的总 visibility（决定得分加成）
    
    @property
    def is_completed(self) -> bool:
        """订单是否已完成"""
        return self.served_at is not None
    
    def is_expired(self, current_time: float) -> bool:
        """订单是否已超时"""
        return current_time >= self.timeout_at and not self.is_completed
    
    def time_remaining(self, current_time: float) -> float:
        """订单剩余时间（秒）"""
        if self.is_completed:
            return 0.0
        return max(0.0, self.timeout_at - current_time)
    
    def __repr__(self) -> str:
        status = "COMPLETED" if self.is_completed else "PENDING"
        return f"Order({self.order_id}, {self.recipe.name}, {status})"


@dataclass
class CookerState:
    """
    灶台状态
    
    跟踪单个灶台的当前状态
    """
    busy: bool = False                  # 是否正在使用
    item_name: str | None = None          # 当前食材名称 / 甜点 recipe slug
    cooker_type: str | None = None       # 厨具类型（grill, oven等）
    started_at: float | None = None      # 烹饪开始时间
    done_at: float | None = None         # 烹饪完成时间
    expired_at: float | None = None      # 食材过期时间
    
    def is_done(self, current_time: float) -> bool:
        """检查烹饪是否已完成"""
        return self.done_at is not None and current_time >= self.done_at
    
    def is_expired(self, current_time: float) -> bool:
        """检查食材是否已过期"""
        return self.expired_at is not None and current_time >= self.expired_at
    
    def clear(self) -> None:
        """清空灶台状态"""
        self.busy = False
        self.item_name = None
        self.cooker_type = None
        self.started_at = None
        self.done_at = None
        self.expired_at = None
    
    def __repr__(self) -> str:
        if not self.busy:
            return "CookerState(IDLE)"
        return f"CookerState({self.item_name}, busy)"


@dataclass
class AssemblyState:
    """
    组装站状态
    
    跟踪组装站上的食材和调料
    """
    target_recipe: Recipe | None = None   # 当前正在组装的配方
    ingredients: list[tuple[str, str, float]] = field(default_factory=list)  # (食材名, 厨具, 添加时间)
    condiments: dict[str, int] = field(default_factory=dict)  # 已添加的调料 {名称: 数量}
    
    @property
    def is_complete(self) -> bool:
        """检查是否所有必需食材都已添加"""
        if not self.target_recipe:
            return False
        required = {ing.name for ing in self.target_recipe.ingredients}
        present = {ing[0] for ing in self.ingredients}
        return required == present
    
    def can_add_ingredient(self, ing_name: str, cooker: str) -> bool:
        """检查食材是否与当前组装兼容"""
        if not self.ingredients:
            return True  # 空组装站可以接受任何食材
        
        if not self.target_recipe:
            return False
        
        recipe_ing_names = {ing.name for ing in self.target_recipe.ingredients}
        present_ing_names = {ing[0] for ing in self.ingredients}
        
        return ing_name in recipe_ing_names and ing_name not in present_ing_names
    
    def clear(self) -> None:
        """清空组装站"""
        self.target_recipe = None
        self.ingredients = []
        self.condiments = {}
    
    def __repr__(self) -> str:
        if not self.ingredients:
            return "AssemblyState(EMPTY)"
        return f"AssemblyState({len(self.ingredients)} ingredients, {len(self.condiments)} condiments)"


@dataclass
class StockpileSlot:
    """
    库存槽位状态
    
    跟踪单个库存槽位中的食材
    """
    ingredient_name: str | None = None   # 食材名称
    cooker_type: str | None = None       # 烹饪使用的厨具
    count: int = 0                          # 当前数量 (max 5)
    
    def can_add(self, ing_name: str, cooker: str) -> bool:
        """检查是否可以添加食材到此槽位"""
        if self.count == 0:
            return True
        return self.ingredient_name == ing_name and self.cooker_type == cooker
    
    def add(self, ing_name: str, cooker: str) -> bool:
        """添加食材到槽位，返回是否成功"""
        if not self.can_add(ing_name, cooker) or self.count >= 5:
            return False
        self.ingredient_name = ing_name
        self.cooker_type = cooker
        self.count += 1
        return True
    
    def remove_one(self) -> bool:
        """从槽位取出一个食材"""
        if self.count <= 0:
            return False
        self.count -= 1
        if self.count == 0:
            self.ingredient_name = None
            self.cooker_type = None
        return True
    
    def clear(self) -> None:
        """清空槽位"""
        self.ingredient_name = None
        self.cooker_type = None
        self.count = 0
    
    def __repr__(self) -> str:
        if self.count == 0:
            return "StockpileSlot(EMPTY)"
        return f"StockpileSlot({self.ingredient_name} x{self.count})"


# ============================================================================
# 游戏状态和游戏模拟器（将在后续文件中实现）
# ============================================================================

@dataclass
class GameState:
    """
    游戏状态
    
    代表游戏某一时刻的完整状态快照
    使用 dataclass 便于创建不可变副本
    """
    orders: list[Order | None] = field(default_factory=lambda: [None] * 4)
    cookers: dict[str, CookerState] = field(default_factory=dict)
    assembly: AssemblyState = field(default_factory=AssemblyState)
    stockpile: dict[str, StockpileSlot] = field(default_factory=dict)
    time: float = 0.0
    total_visibility: float = 0.0
    
    def copy(self) -> GameState:
        """创建状态的深拷贝"""
        import copy
        return copy.deepcopy(self)
    
    def __repr__(self) -> str:
        order_count = sum(1 for o in self.orders if o is not None)
        return f"GameState(t={self.time:.1f}s, {order_count} orders, {len(self.cookers)} cookers)"


@dataclass
class GameConfig:
    """
    单局游戏配置
    
    记录当前游戏局的具体配置：选中的菜谱、可用的道具等
    """
    selected_recipes: list[str] = field(default_factory=list)
    available_cookers: list[str] = field(default_factory=list)
    available_ingredients: list[str] = field(default_factory=list)
    available_condiments: list[str] = field(default_factory=list)
    
    @property
    def is_configured(self) -> bool:
        """检查游戏是否已配置"""
        return len(self.selected_recipes) > 0


# 模块导出列表
__all__ = [
    # 事件
    'EventType',
    'Event',
    
    # 配方
    'IngredientRequirement',
    'Recipe',
    
    # 状态
    'Order',
    'CookerState',
    'AssemblyState',
    'StockpileSlot',
    'GameState',
    'GameConfig',
]
