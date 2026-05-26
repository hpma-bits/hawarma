"""
游戏环境模拟器 - 核心数据结构和类型定义

地位：定义游戏环境模拟器中使用的所有数据结构和事件类型。
      状态类型（Order, CookerState 等）从 hawarma.core.models 导入。
      Recipe 和 IngredientRequirement 从 hawarma.recipe 导入（已统一）。

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

# ============================================================================
# 从 core/models 导入统一状态类型
# ============================================================================

from hawarma.core.models import (
    Order,
    CookerState,
    AssemblyState,
    StockpileSlot,
    MixingBowlState,
)

# ============================================================================
# 从 hawarma.recipe 导入统一配方类型
# ============================================================================

from hawarma.recipe import Recipe, IngredientRequirement

# ============================================================================
# 事件类型（模拟器专用）
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
# 游戏状态
# ============================================================================

@dataclass
class GameState:
    """
    游戏状态

    代表游戏某一时刻的完整状态快照
    使用 core.models 中的统一状态类型
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

    # 配方（从 hawarma.recipe 统一导入）
    'Recipe',
    'IngredientRequirement',

    # 统一状态类型（从 core.models 导入）
    'Order',
    'CookerState',
    'AssemblyState',
    'StockpileSlot',
    'MixingBowlState',

    # 游戏状态
    'GameState',
    'GameConfig',
]
