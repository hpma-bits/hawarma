"""
延迟影响实验脚本

对比有无操作/检测延迟下各 gastronome 策略的表现。

用法:
    python -m experiments.latency_impact.script [num_games]
"""

import sys
from pathlib import Path

from hawarma.agent.registry import get_strategy
from playground.bench.compare import compute_stats, print_comparison, export_csv

GAMES = 30

STRATEGIES = [
    "default",
    "cpm",
    "cpm_enhanced",
    "visibility_aware",
    "preempt_score",
]

def run_benchmark(action_delay: float, detection_delay: float, num_games: int) -> dict:
    from playground.env.sim import SimEnv
    from playground.bench.bench import run_benchmark

    def env_factory():
        return SimEnv(
            action_delay=action_delay,
            detection_delay=detection_delay,
        )

    strategies = {}
    for name in STRATEGIES:
        strategies[name] = get_strategy(name)

    label = f"delay={action_delay}+{detection_delay}" if action_delay > 0 else "baseline"
    print(f"\n{'='*60}")
    print(f"  Benchmark: {label} (action_delay={action_delay}, detection_delay={detection_delay})")
    print(f"{'='*60}")

    return run_benchmark(env_factory, strategies, num_games=num_games)


def main():
    num_games = int(sys.argv[1]) if len(sys.argv) > 1 else GAMES
    print(f"Running {num_games} games per strategy × 2 configs = {num_games * len(STRATEGIES) * 2} episodes")

    baseline = run_benchmark(action_delay=0.0, detection_delay=0.0, num_games=num_games)
    with_delays = run_benchmark(action_delay=0.3, detection_delay=0.4, num_games=num_games)

    outdir = Path(__file__).parent

    print(f"\n{'#'*60}")
    print("#  BASELINE (action_delay=0, detection_delay=0)")
    print(f"{'#'*60}")
    print_comparison(baseline)
    export_csv(baseline, outdir / "baseline.csv")

    print(f"\n{'#'*60}")
    print("#  WITH DELAYS (action_delay=0.3, detection_delay=0.4)")
    print(f"{'#'*60}")
    print_comparison(with_delays)
    export_csv(with_delays, outdir / "with_delays.csv")

    print(f"\n{'#'*60}")
    print("#  PER-STRATEGY DELTA (with_delays - baseline)")
    print(f"{'#'*60}")
    print(f"{'Strategy':<22} {'Baseline':>10} {'WithDelay':>10} {'Delta':>10} {'Delta%':>8}")
    print("-" * 60)
    for name in STRATEGIES:
        base_rewards = [r.total_reward for r in baseline[name]]
        delay_rewards = [r.total_reward for r in with_delays[name]]
        base_avg = sum(base_rewards) / len(base_rewards)
        delay_avg = sum(delay_rewards) / len(delay_rewards)
        delta = delay_avg - base_avg
        delta_pct = (delta / base_avg * 100) if base_avg else 0
        print(f"{name:<22} {base_avg:>10.1f} {delay_avg:>10.1f} {delta:>+10.1f} {delta_pct:>+7.1f}%")

    print(f"\n{'#'*60}")
    print("#  EFFICIENCY METRICS COMPARISON")
    print(f"{'#'*60}")
    print(f"{'Strategy':<22} {'Config':<8} {'Idle%':>7} {'Expired':>8} {'ClrAsm':>7} {'SrvGap':>8} {'None%':>7} {'Actions':>8}")
    print("-" * 75)
    for name in STRATEGIES:
        for label, results, cfg in [
            ("baseline", baseline, "none"),
            ("delay", with_delays, "delay"),
        ]:
            stats = compute_stats(results[name])
            if stats.has_metrics:
                print(f"{name:<22} {cfg:<8} {stats.avg_idle_ratio*100:>6.1f}% {stats.avg_expired:>8.1f} {stats.avg_clear_asm:>7.1f} {stats.avg_serve_gap:>7.2f}s {stats.avg_none_ratio*100:>6.1f}% {stats.avg_actions:>8.1f}")
            else:
                print(f"{name:<22} {cfg:<8} {'N/A':>7} {'N/A':>8} {'N/A':>7} {'N/A':>8} {'N/A':>7} {stats.avg_actions:>8.1f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
