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
        """
        获取指定槽位的订单
        
        注意：如果订单还在动画期间（1秒），返回None
        动画期间订单已存在但agent还无法"看到"
        """
        if 0 <= slot_idx < self.MAX_SLOTS:
            order = self._state.orders[slot_idx]
            # 检查订单是否在动画期间（创建后1秒内）
            if order is not None and self._state.time < order.created_at + 1.0:
                return None
            return order
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
    
    # ============================================================================
    # 核心操作方法
    # ============================================================================
    
    def start_cooking(self, ingredient: str, cooker: str) -> ActionResult:
        """
        在指定灶台开始烹饪食材
        
        Args:
            ingredient: 食材名称
            cooker: 灶台名称
            
        Returns:
            ActionResult: 操作结果
        """
        # 检查灶台是否存在
        if cooker not in self._state.cookers:
            return ActionResult.failure_result(f"Cooker '{cooker}' does not exist")
        
        cooker_state = self._state.cookers[cooker]
        
        # 检查灶台是否繁忙
        if cooker_state.busy:
            return ActionResult.failure_result(f"Cooker '{cooker}' is busy")
        
        # 查找配方中的烹饪时间
        duration = None
        for recipe in self._recipes.values():
            for ing in recipe.ingredients:
                if ing.name == ingredient and ing.cooker_type == cooker:
                    duration = ing.duration
                    break
            if duration is not None:
                break
        
        # 如果没有找到配方，使用默认时间（或拒绝）
        if duration is None:
            return ActionResult.failure_result(
                f"No recipe found for ingredient '{ingredient}' on cooker '{cooker}'"
            )
        
        # 设置灶台状态
        cooker_state.busy = True
        cooker_state.ingredient_name = ingredient
        cooker_state.cooker_type = cooker
        cooker_state.started_at = self._state.time
        cooker_state.done_at = self._state.time + duration
        cooker_state.expired_at = cooker_state.done_at + self.COOKER_RETENTION
        
        # 创建事件
        event = Event(
            timestamp=self._state.time,
            event_type=EventType.COOKING_STARTED,
            details={
                'ingredient': ingredient,
                'cooker': cooker,
                'duration': duration,
                'done_at': cooker_state.done_at
            }
        )
        
        self._event_history.append(event)
        
        if self._debug:
            print(f"Started cooking {ingredient} on {cooker} (done at {cooker_state.done_at:.1f}s)")
        
        return ActionResult.success_result([event])
    
    def move_to_assembly(self, cooker: str) -> ActionResult:
        """
        将烹饪完成的食材从灶台移动到组装站
        
        Args:
            cooker: 灶台名称
            
        Returns:
            ActionResult: 操作结果
        """
        # 检查灶台是否存在
        if cooker not in self._state.cookers:
            return ActionResult.failure_result(f"Cooker '{cooker}' does not exist")
        
        cooker_state = self._state.cookers[cooker]
        
        # 检查灶台是否有食材
        if not cooker_state.busy or cooker_state.ingredient_name is None:
            return ActionResult.failure_result(f"Cooker '{cooker}' has no ingredient")
        
        # 检查烹饪是否完成
        if cooker_state.done_at is None or self._state.time < cooker_state.done_at:
            return ActionResult.failure_result(
                f"Ingredient on '{cooker}' is not cooked yet"
            )
        
        # 检查食材是否过期
        if cooker_state.expired_at and self._state.time >= cooker_state.expired_at:
            return ActionResult.failure_result(
                f"Ingredient on '{cooker}' has expired, must clear to trash"
            )
        
        # 获取食材信息
        ingredient_name = cooker_state.ingredient_name
        cooker_type = cooker_state.cooker_type
        
        # 检查组装站兼容性
        if not self._state.assembly.can_add_ingredient(ingredient_name, cooker_type):
            return ActionResult.failure_result(
                f"Ingredient {ingredient_name} is not compatible with current assembly"
            )
        
        # 移动到组装站
        self._state.assembly.ingredients.append((ingredient_name, cooker_type, self._state.time))
        
        # 设置目标配方（如果是第一个食材）
        if self._state.assembly.target_recipe is None:
            # 查找匹配的配方
            for recipe in self._recipes.values():
                for ing in recipe.ingredients:
                    if ing.name == ingredient_name and ing.cooker_type == cooker_type:
                        self._state.assembly.target_recipe = recipe
                        break
                if self._state.assembly.target_recipe:
                    break
        
        # 清空灶台
        cooker_state.clear()
        
        # 检查组装是否完成
        if self._state.assembly.is_complete:
            complete_event = Event(
                timestamp=self._state.time,
                event_type=EventType.ASSEMBLY_COMPLETED,
                details={
                    'recipe': self._state.assembly.target_recipe.name if self._state.assembly.target_recipe else None,
                    'ingredients': [ing[0] for ing in self._state.assembly.ingredients]
                }
            )
            self._event_history.append(complete_event)
            if self._debug:
                print(f"Assembly completed for recipe: {self._state.assembly.target_recipe.name if self._state.assembly.target_recipe else 'Unknown'}")
        
        # 创建事件
        event = Event(
            timestamp=self._state.time,
            event_type=EventType.INGREDIENT_ADDED_TO_ASSEMBLY,
            details={
                'ingredient': ingredient_name,
                'cooker': cooker,
                'assembly_ingredients': [ing[0] for ing in self._state.assembly.ingredients]
            }
        )
        
        self._event_history.append(event)
        
        if self._debug:
            print(f"Moved {ingredient_name} from {cooker} to assembly")
        
        return ActionResult.success_result([event])
    
    def serve_order(self, slot_idx: int) -> ActionResult:
        """
        提交订单（将组装好的菜品送到取餐台）
        
        Args:
            slot_idx: 订单槽位索引
            
        Returns:
            ActionResult: 操作结果
        """
        # 检查槽位索引
        if slot_idx < 0 or slot_idx >= self.MAX_SLOTS:
            return ActionResult.failure_result(f"Invalid slot index: {slot_idx}")
        
        # 检查槽位是否有订单
        order = self._state.orders[slot_idx]
        if order is None:
            return ActionResult.failure_result(f"No order at slot {slot_idx}")
        
        # 检查组装站是否有完成的菜品
        if not self._state.assembly.is_complete:
            return ActionResult.failure_result("Assembly is not complete")
        
        # 检查组装站的配方是否匹配订单的配方
        if self._state.assembly.target_recipe != order.recipe:
            return ActionResult.failure_result(
                f"Assembly recipe does not match order recipe"
            )
        
        # 检查调料是否满足要求（简化版：检查数量）
        # TODO: 更复杂的调料匹配逻辑
        
        # 标记订单完成
        order.served_at = self._state.time
        order.done = True
        
        # 计算得分（简化版）
        base_score = 100
        time_penalty = max(0, (order.timeout_at - order.created_at) - 
                          (order.served_at - order.created_at))
        # TODO: 更复杂的计分逻辑
        
        score = base_score
        
        # 清空组装站
        self._state.assembly.clear()
        
        # 清除订单槽位
        self._state.orders[slot_idx] = None
        
        # 触发槽位前移
        self._advance_slots(self._state.time)
        
        # 创建事件
        event = Event(
            timestamp=self._state.time,
            event_type=EventType.ORDER_SERVED,
            details={
                'order_id': order.order_id,
                'slot': slot_idx,
                'recipe': order.recipe.name,
                'score': score,
                'served_at': order.served_at
            }
        )
        
        self._event_history.append(event)
        
        if self._debug:
            print(f"Order {order.order_id} served from slot {slot_idx}, score: {score}")
        
        return ActionResult.success_result([event], score=score)
    
    def _advance_slots(self, current_time: float) -> None:
        """触发槽位前移"""
        # 移除None值（已完成或超时的订单）
        new_orders = [o for o in self._state.orders if o is not None]
        # 填充None到右侧
        while len(new_orders) < self.MAX_SLOTS:
            new_orders.append(None)
        
        self._state.orders = new_orders
        
        # 设置动画窗口（1.5秒）
        self._animation_until = current_time + self.ANIMATION_DURATION
        
        # 创建槽位前移事件
        event = Event(
            timestamp=current_time,
            event_type=EventType.SLOTS_ADVANCED,
            details={
                'animation_until': self._animation_until
            }
        )
        
        self._event_history.append(event)
        
        if self._debug:
            print(f"Slots advanced, animation until {self._animation_until}")
    
    # 其余操作将在后续实现...
    # start_cooking, move_to_assembly, serve_order, tick, etc.


# ============================================================================
# 辅助函数
# ============================================================================
    # 时间管理和订单生成
    # ============================================================================
    
    def tick(self, dt: float) -> List[Event]:
        """
        推进游戏时间并触发自动事件
        
        处理的事件包括：
        - 订单超时
        - 烹饪完成
        - 食材过期
        - 订单生成（基于4秒间隔）
        
        Args:
            dt: 推进的时间（秒）
            
        Returns:
            本次tick触发的事件列表
        """
        # 如果游戏已结束，不再推进时间
        if self.is_game_over():
            return []
        
        events: List[Event] = []
        
        # 计算新时间，但不能超过游戏结束时间
        new_time = min(self._state.time + dt, self.GAME_DURATION)
        
        # 检查订单超时
        timeout_events = self._check_order_timeouts(new_time)
        events.extend(timeout_events)
        
        # 检查烹饪完成和食材过期
        cooking_events = self._check_cooking_progress(new_time)
        events.extend(cooking_events)
        
        # 生成新订单
        order_events = self._generate_orders(new_time)
        events.extend(order_events)
        
        # 更新时间
        self._state.time = new_time
        
        # 记录事件
        self._event_history.extend(events)
        
        return events
    
    def _check_order_timeouts(self, current_time: float) -> List[Event]:
        """检查并处理订单超时"""
        events = []
        
        for i, order in enumerate(self._state.orders):
            if order is None or order.is_completed:
                continue
            
            if current_time >= order.timeout_at:
                # 订单超时
                order.failed = True
                events.append(Event(
                    timestamp=current_time,
                    event_type=EventType.ORDER_TIMEOUT,
                    details={
                        'order_id': order.order_id,
                        'slot': i,
                        'recipe': order.recipe.name
                    }
                ))
                
                # 清除订单并触发槽位前移
                self._state.orders[i] = None
                self._advance_slots(current_time)
        
        return events
    
    def _check_cooking_progress(self, current_time: float) -> List[Event]:
        """检查烹饪完成和食材过期"""
        events = []
        
        for cooker_name, cooker in self._state.cookers.items():
            if not cooker.busy:
                continue
            
            # 检查烹饪完成
            if cooker.done_at and current_time >= cooker.done_at:
                if not any(e.event_type == EventType.COOKING_COMPLETED 
                          for e in self._event_history[-10:]):
                    events.append(Event(
                        timestamp=current_time,
                        event_type=EventType.COOKING_COMPLETED,
                        details={
                            'cooker': cooker_name,
                            'ingredient': cooker.ingredient_name
                        }
                    ))
            
            # 检查食材过期
            if cooker.expired_at and current_time >= cooker.expired_at:
                events.append(Event(
                    timestamp=current_time,
                    event_type=EventType.INGREDIENT_EXPIRED,
                    details={
                        'cooker': cooker_name,
                        'ingredient': cooker.ingredient_name
                    }
                ))
                
                # 清理过期食材
                cooker.clear()
        
        return events
    
    def _generate_orders(self, current_time: float) -> List[Event]:
        """生成新订单"""
        events = []
        
        # 检查是否需要立即刷新（提交后无订单）
        if self._should_immediate_refresh(current_time):
            event = self._create_new_order(current_time)
            if event:
                events.append(event)
            return events
        
        # 检查4秒间隔
        # 找到下一个应该生成订单的时间点
        next_order_time = ((int(current_time) // 4) + 1) * 4
        
        # 检查是否到达或超过了下一个订单时间点
        if current_time >= next_order_time:
            # 检查是否已经有足够的订单
            active_orders = sum(1 for o in self._state.orders if o is not None)
            if active_orders < self.MAX_SLOTS:
                event = self._create_new_order(current_time)
                if event:
                    events.append(event)
        
        return events
    
    def _should_immediate_refresh(self, current_time: float) -> bool:
        """检查是否需要立即刷新订单（提交后无订单）"""
        # 检查场上是否没有订单
        active_orders = sum(1 for o in self._state.orders if o is not None)
        if active_orders == 0:
            # 检查是否不在动画窗口期
            if current_time >= self._animation_until:
                return True
        return False
    
    def _create_new_order(self, current_time: float) -> Optional[Event]:
        """创建一个新订单"""
        # 查找空槽位
        empty_slot = None
        for i, order in enumerate(self._state.orders):
            if order is None:
                empty_slot = i
                break
        
        if empty_slot is None:
            return None
        
        # 获取配方（暂时使用第一个可用配方）
        if not self._recipes:
            return None
        
        recipe = list(self._recipes.values())[0]
        
        # 随机决定是否rush（25%概率）
        import random
        is_rush = random.random() < 0.25
        
        # 创建订单
        timeout = self.RUSH_TIMEOUT if is_rush else self.NORMAL_TIMEOUT
        order = Order(
            order_id=self._next_order_id,
            recipe=recipe,
            is_rush=is_rush,
            created_at=current_time,
            timeout_at=current_time + timeout,
            condiments_applied={}
        )
        
        self._next_order_id += 1
        
        # 放置订单
        self._state.orders[empty_slot] = order
        
        # 设置动画窗口（1秒）
        self._animation_until = current_time + 1.0
        
        # 创建事件
        event = Event(
            timestamp=current_time,
            event_type=EventType.ORDER_APPEARED,
            details={
                'order_id': order.order_id,
                'recipe': recipe.name,
                'slot': empty_slot,
                'rush': is_rush,
                'timeout_at': order.timeout_at,
                'animation_until': self._animation_until
            }
        )
        
        self._event_history.append(event)
        
        if self._debug:
            print(f"Order {order.order_id} appeared at slot {empty_slot} "
                  f"(rush={is_rush}, animation until {self._animation_until})")
        
        return event
    
    def _advance_slots(self, current_time: float) -> None:
        """触发槽位前移"""
        # 移除None值（已完成或超时的订单）
        new_orders = [o for o in self._state.orders if o is not None]
        # 填充None到右侧
        while len(new_orders) < self.MAX_SLOTS:
            new_orders.append(None)
        
        self._state.orders = new_orders
        
        # 设置动画窗口（1.5秒）
        self._animation_until = current_time + self.ANIMATION_DURATION
        
        # 创建槽位前移事件
        event = Event(
            timestamp=current_time,
            event_type=EventType.SLOTS_ADVANCED,
            details={
                'animation_until': self._animation_until
            }
        )
        
        self._event_history.append(event)
        
        if self._debug:
            print(f"Slots advanced, animation until {self._animation_until}")
    
    # 其余操作将在后续实现...
    # start_cooking, move_to_assembly, serve_order, etc.


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
