"""
前瞻性烹饪策略测试

测试 CookingAgent 的前瞻性烹饪决策

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新
"""

import pytest
from hawarma.agent.agent import CookingAgent
from hawarma.bridge.simulator_environment import SimulatorEnvironment
from hawarma.env_simulator import GameSimulator


def create_test_agent():
    """创建测试用的 CookingAgent"""
    sim = GameSimulator()
    sim.load_recipes("data/recipes.json")
    recipe_slugs = sim.select_recipes(count=4, random_seed=42)
    sim.setup_from_recipes(recipe_slugs)
    
    env = SimulatorEnvironment(sim)
    recipe_objs = [sim.recipes[slug] for slug in recipe_slugs]
    
    return CookingAgent(env, recipe_objs), sim, env


class TestUrgentIngredients:
    """测试紧迫食材识别"""

    def test_get_urgent_ingredients_empty_orders(self):
        """无订单时应返回空列表"""
        agent, sim, env = create_test_agent()
        urgent = agent._get_urgent_ingredients()
        assert urgent == []

    def test_get_urgent_ingredients_with_orders(self):
        """有订单时应返回需要的食材"""
        agent, sim, env = create_test_agent()
        recipe = list(sim.recipes.values())[0]
        sim.inject_order(0, recipe, is_rush=False)
        
        urgent = agent._get_urgent_ingredients()
        assert len(urgent) > 0
        for item in urgent:
            assert len(item) == 3

    def test_time_until_needed(self):
        """测试食材紧迫时间计算"""
        agent, sim, env = create_test_agent()
        recipe = list(sim.recipes.values())[0]
        sim.inject_order(0, recipe, is_rush=False)
        
        time_needed = agent._get_time_until_needed('clearwater_fish')
        assert time_needed > 0


class TestProactiveCooking:
    """测试前瞻性烹饪策略"""

    def test_cook_when_cooker_free_and_order_urgent(self):
        """灶台空闲且订单紧迫时应主动烹饪"""
        agent, sim, env = create_test_agent()
        recipe = list(sim.recipes.values())[0]
        sim.inject_order(0, recipe, is_rush=False)
        
        free_cookers = agent._get_free_cookers()
        assert len(free_cookers) > 0
        
        action = agent._try_start_cooking()
        # 应该有烹饪动作（如果灶台可用）
        assert action is not None

    def test_prefers_urgent_over_non_urgent(self):
        """应该优先烹饪紧迫订单的食材"""
        agent, sim, env = create_test_agent()
        recipe = list(sim.recipes.values())[0]
        
        sim.inject_order(0, recipe, is_rush=False)
        sim.tick(40)
        sim.inject_order(1, recipe, is_rush=True)
        
        urgent = agent._get_urgent_ingredients()
        if len(urgent) > 1:
            assert urgent[0][2] <= urgent[1][2]


class TestCookerUtilization:
    """测试灶台利用率优化"""

    def test_no_idle_cookers_when_orders_pending(self):
        """有订单时应尽量不让灶台空闲"""
        agent, sim, env = create_test_agent()
        recipe = list(sim.recipes.values())[0]
        sim.inject_order(0, recipe, is_rush=False)
        sim.inject_order(1, recipe, is_rush=False)
        
        actions = []
        for _ in range(10):
            action = agent.step()
            if action:
                actions.append(type(action).__name__)
        
        cook_actions = [a for a in actions if 'Cook' in a]
        assert len(cook_actions) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])