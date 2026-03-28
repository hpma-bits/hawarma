"""
高效烹饪 Agent

地位：基于优先级的贪心策略，在 90 秒内最大化订单完成数

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

# 高频食材（根据配方分析）
HIGH_PRIORITY_STOCKPILE = [
    ("creamfield_rice", "pot", 2.0),
    ("clearwater_fish", "oven", 3.0),
    ("vining_marjoram", "grill", 4.0),
]

# 库存补货阈值
STOCKPILE_REFILL_THRESHOLD = 1

# 紧急时间阈值
RUSH_CRITICAL_TIME = 15.0
NORMAL_CRITICAL_TIME = 25.0


# ============================================================================
# Agent 核心类
# ============================================================================

class CookingAgent:
    """
    高效烹饪 Agent
    
    使用贪心策略，在每个决策点选择最优动作。
    核心原则：最小化等待时间，最大化资源利用率。
    """
    
    def __init__(self, simulator: GameSimulator):
        self.sim = simulator
        self.stats = {
            "orders_served": 0,
            "total_score": 0,
            "orders_timeout": 0,
        }
    
    def run(self, tick_interval: float = 0.5) -> dict:
        """
        运行完整游戏
        
        Args:
            tick_interval: 决策间隔（秒）
            
        Returns:
            游戏统计
        """
        while not self.sim.is_game_over():
            self.step()
            self.sim.tick(tick_interval)
        
        return self.get_stats()
    
    def step(self) -> Optional[ActionResult]:
        """
        单步决策：选择并执行最优动作
        
        Returns:
            执行结果，如果没有动作可执行则返回 None
        """
        # 1. 送餐（最高优先级）
        result = self._try_serve()
        if result:
            return result
        
        # 2. 调味
        result = self._try_season()
        if result:
            return result
        
        # 3. 从库存取用到组装站
        result = self._try_pull_from_stockpile()
        if result:
            return result
        
        # 4. 从灶台移到组装站
        result = self._try_move_to_assembly()
        if result:
            return result
        
        # 5. 开始烹饪
        result = self._try_start_cooking()
        if result:
            return result
        
        # 6. 清理过期食材
        result = self._try_clear_expired()
        if result:
            return result
        
        # 7. 灶台完成移到库存（如果组装站被占用）
        result = self._try_store_to_stockpile()
        if result:
            return result
        
        return None
    
    # ========================================================================
    # 动作尝试方法
    # ========================================================================
    
    def _try_serve(self) -> Optional[ActionResult]:
        """检查是否可以送餐"""
        assembly = self.sim.state.assembly
        
        # 组装站必须完成
        if not assembly.is_complete:
            return None
        
        # 找到匹配的订单
        for slot_idx, order in enumerate(self.sim.state.orders):
            if order is None:
                continue
            
            # 检查配方是否匹配
            if order.recipe.slug != assembly.target_recipe.slug:
                continue
            
            # 检查是否在动画窗口
            if self.sim.is_in_animation_window():
                continue
            
            # 尝试送餐
            result = self.sim.serve_order(slot_idx)
            if result.success:
                self.stats["orders_served"] += 1
                self.stats["total_score"] += result.score_earned
                return result
        
        return None
    
    def _try_season(self) -> Optional[ActionResult]:
        """检查是否可以添加调料"""
        assembly = self.sim.state.assembly
        
        if not assembly.target_recipe:
            return None
        
        # 检查是否需要添加调料
        for condiment, required_count in assembly.target_recipe.condiments.items():
            current_count = assembly.condiments.get(condiment, 0)
            if current_count < required_count:
                result = self.sim.add_condiment(condiment)
                if result.success:
                    return result
        
        return None
    
    def _try_pull_from_stockpile(self) -> Optional[ActionResult]:
        """从库存取用食材到组装站"""
        assembly = self.sim.state.assembly
        
        # 获取当前需要的食材
        needed = self._get_needed_ingredients()
        
        for ing_name, cooker_type in needed:
            # 检查库存是否有
            for slot_name, slot in self.sim.state.stockpile.items():
                if slot.ingredient_name == ing_name and slot.cooker_type == cooker_type and slot.count > 0:
                    # 检查组装站是否可以接受
                    if self._can_add_to_assembly(ing_name, cooker_type):
                        result = self.sim.pull_from_stockpile(slot_name)
                        if result.success:
                            return result
        
        return None
    
    def _try_move_to_assembly(self) -> Optional[ActionResult]:
        """将完成的食材从灶台移到组装站"""
        # 获取当前需要的食材
        needed = self._get_needed_ingredients()
        
        for cooker_name, cooker in self.sim.state.cookers.items():
            if not cooker.busy:
                continue
            
            # 检查是否完成烹饪
            if cooker.done_at is None or self.sim.time < cooker.done_at:
                continue
            
            # 检查是否过期
            if cooker.expired_at and self.sim.time >= cooker.expired_at:
                continue  # 等待清理
            
            # 检查是否是需要的食材
            if (cooker.ingredient_name, cooker.cooker_type) in needed:
                # 检查组装站是否可以接受
                if self._can_add_to_assembly(cooker.ingredient_name, cooker.cooker_type):
                    result = self.sim.move_to_assembly(cooker_name)
                    if result.success:
                        return result
        
        return None
    
    def _try_start_cooking(self) -> Optional[ActionResult]:
        """为空闲灶台分配烹饪任务"""
        free_cookers = self._get_free_cookers()
        if not free_cookers:
            return None
        
        # 获取需要烹饪的食材（按优先级）
        to_cook = self._get_ingredients_to_cook()
        
        for ing_name, cooker_type in to_cook:
            if cooker_type in free_cookers:
                result = self.sim.start_cooking(ing_name, cooker_type)
                if result.success:
                    free_cookers.remove(cooker_type)
                    return result
        
        # 空闲灶台补货高频食材
        return self._try_stockpile_refill(free_cookers)
    
    def _try_clear_expired(self) -> Optional[ActionResult]:
        """清理过期食材"""
        for cooker_name, cooker in self.sim.state.cookers.items():
            if cooker.busy and cooker.expired_at and self.sim.time >= cooker.expired_at:
                result = self.sim.clear_cooker(cooker_name)
                if result.success:
                    return result
        
        return None
    
    def _try_store_to_stockpile(self) -> Optional[ActionResult]:
        """将灶台完成的食材存入库存（当组装站被占用时）"""
        assembly = self.sim.state.assembly
        
        # 组装站未被占用时不存储
        if not assembly.ingredients and not assembly.target_recipe:
            return None
        
        for cooker_name, cooker in self.sim.state.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            
            if self.sim.time < cooker.done_at:
                continue
            
            # 尝试存入库存
            for slot_name, slot in self.sim.state.stockpile.items():
                if slot.can_add(cooker.ingredient_name, cooker.cooker_type) and slot.count < 5:
                    result = self.sim.move_to_stockpile(cooker_name, slot_name)
                    if result.success:
                        return result
        
        return None
    
    def _try_stockpile_refill(self, free_cookers: list[str]) -> Optional[ActionResult]:
        """空闲灶台补货高频食材"""
        for ing_name, cooker_type, _ in HIGH_PRIORITY_STOCKPILE:
            if cooker_type not in free_cookers:
                continue
            
            # 检查库存是否需要补货
            slot = self._find_stockpile_slot(ing_name, cooker_type)
            if slot is None or slot.count <= STOCKPILE_REFILL_THRESHOLD:
                result = self.sim.start_cooking(ing_name, cooker_type)
                if result.success:
                    return result
        
        return None
    
    # ========================================================================
    # 辅助方法
    # ========================================================================
    
    def _get_needed_ingredients(self) -> list[tuple[str, str]]:
        """获取当前组装所需的食材"""
        assembly = self.sim.state.assembly
        
        if not assembly.target_recipe:
            # 组装站为空，返回第一个订单需要的第一个食材
            for order in self.sim.state.orders:
                if order:
                    recipe = order.recipe
                    # 返回所有食材（因为可能还没有开始组装）
                    return [(ing.name, ing.cooker_type) for ing in recipe.ingredients]
            return []
        
        # 返回配方中尚未在组装站的食材
        needed = []
        present = {(ing[0], ing[1]) for ing in assembly.ingredients}
        
        for ing in assembly.target_recipe.ingredients:
            if (ing.name, ing.cooker_type) not in present:
                needed.append((ing.name, ing.cooker_type))
        
        return needed
    
    def _can_add_to_assembly(self, ing_name: str, cooker_type: str) -> bool:
        """检查食材是否可以添加到组装站"""
        assembly = self.sim.state.assembly
        
        # 组装站为空
        if not assembly.ingredients and not assembly.target_recipe:
            return True
        
        # 检查配方是否存在
        if not assembly.target_recipe:
            return False
        
        # 检查食材是否在配方中
        recipe_ings = {(ing.name, ing.cooker_type) for ing in assembly.target_recipe.ingredients}
        if (ing_name, cooker_type) not in recipe_ings:
            return False
        
        # 检查是否已有该食材
        present = {(ing[0], ing[1]) for ing in assembly.ingredients}
        return (ing_name, cooker_type) not in present
    
    def _get_ingredients_to_cook(self) -> list[tuple[str, str]]:
        """获取需要烹饪的食材列表（按优先级排序）"""
        needed = self._get_needed_ingredients()
        
        # 过滤掉已经在灶台烹饪或库存已有的
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
            if cooker.busy and cooker.ingredient_name == ing_name and cooker.cooker_type == cooker_type:
                return True
        return False
    
    def _has_in_stockpile(self, ing_name: str, cooker_type: str) -> bool:
        """检查库存是否有该食材"""
        for slot in self.sim.state.stockpile.values():
            if slot.ingredient_name == ing_name and slot.cooker_type == cooker_type and slot.count > 0:
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
            "events_count": len(self.sim.events),
        }
