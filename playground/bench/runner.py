"""
Playground Benchmark Runner

多策略基准测试运行器。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from playground.core.runner import EpisodeResult
    from playground.env.game_env import GameEnv
    from playground.strategies.base import Strategy


def run_benchmark(
    env_factory: Callable[[], GameEnv],
    strategies: dict[str, Strategy],
    num_games: int = 50,
    seeds: list[int] | None = None,
    recipe_slugs: list[str] | None = None,
) -> dict[str, list[EpisodeResult]]:
    """
    运行多策略基准测试。

    配对实验：同一 seed 下所有策略各跑一局，确保公平对比。

    Args:
        env_factory: 创建 GameEnv 的工厂函数
        strategies: {策略名: Strategy 实例}
        num_games: 每策略测试局数
        seeds: 自定义种子列表，None 则使用 0..num_games-1

    Returns:
        {策略名: [EpisodeResult, ...]}
    """
    from playground.agents.base import Agent
    from playground.core.runner import run_episode

    if seeds is None:
        seeds = list(range(num_games))

    results = {name: [] for name in strategies}

    print(f"Running benchmark: {len(strategies)} strategies × {len(seeds)} games")
    print("Strategies:", ", ".join(strategies.keys()))
    print("-" * 50)

    for i, seed in enumerate(seeds):
        for name, strategy in strategies.items():
            env = env_factory()
            agent = Agent(strategy)
            result = run_episode(env, agent, seed=seed, recipe_slugs=recipe_slugs, collect_metrics=True)
            results[name].append(result)

        if (i + 1) % 10 == 0 or i == len(seeds) - 1:
            print(f"  Completed {i + 1}/{len(seeds)} games...")

    return results
