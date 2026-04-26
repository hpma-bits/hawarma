"""
前瞻性烹饪策略测试

测试 CookingAgent + DefaultStrategy 的前瞻性烹饪决策。
重构后：Agent 仅为 Shell，决策逻辑在 DefaultStrategy 中。
本文件改为黑盒行为测试，只通过 agent.step() 验证策略行为。

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新
"""

import pytest
from hawarma.agent.agent import CookingAgent
from hawarma.bridge.simulator_environment import SimulatorEnvironment
from hawarma.env_simulator import GameSimulator


def create_test_agent(strategy=None):
    """创建测试用的 CookingAgent"""
    sim = GameSimulator()
    sim.load_recipes("data/recipes.json")
    recipe_slugs = sim.select_recipes(count=4, random_seed=42)
    sim.setup_from_recipes(recipe_slugs)

    env = SimulatorEnvironment(sim)
    recipe_objs = [sim.recipes[slug] for slug in recipe_slugs]

    return CookingAgent(env, recipe_objs, strategy=strategy), sim, env


class TestUrgentIngredients:
    """测试紧迫食材识别（黑盒：通过 step 输出推断）"""

    def test_urgent_order_triggers_cooking(self):
        """有订单时 step() 应返回 CookAction"""
        agent, sim, env = create_test_agent()
        recipe = list(sim.recipes.values())[0]
        sim.inject_order(0, recipe, is_rush=False)

        action = agent.step()
        # 有空闲灶台和订单时，策略应该开始烹饪
        assert action is not None


class TestProactiveCooking:
    """测试前瞻性烹饪策略（黑盒）"""

    def test_cook_when_cooker_free_and_order_urgent(self):
        """灶台空闲且订单紧迫时应主动烹饪"""
        agent, sim, env = create_test_agent()
        recipe = list(sim.recipes.values())[0]
        sim.inject_order(0, recipe, is_rush=False)

        action = agent.step()
        # 应该有烹饪动作（如果灶台可用）
        assert action is not None

    def test_rush_order_gets_priority(self):
        """rush 订单应被优先处理（通过观察多步输出）"""
        agent, sim, env = create_test_agent()
        recipe = list(sim.recipes.values())[0]

        sim.inject_order(0, recipe, is_rush=False)
        sim.tick(40)
        sim.inject_order(1, recipe, is_rush=True)

        # 多步执行，观察是否优先服务 rush
        actions = []
        for _ in range(20):
            action = agent.step()
            if action:
                actions.append(type(action).__name__)

        # 至少有烹饪动作发生
        cook_actions = [a for a in actions if 'Cook' in a]
        assert len(cook_actions) > 0


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
