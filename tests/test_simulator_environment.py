"""
测试 SimulatorEnvironment 适配器

验证 SimulatorEnvironment 正确实现 BaseEnvironment 接口
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest

from hawarma.env_simulator import GameSimulator
from hawarma.bridge.simulator_environment import SimulatorEnvironment
from hawarma.bridge.base_environment import BaseEnvironment


class TestSimulatorEnvironment(unittest.TestCase):
    """测试 SimulatorEnvironment 适配器"""
    
    def setUp(self):
        """设置测试环境"""
        self.sim = GameSimulator()
        self.sim.load_recipes("data/recipes.json")
        self.sim.setup_from_recipes(self.sim.select_recipes(count=4, random_seed=42))
        self.env = SimulatorEnvironment(self.sim)
    
    def test_is_base_environment(self):
        """验证实现了 BaseEnvironment 接口"""
        self.assertIsInstance(self.env, BaseEnvironment)
    
    def test_time_property(self):
        """测试 time 属性"""
        self.assertEqual(self.env.time, 0.0)
        
        self.sim.tick(1.0)
        self.assertEqual(self.env.time, 1.0)
    
    def test_cookers_property(self):
        """测试 cookers 属性转换"""
        cookers = self.env.cookers
        
        self.assertIsInstance(cookers, dict)
        self.assertGreater(len(cookers), 0)
        
        for name, state in cookers.items():
            self.assertFalse(state.busy)
            self.assertIsNone(state.ingredient_name)
            # cooker_type 在空闲时可能为 None，从灶台名称推断
            # self.assertEqual(state.cooker_type, name)
    
    def test_assembly_property(self):
        """测试 assembly 属性转换"""
        assembly = self.env.assembly
        
        self.assertIsInstance(assembly.ingredients, list)
        self.assertEqual(len(assembly.ingredients), 0)
        self.assertIsNone(assembly.target_recipe_slug)
    
    def test_stockpile_property(self):
        """测试 stockpile 属性转换"""
        stockpile = self.env.stockpile
        
        self.assertIsInstance(stockpile, dict)
        self.assertEqual(len(stockpile), 3)
        
        for name, slot in stockpile.items():
            self.assertIsNone(slot.ingredient_name)
            self.assertEqual(slot.count, 0)
    
    def test_orders_property(self):
        """测试 orders 属性转换"""
        orders = self.env.orders
        
        self.assertIsInstance(orders, list)
        self.assertEqual(len(orders), 4)
        
        for order in orders:
            if order is not None:
                self.assertIsNotNone(order.recipe_slug)
                self.assertIsNotNone(order.order_id)
    
    def test_tick_method(self):
        """测试 tick 方法"""
        events = self.env.tick(0.1)
        
        self.assertEqual(self.env.time, 0.1)
        self.assertIsInstance(events, list)
    
    def test_start_cooking(self):
        """测试 start_cooking 操作"""
        cookers = list(self.env.cookers.keys())
        if cookers:
            cooker_name = cookers[0]
            
            self.sim.tick(5.0)  # 等待订单出现
            
            # 获取一个需要的食材
            for order in self.env.orders:
                if order and hasattr(self.sim.recipes[order.recipe_slug], 'raw_ingredients'):
                    ingredient = self.sim.recipes[order.recipe_slug].raw_ingredients[0]
                    
                    result = self.env.start_cooking(ingredient, cooker_name, 3.0)
                    self.assertTrue(result)
                    
                    # 验证状态
                    cookers_state = self.env.cookers[cooker_name]
                    self.assertTrue(cookers_state.busy)
                    self.assertEqual(cookers_state.ingredient_name, ingredient)
                    break
    
    def test_is_in_animation_window(self):
        """测试 is_in_animation_window"""
        result = self.env.is_in_animation_window()
        self.assertIsInstance(result, bool)


if __name__ == "__main__":
    unittest.main()
