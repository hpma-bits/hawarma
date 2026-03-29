"""
Agent Scheduler - 高效调度器

地位：游戏的唯一决策中心，基于 Agent 策略优化决策。
      替换原有 Scheduler，提供更高的订单完成率。

输入：GameState 快照
输出：Action 列表供 Executor 执行

核心策略：
  1. 立即送餐（不等待）
  2. 全局并行（同时启动多个灶台）
  3. 预烹饪（空闲灶台补充库存）
  4. 跨订单共享（食材可被多个订单使用）

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

import asyncio
from collections import Counter
from typing import Optional

from loguru import logger

from hawarma.actions import (
    Action,
    CookIngredient,
    FinishOrder,
    PullFromStockpile,
)
from hawarma.models import OrderStage
from hawarma.state import GameState, SessionState


# ============================================================================
# 常量配置
# ============================================================================

# 高频食材配置（根据配方分析动态调整）
DEFAULT_STOCKPILE_CONFIG = [
    ("creamfield_rice", "pot", 2),
    ("clearwater_fish", "oven", 2),
    ("wild_mushroom", "skillet", 2),
]

# 预烹饪阈值：库存 <= 此值时预烹饪
PRECOOK_THRESHOLD = 2


# ============================================================================
# AgentScheduler
# ============================================================================

class AgentScheduler:
    """
    高效 Agent 调度器
    
    基于贪心策略，在每个 tick 选择最优动作组合。
    核心原则：最小化等待时间，最大化资源利用率。
    """
    
    def __init__(
        self,
        game_state: GameState,
        session_state: SessionState,
    ):
        self.game_state = game_state
        self.session_state = session_state
        
        # 动态高频食材配置
        self.stockpile_config = self._build_stockpile_config()
        
        # 统计信息
        self.stats = {
            "actions_generated": 0,
            "finish_actions": 0,
            "cook_actions": 0,
        }
    
    def _build_stockpile_config(self) -> list[tuple[str, str, int]]:
        """根据当前配方构建高频食材配置"""
        # 分析所有配方，找出高频食材
        ingredient_freq = Counter()
        ingredient_cooker = {}
        
        for recipe in self.session_state.ordered_recipes:
            for ing in recipe.raw_ingredients:
                ingredient_freq[ing] += 1
                # 从配方数据获取灶台类型
                for ing_req in recipe.ingredients:
                    if ing_req.name == ing:
                        ingredient_cooker[ing] = ing_req.cooker
        
        # 选择出现次数 >= 2 的食材
        config = []
        for ing, freq in ingredient_freq.most_common():
            if freq >= 2 and ing in ingredient_cooker:
                config.append((ing, ingredient_cooker[ing], PRECOOK_THRESHOLD))
                if len(config) >= 3:
                    break
        
        # 如果不够，使用默认配置补充
        if len(config) < 3:
            for default in DEFAULT_STOCKPILE_CONFIG:
                if default[0] not in [c[0] for c in config]:
                    config.append(default)
                if len(config) >= 3:
                    break
        
        return config
    
    def get_next_actions(self) -> list[Action]:
        """
        主入口。每个 tick 调用一次，返回待执行动作列表。
        
        调度优先级：
        1. 送餐（最高优先级，只执行一个）
        2. 调味（多次）
        3. 从灶台移到组装站（多次）
        4. 从库存取用（多次）
        5. 启动烹饪（尽可能多）
        """
        state = self.game_state
        now = asyncio.get_event_loop().time()
        actions: list[Action] = []
        
        # 1. 送餐（最高优先级）
        if action := self._try_finish_order(state, now):
            actions.append(action)
            self.stats["finish_actions"] += 1
            self.stats["actions_generated"] += 1
            return actions  # 送餐后等待动画
        
        # 2. 调味（多次）
        while action := self._try_season(state):
            actions.append(action)
        
        # 3. 从灶台移到组装站（多次）
        while action := self._try_move_to_assembly(state):
            actions.append(action)
        
        # 4. 从库存取用（多次）
        while action := self._try_pull_from_stockpile(state):
            actions.append(action)
        
        # 5. 启动烹饪（尽可能多）
        while action := self._try_start_cooking(state):
            actions.append(action)
            self.stats["cook_actions"] += 1
        
        self.stats["actions_generated"] += len(actions)
        return actions
    
    # ========================================================================
    # 送餐决策
    # ========================================================================
    
    def _try_finish_order(self, state: GameState, now: float) -> Optional[FinishOrder]:
        """尝试送餐"""
        # 检查动画窗口
        if not state.is_ui_stable(now):
            return None
        
        # 检查是否有正在完成的订单
        if state.reservations:
            return None
        
        # 检查组装站
        assembly = state.assembly
        if assembly.is_free():
            return None
        
        # 组装站有食材，找到匹配的订单
        owner_order_id = assembly.owner_order_id
        if owner_order_id is None:
            return None
        
        # 检查是否可以调味/送餐
        order = state.get_order_by_id(owner_order_id)
        if order is None or order.done:
            # 清理无效的组装站
            return None
        
        # 检查食材是否齐全
        if order.current_stage not in [OrderStage.READY_TO_SEASON, OrderStage.SEASONING]:
            return None
        
        # 找到订单所在的 slot
        slot_idx = state.get_order_slot(order.order_id)
        if slot_idx is None:
            return None
        
        # 预留完成操作
        reserved = state.reserve_finish(order.order_id)
        if not reserved:
            return None
        
        return FinishOrder(
            order_id=order.order_id,
            pickup_slot=slot_idx,
        )
    
    # ========================================================================
    # 调味决策
    # ========================================================================
    
    def _try_season(self, state: GameState) -> Optional[Action]:
        """尝试添加调料"""
        assembly = state.assembly
        if assembly.is_free():
            return None
        
        order = state.get_order_by_id(assembly.owner_order_id)
        if order is None:
            return None
        
        # 检查是否需要调味
        if order.current_stage not in [OrderStage.READY_TO_SEASON, OrderStage.SEASONING]:
            return None
        
        # 检查调料是否已完成
        if order.current_stage == OrderStage.SERVING:
            return None
        
        # TODO: 返回 AddCondiment 动作（如果需要）
        # 目前系统没有 AddCondiment action，调味在 FinishOrder 中处理
        return None
    
    # ========================================================================
    # 移动决策
    # ========================================================================
    
    def _try_move_to_assembly(self, state: GameState) -> Optional[Action]:
        """将完成的食材从灶台移到组装站"""
        for cooker_name, cooker in state.cookers.items():
            if not cooker.busy:
                continue
            
            # 检查是否完成烹饪
            if cooker.ready_at is None or asyncio.get_event_loop().time() < cooker.ready_at:
                continue
            
            # 检查是否已处理
            if cooker.cooked_waiting_assembly:
                continue
            
            # 检查目标
            if cooker.destination == "assembly":
                # 检查组装站是否可用
                if not state.is_assembly_free() and not state.is_assembly_owned_by(cooker.order_id):
                    # 组装站被占用，尝试 fallback 到库存
                    if action := self._fallback_to_stockpile(state, cooker_name, cooker):
                        return action
                    continue
                
                # 返回移动动作（通过 CookIngredient 的 _move_only 模式）
                return CookIngredient(
                    order_id=cooker.order_id,
                    ingredient_name=cooker.ingredient_name,
                    cooker_name=cooker_name,
                    destination="assembly",
                    _move_only=True,
                )
        
        return None
    
    def _fallback_to_stockpile(self, state: GameState, cooker_name: str, cooker) -> Optional[Action]:
        """当组装站被占用时，fallback 到库存"""
        # 找到合适的库存槽位
        for slot_idx, slot_name in enumerate(state.stockpile_counts.keys()):
            # 检查槽位是否兼容
            # TODO: 实现更精确的槽位检查
            return CookIngredient(
                order_id=cooker.order_id,
                ingredient_name=cooker.ingredient_name,
                cooker_name=cooker_name,
                destination="stockpile",
                stockpile_slot=slot_idx,
                _move_only=True,
            )
        return None
    
    # ========================================================================
    # 库存取用决策
    # ========================================================================
    
    def _try_pull_from_stockpile(self, state: GameState) -> Optional[PullFromStockpile]:
        """从库存取用食材到组装站"""
        # 检查组装站是否可用
        if not state.is_assembly_free():
            return None
        
        # 获取活跃订单
        active_orders = self._get_active_orders(state)
        if not active_orders:
            return None
        
        # 按优先级排序订单
        sorted_orders = self._sort_orders_by_priority(active_orders)
        
        for slot_idx, order in sorted_orders:
            # 获取需要的食材
            needed = self._get_needed_ingredients_for_order(state, order)
            
            for ing_name in needed:
                # 检查库存是否有
                stock_count = state.stockpile_counts.get(ing_name, 0)
                if stock_count > 0:
                    # 找到库存槽位
                    stockpile_slot = self._find_stockpile_slot(state, ing_name)
                    if stockpile_slot is not None:
                        return PullFromStockpile(
                            order_id=order.order_id,
                            ingredient_name=ing_name,
                            stockpile_slot=stockpile_slot,
                        )
        
        return None
    
    def _find_stockpile_slot(self, state: GameState, ingredient_name: str) -> Optional[int]:
        """找到存储指定食材的库存槽位"""
        # 简化实现：假设库存槽位索引与食材对应
        # 实际需要根据 session_state 的库存配置来确定
        for idx, (ing, _, _) in enumerate(self.stockpile_config):
            if ing == ingredient_name:
                return idx
        return None
    
    # ========================================================================
    # 烹饪决策
    # ========================================================================
    
    def _try_start_cooking(self, state: GameState) -> Optional[CookIngredient]:
        """为空闲灶台分配烹饪任务"""
        # 获取空闲灶台
        free_cookers = self._get_free_cookers(state)
        if not free_cookers:
            return None
        
        # 获取所有需要的食材（按优先级）
        all_needed = self._get_all_needed_ingredients(state)
        
        # 优先烹饪订单需要的食材
        for ing_name, cooker_type, order_id in all_needed:
            if cooker_type in free_cookers:
                # 检查是否已在烹饪
                if self._is_cooking(state, ing_name, cooker_type):
                    continue
                
                # 检查库存是否有（优先使用库存）
                if state.stockpile_counts.get(ing_name, 0) > 0:
                    continue
                
                return CookIngredient(
                    order_id=order_id,
                    ingredient_name=ing_name,
                    cooker_name=cooker_type,
                    destination="assembly",
                )
        
        # 空闲灶台预烹饪高频食材
        for cooker_type in free_cookers:
            if action := self._precook_for_stockpile(state, cooker_type):
                return action
        
        return None
    
    def _precook_for_stockpile(self, state: GameState, cooker_type: str) -> Optional[CookIngredient]:
        """为库存预烹饪高频食材"""
        for ing_name, cooker, threshold in self.stockpile_config:
            if cooker != cooker_type:
                continue
            
            # 检查库存是否需要补货
            count = state.stockpile_counts.get(ing_name, 0)
            if count < threshold:
                # 检查是否已在烹饪
                if self._is_cooking(state, ing_name, cooker_type):
                    continue
                
                return CookIngredient(
                    order_id=None,  # 无订单绑定
                    ingredient_name=ing_name,
                    cooker_name=cooker_type,
                    destination="stockpile",
                )
        
        return None
    
    # ========================================================================
    # 辅助方法
    # ========================================================================
    
    def _get_free_cookers(self, state: GameState) -> list[str]:
        """获取空闲灶台列表"""
        return [name for name, cooker in state.cookers.items() if not cooker.busy]
    
    def _get_active_orders(self, state: GameState) -> list[tuple[int, object]]:
        """获取活跃订单列表"""
        result = []
        for idx, order in enumerate(state.orders):
            if order is not None and not order.done:
                result.append((idx, order))
        return result
    
    def _sort_orders_by_priority(self, orders: list[tuple[int, object]]) -> list[tuple[int, object]]:
        """按优先级排序订单：Rush 优先"""
        rush = []
        normal = []
        for idx, order in orders:
            if order.is_rush:
                rush.append((idx, order))
            else:
                normal.append((idx, order))
        return rush + normal
    
    def _get_needed_ingredients_for_order(self, state: GameState, order) -> list[str]:
        """获取订单需要的食材"""
        # 获取已在组装站的食材
        at_assembly = Counter()
        if state.assembly.owner_order_id == order.order_id:
            at_assembly = Counter(state.assembly.ingredients)
        
        # 获取需要的食材
        required = Counter(order.recipe.raw_ingredients)
        needed = []
        for ing, count in required.items():
            if at_assembly[ing] < count:
                needed.append(ing)
        
        return needed
    
    def _get_all_needed_ingredients(self, state: GameState) -> list[tuple[str, str, int]]:
        """获取所有需要的食材（按优先级排序）"""
        result = []
        
        # 获取活跃订单
        active_orders = self._get_active_orders(state)
        sorted_orders = self._sort_orders_by_priority(active_orders)
        
        for slot_idx, order in sorted_orders:
            needed = self._get_needed_ingredients_for_order(state, order)
            for ing_name in needed:
                # 获取灶台类型
                cooker_type = self._get_cooker_for_ingredient(ing_name)
                if cooker_type:
                    result.append((ing_name, cooker_type, order.order_id))
        
        return result
    
    def _get_cooker_for_ingredient(self, ingredient_name: str) -> Optional[str]:
        """获取食材对应的灶台类型"""
        for recipe in self.session_state.ordered_recipes:
            for ing_req in recipe.ingredients:
                if ing_req.name == ingredient_name:
                    return ing_req.cooker
        return None
    
    def _is_cooking(self, state: GameState, ingredient_name: str, cooker_type: str) -> bool:
        """检查食材是否正在烹饪"""
        for cooker in state.cookers.values():
            if (cooker.busy and 
                cooker.ingredient_name == ingredient_name and 
                cooker.cooker_name == cooker_type):
                return True
        return False
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return self.stats
