"""
端到端集成测试：GameEnvImpl + CookingAgent (with DefaultStrategy)

验证完整的 RL 循环：
- GameEnvImpl.reset() -> UnifiedState
- CookingAgent.step() -> Strategy.decide(state) -> Action
- GameEnvImpl.step(action) -> next_state, reward, done
"""

import pytest

from playground.env.game_env_impl import GameEnvImpl
from hawarma.agent.agent import CookingAgent, Action


@pytest.fixture
def env():
    return GameEnvImpl()


class TestEndToEnd:
    """端到端测试：Agent 在 GameEnv 中跑完整局游戏"""

    def test_agent_runs_full_game(self, env):
        """验证 CookingAgent + DefaultStrategy 能跑完一局游戏"""
        obs, info = env.reset(seed=42)

        # 创建 CookingAgent，使用默认的 DefaultStrategy
        # 需要用 SimulatorEnvironment 包装 GameSimulator（CookingAgent 期望 BaseEnvironment 接口）
        from hawarma.bridge.simulator_environment import SimulatorEnvironment
        from hawarma.agent.strategies.default import DefaultStrategy
        sim_env = SimulatorEnvironment(env._sim)
        recipes = list(info["recipes"].values())
        agent = CookingAgent(sim_env, recipes, strategy=DefaultStrategy())

        total_reward = 0.0
        steps = 0
        max_steps = 1000  # 安全上限
        actions_taken = 0

        while steps < max_steps:
            action = agent.step()
            result = env.step(action)

            total_reward += result.reward
            steps += 1

            if action is not None:
                actions_taken += 1

            if result.terminated or result.truncated:
                break

        # 验证游戏正常结束
        assert result.terminated is True
        assert steps > 100  # 至少跑了 10 秒 (100 * 0.1s)

        # 验证 Agent 的统计
        stats = agent.get_stats()
        assert stats["time"] >= 90.0
        assert actions_taken > 0  # Agent 至少做了一些动作

        print(f"\nGame completed: steps={steps}, actions={actions_taken}, "
              f"score={stats['total_score']}, served={stats['orders_served']}")

    def test_agent_with_explicit_strategy(self, env):
        """验证可以注入自定义 Strategy"""
        from hawarma.agent.strategies.default import DefaultStrategy
        from hawarma.bridge.simulator_environment import SimulatorEnvironment

        obs, info = env.reset(seed=42)
        recipes = list(info["recipes"].values())

        strategy = DefaultStrategy()
        strategy.on_game_start(info["recipes"])

        sim_env = SimulatorEnvironment(env._sim)
        agent = CookingAgent(sim_env, recipes, strategy=strategy)

        # 跑几步验证不报错
        for _ in range(50):
            action = agent.step()
            result = env.step(action)
            if result.terminated:
                break

        assert True  # 没有异常就是成功

    def test_strategy_decides_from_unified_state(self, env):
        """验证 Strategy 从 UnifiedState 决策，不直接访问 env"""
        from hawarma.agent.strategies.default import DefaultStrategy
        from playground.env.unified_state import UnifiedState

        obs, info = env.reset(seed=42)

        strategy = DefaultStrategy()
        strategy.on_game_start(info["recipes"])

        # 推进几步让订单出现
        for _ in range(50):
            env.step(None)

        state = env.get_unified_state()
        assert isinstance(state, UnifiedState)

        # Strategy 只接收 state，不接触 env
        action = strategy.decide(state)

        # 验证返回的是合法的 Action
        assert action is None or isinstance(action, Action)
