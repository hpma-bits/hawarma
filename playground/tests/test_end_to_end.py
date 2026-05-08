"""
端到端集成测试：SimEnv + Strategy

验证完整的决策循环：
- SimEnv.reset() -> UnifiedState
- strategy.decide(state) -> Action
- SimEnv.step(action) -> next_state, reward, done
"""

import pytest

from playground.env.sim import SimEnv
from hawarma.core.actions import Action


@pytest.fixture
def env():
    return SimEnv()


class TestEndToEnd:
    """端到端测试：Strategy 在 GameEnv 中跑完整局游戏"""

    def test_agent_runs_full_game(self, env):
        """验证 DefaultStrategy 能跑完一局游戏"""
        from hawarma.agent.strategies.default import DefaultStrategy

        obs, info = env.reset(seed=42)
        strategy = DefaultStrategy()
        strategy.on_game_start(info["recipes"])

        total_reward = 0.0
        steps = 0
        max_steps = 1000
        actions_taken = 0

        while steps < max_steps:
            state = env.get_unified_state()
            action = strategy.decide(state)
            result = env.step(action)

            total_reward += result.reward
            steps += 1

            if action is not None:
                actions_taken += 1

            if result.terminated or result.truncated:
                break

        assert result.terminated is True
        assert steps > 100
        assert actions_taken > 0

        stats = env.get_stats()
        print(f"\nGame completed: steps={steps}, actions={actions_taken}, "
              f"score={stats['total_score']}, served={stats['orders_served']}")

    def test_agent_with_explicit_strategy(self, env):
        """验证可以注入自定义 Strategy"""
        from hawarma.agent.strategies.default import DefaultStrategy

        obs, info = env.reset(seed=42)
        strategy = DefaultStrategy()
        strategy.on_game_start(info["recipes"])

        for _ in range(50):
            state = env.get_unified_state()
            action = strategy.decide(state)
            result = env.step(action)
            if result.terminated:
                break

        assert True

    def test_strategy_decides_from_unified_state(self, env):
        """验证 Strategy 从 UnifiedState 决策，不直接访问 env"""
        from hawarma.agent.strategies.default import DefaultStrategy
        from hawarma.core.state import UnifiedState

        obs, info = env.reset(seed=42)
        strategy = DefaultStrategy()
        strategy.on_game_start(info["recipes"])

        for _ in range(50):
            env.step(None)

        state = env.get_unified_state()
        assert isinstance(state, UnifiedState)

        action = strategy.decide(state)
        assert action is None or isinstance(action, Action)
