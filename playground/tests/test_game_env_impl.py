"""
GameEnvImpl 集成测试

验证 GameEnvImpl 与 GameSimulator 的行为一致性。
需要启动真实 Simulator。

测试覆盖：
- reset() 初始化
- step(action) 执行动作 + 推进时间
- get_unified_state() 状态转换正确性
- 完整一局游戏
"""

import pytest

from playground.env.game_env_impl import GameEnvImpl
from playground.env.unified_state import UnifiedState
from hawarma.agent.agent import (
    CookAction,
    ServeOrderAction,
)
from hawarma.bridge.base_environment import OrderInfo


@pytest.fixture
def env() -> GameEnvImpl:
    """创建测试用的 GameEnvImpl"""
    return GameEnvImpl()


class TestReset:
    """测试 reset()"""

    def test_reset_returns_obs_and_info(self, env: GameEnvImpl):
        obs, info = env.reset(seed=42)

        assert isinstance(obs, UnifiedState)
        assert obs.time == 0.0
        assert obs.game_duration == 90.0
        assert len(obs.orders) == 4
        assert info["seed"] == 42
        assert len(info["recipes"]) == 4
        assert len(info["recipe_slugs"]) == 4

    def test_reset_creates_different_recipes_with_different_seeds(self, env: GameEnvImpl):
        _, info1 = env.reset(seed=1)
        _, info2 = env.reset(seed=2)
        assert info1["recipe_slugs"] != info2["recipe_slugs"]

    def test_reset_with_specific_recipes(self, env: GameEnvImpl):
        # 先 reset 一次加载 recipes
        env.reset(seed=42)
        # 然后用已知的 slugs
        slugs = list(env._recipe_adapters.keys())[:2]
        obs, info = env.reset(seed=42, recipe_slugs=slugs)
        assert info["recipe_slugs"] == slugs


class TestGetUnifiedState:
    """测试 get_unified_state() 状态转换"""

    def test_initial_state(self, env: GameEnvImpl):
        env.reset(seed=42)
        state = env.get_unified_state()

        assert state.time == 0.0
        assert len(state.cookers) >= 2
        assert "grill" in state.cookers or "oven" in state.cookers
        assert len(state.stockpile) == 3
        assert state.assembly.target_recipe_slug is None

    def test_orders_are_tuple(self, env: GameEnvImpl):
        env.reset(seed=42)
        state = env.get_unified_state()
        assert isinstance(state.orders, tuple)
        assert len(state.orders) == 4

    def test_recipe_adapters(self, env: GameEnvImpl):
        env.reset(seed=42)
        state = env.get_unified_state()
        assert len(state.recipes) == 4
        for slug, adapter in state.recipes.items():
            assert hasattr(adapter, "slug")
            assert hasattr(adapter, "raw_ingredients")
            assert hasattr(adapter, "cookers")


class TestStep:
    """测试 step()"""

    def test_step_none_advances_time(self, env: GameEnvImpl):
        env.reset(seed=42)
        result = env.step(None)

        assert result.observation.time == pytest.approx(0.1, abs=0.01)
        assert result.reward == 0.0
        assert result.terminated is False
        assert result.truncated is False
        assert "events" in result.info

    def test_step_cook_action(self, env: GameEnvImpl):
        env.reset(seed=42)
        state = env.get_unified_state()

        # 找一个可用的食材和灶台
        recipe = list(state.recipes.values())[0]
        ingredient = recipe.raw_ingredients[0]
        cooker = recipe.cookers[0]

        action = CookAction(ingredient=ingredient, cooker=cooker, duration=3.0)
        result = env.step(action)

        # 检查灶台是否忙碌
        next_state = result.observation
        assert next_state.cookers[cooker].busy is True
        assert next_state.cookers[cooker].ingredient_name == ingredient

    def test_step_invalid_action_fails_gracefully(self, env: GameEnvImpl):
        env.reset(seed=42)
        # 用一个不存在的食材
        action = CookAction(ingredient="nonexistent", cooker="grill", duration=3.0)
        result = env.step(action)

        assert result.info["action_success"] is False
        assert result.info["error_message"] is not None
        # 时间仍然推进
        assert result.observation.time == pytest.approx(0.1, abs=0.01)

    def test_multiple_steps(self, env: GameEnvImpl):
        env.reset(seed=42)
        for _ in range(10):
            result = env.step(None)
        assert result.observation.time == pytest.approx(1.0, abs=0.01)


class TestCookingFlow:
    """测试完整的烹饪流程"""

    def test_cook_and_move_to_assembly(self, env: GameEnvImpl):
        env.reset(seed=42)
        state = env.get_unified_state()

        recipe = list(state.recipes.values())[0]
        ingredient = recipe.raw_ingredients[0]
        cooker = recipe.cookers[0]
        duration = recipe.cook_durations[0]

        # 1. 开始烹饪
        env.step(CookAction(ingredient=ingredient, cooker=cooker, duration=duration))

        # 2. 推进时间到烹饪完成
        steps_needed = int(duration / env.TICK_INTERVAL) + 2
        for _ in range(steps_needed):
            result = env.step(None)
            if result.observation.cookers[cooker].done_at is not None:
                if result.observation.time >= result.observation.cookers[cooker].done_at:
                    break

        # 3. 移动到 assembly
        from hawarma.agent.agent import MoveToAssemblyAction
        env.step(MoveToAssemblyAction(cooker=cooker))

        final_state = env.get_unified_state()
        # assembly 应该有食材
        assert len(final_state.assembly.ingredients_cookers) > 0


class TestGameCompletion:
    """测试游戏结束"""

    def test_game_terminates(self, env: GameEnvImpl):
        # GameSimulator 要求 game_duration >= 90，使用 90 秒
        env.reset(seed=42, game_duration=90.0)

        # 推进时间直到游戏结束（大步长加速）
        terminated = False
        steps = 0
        max_steps = 950  # 90s / 0.1s + margin

        while not terminated and steps < max_steps:
            result = env.step(None)
            terminated = result.terminated
            steps += 1

        assert terminated is True
        assert env.is_game_over()

    def test_game_over_no_more_steps(self, env: GameEnvImpl):
        env.reset(seed=42, game_duration=90.0)

        # 推进到结束
        while not env.is_game_over():
            env.step(None)

        # 结束后 step 应该返回 terminated
        result = env.step(None)
        assert result.terminated is True


class TestReward:
    """测试奖励计算"""

    def test_no_reward_without_serve(self, env: GameEnvImpl):
        env.reset(seed=42)
        for _ in range(5):
            result = env.step(None)
            assert result.reward == 0.0


class TestConsistencyWithSimulator:
    """验证 GameEnvImpl 与底层 GameSimulator 状态一致"""

    def test_time_consistency(self, env: GameEnvImpl):
        env.reset(seed=42)
        sim = env._sim
        assert sim is not None

        for _ in range(10):
            env.step(None)
            assert env.get_unified_state().time == sim.time

    def test_order_consistency(self, env: GameEnvImpl):
        env.reset(seed=42)
        sim = env._sim
        assert sim is not None

        # 推进一段时间让订单出现
        for _ in range(50):
            env.step(None)

        unified = env.get_unified_state()
        for i in range(4):
            sim_order = sim._state.orders[i]
            uni_order = unified.orders[i]
            if sim_order is None:
                assert uni_order is None
            else:
                assert uni_order is not None
                assert uni_order.order_id == sim_order.order_id
                assert uni_order.recipe_slug == sim_order.recipe.slug
