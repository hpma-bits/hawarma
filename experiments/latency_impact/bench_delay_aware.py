"""
延迟感知策略基准测试 (V1 + V2)

对比所有现有策略 vs DelayAwareCPMStrategy V1/V2 在延迟条件下的表现。

用法:
    python -m experiments.latency_impact.bench_delay_aware [num_games]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from hawarma.agent.registry import get_strategy
from playground.bench.compare import print_comparison, export_csv
from experiments.latency_impact.delay_aware_cpm import DelayAwareCPMStrategy
from experiments.latency_impact.delay_aware_cpm_v2 import DelayAwareCPMStrategyV2
from experiments.latency_impact.delay_aware_cpm_v3 import DelayAwareCPMStrategyV3

GAMES = 50

STRATEGIES = {
    "cpm": lambda: get_strategy("cpm"),
    "delay_aware_v2": lambda: DelayAwareCPMStrategyV2(),
    "delay_aware_v3": lambda: DelayAwareCPMStrategyV3(),
    "delay_aware_v1": lambda: DelayAwareCPMStrategy(),
}


def run_benchmark(action_delay: float, detection_delay: float, num_games: int) -> dict:
    from playground.env.sim import SimEnv
    from playground.bench.bench import run_benchmark

    def env_factory():
        return SimEnv(
            action_delay=action_delay,
            detection_delay=detection_delay,
        )

    strategies = {name: factory() for name, factory in STRATEGIES.items()}
    return run_benchmark(env_factory, strategies, num_games=num_games)


def main():
    num_games = int(sys.argv[1]) if len(sys.argv) > 1 else GAMES
    print(f"Running {num_games} games per strategy × 1 config = {num_games * len(STRATEGIES)} episodes")

    outdir = Path(__file__).parent

    results = run_benchmark(action_delay=0.3, detection_delay=0.4, num_games=num_games)

    print(f"\n{'#'*60}")
    print("#  WITH DELAYS (action_delay=0.3, detection_delay=0.4)")
    print(f"{'#'*60}")
    print_comparison(results)
    export_csv(results, outdir / "delay_aware_v2_bench.csv")

    print("\nDone.")


if __name__ == "__main__":
    main()
