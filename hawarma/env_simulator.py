"""
游戏环境模拟器 - 核心实现

地位：轻量级、确定性的状态机，模拟烹饪游戏
      作为游戏规则的"真理之源"

输入：游戏动作（烹饪、移动、调味等）、时间推进
输出：事件列表、状态更新、操作结果

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .env_simulator_types import (
    Event,
    EventType,
    Order,
    CookerState,
    AssemblyState,
    StockpileSlot,
    GameState,
    Recipe,
    IngredientRequirement,
)


# ============================================================================
# ActionResult 和异常
# ============================================================================

@dataclass(frozen=True)
class ActionResult:
    """
    动作执行结果
    
    使用 frozen=True 确保结果不可变，避免意外修改
    """
    success: bool
    events: Tuple[Event, ...] = field(default_factory=tuple)
    error_message: Optional[str] = None
    score_earned: int = 0  # 如果是 serve_order，记录得分
    
    def __bool__(self) -> bool:
        """允许使用 `if result:` 语法"""
        return self.success
    
    @property
    def is_success(self) -> bool:
        """显式检查是否成功"""
        return self.success
    
    def get_error(self) -> str:
        """获取错误信息，如果没有则返回默认值"""
        return self.error_message or "Unknown error"
    
    @classmethod
    def success_result(cls, events: List[Event] = None, score: int = 0) -> ActionResult:
        """快速创建成功结果"""
        return cls(
            success=True,
            events=tuple(events) if events else (),
            score_earned=score
        )
    
    @classmethod
    def failure_result(cls, error_message: str, events: List[Event] = None) -> ActionResult:
        """快速创建失败结果"""
        return cls(
            success=False,
            events=tuple(events) if events else (),
            error_message=error_message
        )


class SimulationError(Exception):
    """模拟器内部错误"""
    pass


class ValidationError(Exception):
    """验证错误（游戏规则违反）"""
    pass


# ============================================================================
# 游戏模拟器主类
# ============================================================================

class GameSimulator:
    """
    游戏环境模拟器
    
    轻量级、确定性的状态机，作为游戏规则的"真理之源"。
    
    核心特性：
    - 不可变状态：每个动作返回新的状态副本，便于调试和重放
    - 完整验证：所有操作都严格验证游戏规则
    - 事件驱动：所有状态变化都通过事件记录
    - 时间推进：通过 tick() 方法推进时间，触发自动事件
    
    使用示例：
        sim = GameSimulator()
        sim.load_recipes("data/recipes.json")
        sim.setup_cookers(['grill', 'oven', 'skillet', 'pot'])
        sim.setup_stockpile(['stk0', 'stk1', 'stk2'])
        
        # 注入订单
        sim.inject_order(0, recipe, is_rush=False)
        
        # 执行动作
        result = sim.start_cooking('beef', 'grill')
        if result.success:
            print(f"Cooking started! Events: {result.events}")
        
        # 推进时间
        events = sim.tick(5.0)  # 推进5秒
        for event in events:
            print(f"Event: {event}")
    """
    
    # 类常量
    MAX_SLOTS = 4
    MAX_STOCKPILE = 5
    COOKER_RETENTION = 5.0  # 灶台食材保留时间（秒）
    ANIMATION_DURATION = 1.5  # slot 位移动画时间（秒）
    RUSH_TIMEOUT = 40.0      # Rush 订单超时时间
    NORMAL_TIMEOUT = 70.0    # 普通订单超时时间
    MAX_CONDIMENTS = 3       # 每道菜最多调料数
    
    def __init__(self):
        """初始化模拟器"""
        # 当前游戏状态（使用深拷贝确保不可变性）
        self._state = GameState()
        
        # 配方数据
        self._recipes: Dict[str, Recipe] = {}
        
        # 事件历史（完整记录，用于调试和重放）
        self._event_history: List[Event] = []
        
        # 动画窗口结束时间
        self._animation_until: float = 0.0
        
        # 待处理订单（用于延迟生成）
        self._pending_orders: List[Tuple[Order, float]] = []  # (order, appear_at)
        
        # 订单ID计数器
        self._next_order_id: int = 1
        
        # 调试模式
        self._debug: bool = False
    
    # ------------------------------------------------------------------
    # 配置和初始化
    # ------------------------------------------------------------------
    
    def load_recipes(self, filepath: Union[str, Path]) -> None:
        """
        从 JSON 文件加载配方数据
        
        Args:
            filepath: 配方文件路径
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Recipe file not found: {filepath}")
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self._recipes = {}
        for recipe_data in data.get('recipes', []):
            # 解析食材需求
            ingredients = []
            for ing_data in recipe_data['ingredients']:
                ing = IngredientRequirement(
                    name=ing_data['name'],
                    cooker_type=ing_data['cooker'],
                    duration=ing_data['duration']
                )
                ingredients.append(ing)
            
            # 创建配方对象
            recipe = Recipe(
                name=recipe_data['name'],
                slug=recipe_data['slug'],
                ingredients=tuple(ingredients),
                condiments=recipe_data.get('condiments', {})
            )
            
            self._recipes[recipe.slug] = recipe
        
        if self._debug:
            print(f"Loaded {len(self._recipes)} recipes")
    
    def setup_cookers(self, names: List[str]) -> None:
        """
        初始化灶台
        
        Args:
            names: 灶台名称列表（如 ['grill', 'oven', 'skillet', 'pot']）
        """
        self._state.cookers = {name: CookerState() for name in names}
        
        if self._debug:
            print(f"Setup {len(names)} cookers: {names}")
    
    def setup_stockpile(self, slots: List[str]) -> None:
        """
        初始化库存区
        
        Args:
            slots: 库存槽位名称列表（如 ['stk0', 'stk1', 'stk2']）
        """
        self._state.stockpile = {slot_name: StockpileSlot() for slot_name in slots}
        
        if self._debug:
            print(f"Setup {len(slots)} stockpile slots: {slots}")
    
    def enable_debug(self, enabled: bool = True) -> None:
        """启用或禁用调试模式"""
        self._debug = enabled
    
    # ------------------------------------------------------------------
    # 属性和查询
    # ------------------------------------------------------------------
    
    @property
    def state(self) -> GameState:
        """获取当前游戏状态（只读）"""
        return copy.deepcopy(self._state)
    
    @property
    def time(self) -> float:
        """获取当前模拟时间"""
        return self._state.time
    
    @property
    def recipes(self) -> Dict[str, Recipe]:
        """获取所有配方"""
        return dict(self._recipes)  # 返回副本
    
    @property
    def events(self) -> List[Event]:
        """获取当前步骤的事件列表"""
        return list(self._event_history)
    
    def is_in_animation_window(self) -> bool:
        """检查是否在动画窗口期"""
        return self._state.time < self._animation_until
    
    def get_order(self, slot_idx: int) -> Optional[Order]:
        """获取指定槽位的订单"""
        if 0 <= slot_idx < self.MAX_SLOTS:
            return self._state.orders[slot_idx]
        return None
    
    def get_cooker_state(self, cooker_name: str) -> Optional[CookerState]:
        """获取指定灶台的状态"""
        return self._state.cookers.get(cooker_name)
    
    def get_stockpile_slot(self, slot_name: str) -> Optional[StockpileSlot]:
        """获取指定库存槽位的状态"""
        return self._state.stockpile.get(slot_name)
    
    # ------------------------------------------------------------------
    # 订单管理
    # ------------------------------------------------------------------
    
    def inject_order(
        self,
        slot_idx: int,
        recipe: Recipe,
        is_rush: bool = False,
        condiments: Optional[Dict[str, int]] = None
    ) -> ActionResult:
        """
        将订单注入指定槽位
        
        Args:
            slot_idx: 槽位索引 (0-3)
            recipe: 配方
            is_rush: 是否为紧急订单
            condiments: 自定义调料需求（可选）
            
        Returns:
            ActionResult: 操作结果
        """
        # 验证槽位索引
        if slot_idx < 0 or slot_idx >= self.MAX_SLOTS:
            return ActionResult.failure_result(
                f"Invalid slot index: {slot_idx}. Must be 0-{self.MAX_SLOTS-1}"
            )
        
        # 检查槽位是否被占用
        if self._state.orders[slot_idx] is not None:
            return ActionResult.failure_result(
                f"Slot {slot_idx} is already occupied"
            )
        
        # 创建订单
        timeout = self.RUSH_TIMEOUT if is_rush else self.NORMAL_TIMEOUT
        order = Order(
            order_id=self._next_order_id,
            recipe=recipe,
            is_rush=is_rush,
            created_at=self._state.time,
            timeout_at=self._state.time + timeout,
            condiments_applied=condiments if condiments else {}
        )
        
        self._next_order_id += 1
        
        # 放置订单
        self._state.orders[slot_idx] = order
        
        # 创建事件
        event = Event(
            timestamp=self._state.time,
            event_type=EventType.ORDER_APPEARED,
            details={
                'order_id': order.order_id,
                'recipe': recipe.name,
                'slot': slot_idx,
                'rush': is_rush,
                'timeout_at': order.timeout_at
            }
        )
        
        self._event_history.append(event)
        
        if self._debug:
            print(f"Order {order.order_id} injected to slot {slot_idx}")
        
        return ActionResult.success_result([event])
    
    # 其余操作将在后续实现...
    # start_cooking, move_to_assembly, serve_order, tick, etc.


# ============================================================================
# 辅助函数
# ============================================================================

def load_recipes_from_file(filepath: Union[str, Path]) -> Dict[str, Recipe]:
    """
    从文件加载配方数据
    
    这是一个独立的辅助函数，不依赖于 GameSimulator 实例
    
    Args:
        filepath: 配方文件路径
        
    Returns:
        Dict[str, Recipe]: 配方字典 {slug: Recipe}
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Recipe file not found: {filepath}")
    
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    recipes = {}
    for recipe_data in data.get('recipes', []):
        # 解析食材需求
        ingredients = []
        for ing_data in recipe_data['ingredients']:
            ing = IngredientRequirement(
                name=ing_data['name'],
                cooker_type=ing_data['cooker'],
                duration=ing_data['duration']
            )
            ingredients.append(ing)
        
        # 创建配方对象
        recipe = Recipe(
            name=recipe_data['name'],
            slug=recipe_data['slug'],
            ingredients=tuple(ingredients),
            condiments=recipe_data.get('condiments', {})
        )
        
        recipes[recipe.slug] = recipe
    
    return recipes


# 模块导出
__all__ = [
    'GameSimulator',
    'ActionResult',
    'SimulationError',
    'ValidationError',
    'load_recipes_from_file',
]
