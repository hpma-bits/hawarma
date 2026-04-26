"""
Playground CLI

统一入口：python -m playground ...

命令：
    run     运行单局游戏
    bench   运行基准测试
    replay  回放游戏记录
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


def cmd_run(args):
    """运行单局游戏"""
    from playground.env.game_env_impl import GameEnvImpl
    from playground.agents.base import Agent
    from playground.strategies.default import DefaultStrategy
    from playground.core.runner import run_episode
    from playground.replay.recorder import save_replay

    env = GameEnvImpl()
    strategy = DefaultStrategy()
    agent = Agent(strategy)

    result = run_episode(
        env,
        agent,
        seed=args.seed,
        record_history=args.record,
    )

    print(f"\nGame completed!")
    print(f"  Seed: {result.seed}")
    print(f"  Strategy: {result.strategy_name}")
    print(f"  Total Reward: {result.total_reward:.0f}")
    print(f"  Steps: {result.steps}")
    print(f"  Actions: {result.actions_taken}")

    if args.record and result.history:
        save_replay(result, args.output)
        print(f"  Replay saved to {args.output}")


def cmd_bench(args):
    """运行基准测试"""
    from playground.env.game_env_impl import GameEnvImpl
    from playground.strategies.default import DefaultStrategy
    from playground.strategies.cooking_first_v2 import CookingFirstV2Strategy
    from playground.strategies.stockpile_first import StockpileFirstStrategy
    from playground.bench.runner import run_benchmark
    from playground.bench.compare import print_comparison, export_csv, export_json

    strategies = {
        "default": DefaultStrategy(),
        "cooking_first_v2": CookingFirstV2Strategy(),
        "stockpile_first": StockpileFirstStrategy(),
    }

    if args.strategies:
        names = [s.strip() for s in args.strategies.split(",")]
        strategies = {k: v for k, v in strategies.items() if k in names}

    def env_factory():
        return GameEnvImpl()

    results = run_benchmark(
        env_factory,
        strategies,
        num_games=args.games,
    )

    print_comparison(results)

    if args.csv:
        export_csv(results, args.csv)
    if args.json:
        export_json(results, args.json)


def cmd_replay(args):
    """回放游戏记录"""
    from playground.replay.recorder import replay_cli
    replay_cli(args.file)


def main():
    parser = argparse.ArgumentParser(
        prog="playground",
        description="Hawarma Playground - RL-style game simulation and strategy benchmark",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run
    run_parser = subparsers.add_parser("run", help="Run a single game")
    run_parser.add_argument("--seed", type=int, default=42, help="Random seed")
    run_parser.add_argument("--record", action="store_true", help="Record replay")
    run_parser.add_argument("--output", type=str, default="playground_replay.json", help="Replay output file")
    run_parser.set_defaults(func=cmd_run)

    # bench
    bench_parser = subparsers.add_parser("bench", help="Run benchmark")
    bench_parser.add_argument("--games", type=int, default=50, help="Number of games per strategy")
    bench_parser.add_argument("--strategies", type=str, default=None, help="Comma-separated strategy names")
    bench_parser.add_argument("--csv", type=str, default=None, help="Export to CSV")
    bench_parser.add_argument("--json", type=str, default=None, help="Export to JSON")
    bench_parser.set_defaults(func=cmd_bench)

    # replay
    replay_parser = subparsers.add_parser("replay", help="Replay a recorded game")
    replay_parser.add_argument("file", type=str, help="Replay JSON file")
    replay_parser.set_defaults(func=cmd_replay)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()