"""
高效烹饪 Agent v2

地位：基于优先级的贪心策略，在 90 秒内最大化订单完成数
      优化版本：支持多动作执行、预烹饪、最大化并行

输入：GameSimulator 实例
输出：订单完成统计
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..env_simulator import GameSimulator, ActionResult
from ..env_simulator_types import Order, CookerState


# ============================================================================
# 常量配置
# ============================================================================

# 高频食材预存配置（动态调整）
DEFAULT_STOCKPILE = [
    ("creamfield_rice", "pot", 2.0),
    ("clearwater_fish", "oven", 3.0),
    ("wild_mushroom", "skillet", 2.0),
]

# 预烹饪阈值：当库存 <= 此值时预烹饪
PRECOOK_THRESHOLD = 2

# 紧急时间阈值
RUSH_CRITICAL_TIME = 20.0
NORMAL_CRITICAL_TIME = 30.0


# ============================================================================
# Agent 核心类
# ============================================================================

class CookingAgentV2:
    """
    高效烹饪 Agent v2
    
    改进：
    1. 每个 tick 执行多个动作（送餐、调味、移动、烹饪）
    2. 预烹饪策略：空闲灶台主动补货
    3. 最大化并行：同时使用所有空闲灶台
    """
    
    def __init__(self, simulator: GameSimulator):
        self.sim = simulator
        self.stats = {
            "orders_served": 0,
            "total_score": 0,
            "orders_timeout": 0,
            "actions_taken": 0,
        }
    
    def run(self, tick_interval: float = 0.1) -> dict:
        """
        运行完整游戏
        
        Args:
            tick_interval: 决策间隔（秒），建议 0.1s
            
        Returns:
            游戏统计
        """
        while not self.sim.is_game_over():
            self.step()
            self.sim.tick(tick_interval)
        
        return self.get_stats()
    
    def step(self) -> int:
        """
        单步决策：执行所有可能的动作
        
        Returns:
            执行的动作数量
        """
        actions_taken = 0
        
        # 1. 送餐（最高优先级，只能送一个）
        if self._try_serve():
            actions_taken += 1
        
        # 2. 调味（可以多次）
        while self._try_season():
            actions_taken += 1
        
        # 3. 从灶台移到组装站（可以多个）
        while self._try_move_to_assembly():
            actions_taken += 1
        
        # 4. 从库存取用到组装站
        while self._try_pull_from_stockpile():
            actions_taken += 1
        
        # 5. 开始烹饪（尽可能多地启动灶台）
        while self._try_start_cooking():
            actions_taken += 1
        
        # 6. 清理过期食材
        while self._try_clear_expired():
            actions_taken += 1
        
        # 7. 多余食材存入库存
        while self._try_store_to_stockpile():
            actions_taken += 1
        
        self.stats["actions_taken"] += actions_taken
        return actions_taken
    
    # ========================================================================
    # 动作尝试方法
    # ========================================================================
    
    def _try_serve(self) -> bool:
        """检查是否可以送餐"""
        assembly = self.sim.state.assembly
        
        if not assembly.is_complete:
            return False
        
        if self.sim.is_in_animation_window():
            return False
        
        # 找到匹配的订单
        for slot_idx, order in enumerate(self.sim.state.orders):
            if order is None:
                continue
            
            if order.recipe.slug == assembly.target_recipe.slug:
                result = self.sim.serve_order(slot_idx)
                if result.success:
                    self.stats["orders_served"] += 1
                    self.stats["total_score"] += result.score_earned
                    return True
        
        return False
    
    def _try_season(self) -> bool:
        """检查是否可以添加调料"""
        assembly = self.sim.state.assembly
        
        if not assembly.target_recipe:
            return False
        
        for condiment, required_count in assembly.target_recipe.condiments.items():
            current_count = assembly.condiments.get(condiment, 0)
            if current_count < required_count:
                result = self.sim.add_condiment(condiment)
                if result.success:
                    return True
        
        return False
    
    def _try_pull_from_stockpile(self) -> bool:
        """从库存取用食材到组装站"""
        needed = self._get_needed_ingredients()
        
        for ing_name, cooker_type in needed:
            # 检查组装站是否可以接受
            if not self._can_add_to_assembly(ing_name, cooker_type):
                continue
            
            # 检查库存是否有
            for slot_name, slot in self.sim.state.stockpile.items():
                if (slot.ingredient_name == ing_name and 
                    slot.cooker_type == cooker_type and 
                    slot.count > 0):
                    result = self.sim.pull_from_stockpile(slot_name)
                    if result.success:
                        return True
        
        return False
    
    def _try_move_to_assembly(self) -> bool:
        """将完成的食材从灶台移到组装站"""
        needed = self._get_needed_ingredients()
        
        for cooker_name, cooker in self.sim.state.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            
            if self.sim.time < cooker.done_at:
                continue
            
            # 检查是否过期
            if cooker.expired_at and self.sim.time >= cooker.expired_at:
                continue
            
            # 检查是否是需要的食材
            if (cooker.ingredient_name, cooker.cooker_type) not in needed:
                continue
            
            if self._can_add_to_assembly(cooker.ingredient_name, cooker.cooker_type):
                result = self.sim.move_to_assembly(cooker_name)
                if result.success:
                    return True
        
        return False
    
    def _try_start_cooking(self) -> bool:
        """为空闲灶台分配烹饪任务"""
        free_cookers = self._get_free_cookers()
        if not free_cookers:
            return False
        
        # 优先烹饪订单需要的食材
        to_cook = self._get_ingredients_to_cook()
        for ing_name, cooker_type in to_cook:
            if cooker_type in free_cookers:
                result = self.sim.start_cooking(ing_name, cooker_type)
                if result.success:
                    return True
        
        # 空闲灶台预烹饪高频食材
        for cooker_type in free_cookers:
            if self._try_precook(cooker_type):
                return True
        
        return False
    
    def _try_precook(self, cooker_type: str) -> bool:
        """预烹饪高频食材"""
        # 动态确定需要补货的食材
        for slot_name, slot in self.sim.state.stockpile.items():
            if slot.cooker_type == cooker_type and slot.count < PRECOOK_THRESHOLD:
                if slot.ingredient_name:
                    result = self.sim.start_cooking(slot.ingredient_name, cooker_type)
                    if result.success:
                        return True
        
        # 使用默认配置补货
        for ing_name, cooker, _ in DEFAULT_STOCKPILE:
            if cooker != cooker_type:
                continue
            
            slot = self._find_stockpile_slot(ing_name, cooker)
            if slot is None or slot.count < PRECOOK_THRESHOLD:
                result = self.sim.start_cooking(ing_name, cooker)
                if result.success:
                    return True
        
        return False
    
    def _try_clear_expired(self) -> bool:
        """清理过期食材"""
        for cooker_name, cooker in self.sim.state.cookers.items():
            if cooker.busy and cooker.expired_at and self.sim.time >= cooker.expired_at:
                result = self.sim.clear_cooker(cooker_name)
                if result.success:
                    return True
        return False
    
    def _try_store_to_stockpile(self) -> bool:
        """将灶台完成的食材存入库存"""
        # 只在组装站被占用时存储
        assembly = self.sim.state.assembly
        if not assembly.ingredients and not assembly.target_recipe:
            return False
        
        for cooker_name, cooker in self.sim.state.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            
            if self.sim.time < cooker.done_at:
                continue
            
            for slot_name, slot in self.sim.state.stockpile.items():
                if slot.can_add(cooker.ingredient_name, cooker.cooker_type) and slot.count < 5:
                    result = self.sim.move_to_stockpile(cooker_name, slot_name)
                    if result.success:
                        return True
        
        return False
    
    # ========================================================================
    # 辅助方法
    # ========================================================================
    
    def _get_needed_ingredients(self) -> list[tuple[str, str]]:
        """获取当前组装所需的食材"""
        assembly = self.sim.state.assembly
        
        # 如果组装站已有配方
        if assembly.target_recipe:
            present = {(ing[0], ing[1]) for ing in assembly.ingredients}
            return [
                (ing.name, ing.cooker_type) 
                for ing in assembly.target_recipe.ingredients 
                if (ing.name, ing.cooker_type) not in present
            ]
        
        # 组装站为空，返回第一个订单的第一个食材
        for order in self.sim.state.orders:
            if order:
                return [(ing.name, ing.cooker_type) for ing in order.recipe.ingredients]
        
        return []
    
    def _can_add_to_assembly(self, ing_name: str, cooker_type: str) -> bool:
        """检查食材是否可以添加到组装站"""
        assembly = self.sim.state.assembly
        
        if not assembly.ingredients and not assembly.target_recipe:
            return True
        
        if not assembly.target_recipe:
            return False
        
        recipe_ings = {(ing.name, ing.cooker_type) for ing in assembly.target_recipe.ingredients}
        if (ing_name, cooker_type) not in recipe_ings:
            return False
        
        present = {(ing[0], ing[1]) for ing in assembly.ingredients}
        return (ing_name, cooker_type) not in present
    
    def _get_ingredients_to_cook(self) -> list[tuple[str, str]]:
        """获取需要烹饪的食材列表"""
        needed = self._get_needed_ingredients()
        result = []
        
        for ing_name, cooker_type in needed:
            # 检查是否已在灶台
            if self._is_cooking(ing_name, cooker_type):
                continue
            
            # 检查库存是否有
            if self._has_in_stockpile(ing_name, cooker_type):
                continue
            
            result.append((ing_name, cooker_type))
        
        return result
    
    def _is_cooking(self, ing_name: str, cooker_type: str) -> bool:
        """检查食材是否正在烹饪"""
        for cooker in self.sim.state.cookers.values():
            if (cooker.busy and 
                cooker.ingredient_name == ing_name and 
                cooker.cooker_type == cooker_type):
                return True
        return False
    
    def _has_in_stockpile(self, ing_name: str, cooker_type: str) -> bool:
        """检查库存是否有该食材"""
        for slot in self.sim.state.stockpile.values():
            if (slot.ingredient_name == ing_name and 
                slot.cooker_type == cooker_type and 
                slot.count > 0):
                return True
        return False
    
    def _find_stockpile_slot(self, ing_name: str, cooker_type: str):
        """找到存储指定食材的库存槽"""
        for slot in self.sim.state.stockpile.values():
            if slot.ingredient_name == ing_name and slot.cooker_type == cooker_type:
                return slot
        return None
    
    def _get_free_cookers(self) -> list[str]:
        """获取空闲灶台列表"""
        return [name for name, cooker in self.sim.state.cookers.items() if not cooker.busy]
    
    def get_stats(self) -> dict:
        """获取游戏统计"""
        return {
            "time": self.sim.time,
            "orders_served": self.stats["orders_served"],
            "total_score": self.stats["total_score"],
            "orders_timeout": self.stats["orders_timeout"],
            "actions_taken": self.stats["actions_taken"],
            "events_count": len(self.sim.events),
        }
