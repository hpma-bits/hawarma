"""
Playground Core Runner

游戏循环和基准测试运行器。

输入: GameEnv, Agent/Strategy, 配置
输出: EpisodeResult / BenchmarkResult
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from hawarma.agent.agent import Action
    from playground.agents.base import Agent
    from playground.env.game_env import GameEnv
    from playground.strategies.base import Strategy


@dataclass
class EpisodeResult:
    """单局游戏结果"""

    total_reward: float
    steps: int
    actions_taken: int
    orders_served: int
    orders_timeout: int
    final_time: float
    seed: int
    strategy_name: str
    history: list[tuple[float, object, Action | None]] = field(default_factory=list)
    """[(time, state, action), ...] 用于 replay"""


def run_episode(
    env: GameEnv,
    agent: Agent,
    seed: int,
    record_history: bool = False,
    max_steps: int = 2000,
) -> EpisodeResult:
    """
    运行单局游戏。

    Args:
        env: 游戏环境
        agent: Agent（包含 Strategy）
        seed: 随机种子
        record_history: 是否记录完整历史（用于 replay）
        max_steps: 最大步数（安全上限）

    Returns:
        EpisodeResult: 游戏结果
    """
    obs, info = env.reset(seed=seed)
    agent.reset()
    agent.strategy.on_game_start(info.get("recipes", {}))

    total_reward = 0.0
    steps = 0
    actions_taken = 0
    orders_served = 0
    orders_timeout = 0
    history = []

    while steps < max_steps:
        action = agent.act(obs)

        if record_history:
            history.append((obs.time, obs, action))

        result = env.step(action)
        agent.observe(result.observation, result.reward, result.terminated, result.info)

        total_reward += result.reward
        steps += 1

        if action is not None:
            actions_taken += 1

        # 统计订单事件
        for event in result.info.get("events", []):
            from hawarma.env_simulator_types import EventType
            if event.event_type == EventType.ORDER_SERVED:
                orders_served += 1
            elif event.event_type == EventType.ORDER_TIMEOUT:
                orders_timeout += 1

        if result.terminated or result.truncated:
            break

        obs = result.observation

    return EpisodeResult(
        total_reward=total_reward,
        steps=steps,
        actions_taken=actions_taken,
        orders_served=orders_served,
        orders_timeout=orders_timeout,
        final_time=obs.time if hasattr(obs, 'time') else 0.0,
        seed=seed,
        strategy_name=type(agent.strategy).__name__,
        history=history if record_history else [],
    )


def run_benchmark(
    env_factory: Callable[[], GameEnv],
    strategies: dict[str, Strategy],
    num_games: int = 50,
    seeds: list[int] | None = None,
) -> dict[str, list[EpisodeResult]]:
    """
    运行多策略基准测试。

    Args:
        env_factory: 创建 GameEnv 的工厂函数
        strategies: {策略名: Strategy 实例}
        num_games: 每策略测试局数
        seeds: 自定义种子列表，None 则使用 0..num_games-1

    Returns:
        {策略名: [EpisodeResult, ...]}
    """
    from playground.agents.base import Agent

    if seeds is None:
        seeds = list(range(num_games))

    results = {name: [] for name in strategies}

    for seed in seeds:
        for name, strategy in strategies.items():
            env = env_factory()
            agent = Agent(strategy)
            result = run_episode(env, agent, seed=seed)
            results[name].append(result)

    return results
