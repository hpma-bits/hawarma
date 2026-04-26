"""
Runner 和 Benchmark 集成测试
"""

import pytest

from playground.env.game_env_impl import GameEnvImpl
from playground.agents.base import Agent
from playground.strategies.default import DefaultStrategy
from playground.core.runner import run_episode, run_benchmark


class TestRunner:
    """测试 run_episode"""

    def test_run_episode_basic(self):
        env = GameEnvImpl()
        agent = Agent(DefaultStrategy())
        result = run_episode(env, agent, seed=42)

        assert result.seed == 42
        assert result.steps > 100
        assert result.strategy_name == "DefaultStrategy"

    def test_run_episode_records_history(self):
        env = GameEnvImpl()
        agent = Agent(DefaultStrategy())
        result = run_episode(env, agent, seed=42, record_history=True)

        assert len(result.history) > 0
        time, state, action = result.history[0]
        assert time >= 0.0

    def test_run_episode_different_seeds(self):
        env1 = GameEnvImpl()
        env2 = GameEnvImpl()
        agent = Agent(DefaultStrategy())

        r1 = run_episode(env1, agent, seed=1)
        r2 = run_episode(env2, agent, seed=2)

        # 不同 seed 应该有不同的 reward
        assert r1.total_reward != r2.total_reward


class TestBenchmark:
    """测试 run_benchmark"""

    def test_benchmark_single_strategy(self):
        def env_factory():
            return GameEnvImpl()

        strategies = {"default": DefaultStrategy()}
        results = run_benchmark(env_factory, strategies, num_games=3)

        assert "default" in results
        assert len(results["default"]) == 3

        for r in results["default"]:
            assert r.total_reward > 0 or r.steps > 100

    def test_benchmark_paired_seeds(self):
        """验证同一 seed 下运行多策略（配对实验）"""
        def env_factory():
            return GameEnvImpl()

        # 两个相同策略，结果应该完全一致
        strategies = {
            "a": DefaultStrategy(),
            "b": DefaultStrategy(),
        }
        results = run_benchmark(env_factory, strategies, num_games=2)

        for r1, r2 in zip(results["a"], results["b"]):
            assert r1.total_reward == r2.total_reward
            assert r1.seed == r2.seed
