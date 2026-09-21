"""
Playground Benchmark Comparison

策略统计对比，输出带显著性检验的结果。

输入: {strategy_name: [EpisodeResult, ...]}
输出: 打印表格 / 导出 CSV/JSON

口径（Issue #15）：表格与配对检验统一使用 ``final_score``
（v2 = 逐单 reward 之和 + 终局 visibility），与 CSV 导出的
``final_score`` 列一致；配对检验为 df = n-1 的双侧 t 检验，
输出真实 p 值、配对 Cohen's d 与 Δ 均值 95% CI（见 bench/stats.py）。

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, stdev
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playground.core.episode import EpisodeResult

from hawarma.core.scoring import LEGACY_SCORING_VERSION
from playground.bench.stats import PairedStats, paired_comparison


def _result_version(r: EpisodeResult) -> str:
    """口径版本回退（旧数据无该字段时视为 v1）."""
    return getattr(r, "scoring_version", LEGACY_SCORING_VERSION)

def _result_final(r: EpisodeResult) -> float:
    return getattr(r, "final_score", r.total_reward)

def _result_visibility(r: EpisodeResult) -> float:
    return getattr(r, "total_visibility", 0.0)


@dataclass
class StrategyStats:
    """单策略统计结果"""
    name: str
    games: int
    avg_reward: float
    std_reward: float
    avg_steps: float
    avg_actions: float
    max_reward: float
    min_reward: float
    scoring_version: str = LEGACY_SCORING_VERSION
    """计分口径版本（新旧基准隔离展示）"""
    # 统一口径（final_score，与 CSV 导出一致）
    avg_score: float = 0.0
    """final_score 均值（v2 口径：reward + 终局 visibility）"""
    std_score: float = 0.0
    max_score: float = 0.0
    min_score: float = 0.0
    # 效率指标（有 metrics 的游戏才统计）
    avg_idle_ratio: float = 0.0
    avg_expired: float = 0.0
    avg_clear_asm: float = 0.0
    avg_serve_gap: float = 0.0
    avg_none_ratio: float = 0.0
    avg_stockpile_in: float = 0.0
    avg_stockpile_out: float = 0.0
    avg_stockpile_max: float = 0.0
    has_metrics: bool = False


def compute_stats(results: list[EpisodeResult]) -> StrategyStats:
    """计算单策略统计指标（表格/检验统一用 final_score 口径，与 CSV 一致）"""
    rewards = [r.total_reward for r in results]
    scores = [_result_final(r) for r in results]
    steps = [r.steps for r in results]
    actions = [r.actions_taken for r in results]
    versions = {_result_version(r) for r in results}
    scoring_version = next(iter(versions)) if len(versions) == 1 else "mixed"

    # 效率指标
    has_metrics = any(r.metrics is not None for r in results)
    if has_metrics:
        metrics_list = [r.metrics for r in results if r.metrics is not None]
        idle_ratios = [m.cooker_idle_ratio for m in metrics_list]
        expireds = [m.expired_ingredients for m in metrics_list]
        clear_asms = [m.clear_assembly_count for m in metrics_list]
        serve_gaps = [m.avg_serve_interval for m in metrics_list]
        none_ratios = [m.none_ratio for m in metrics_list]
        stock_ins = [m.stockpile_inserts for m in metrics_list]
        stock_outs = [m.stockpile_pulls for m in metrics_list]
        stock_maxs = [m.stockpile_max_occupancy for m in metrics_list]

        return StrategyStats(
            name=results[0].strategy_name,
            games=len(results),
            avg_reward=mean(rewards),
            std_reward=stdev(rewards) if len(rewards) > 1 else 0.0,
            avg_steps=mean(steps),
            avg_actions=mean(actions),
            max_reward=max(rewards),
            min_reward=min(rewards),
            scoring_version=scoring_version,
            avg_score=mean(scores),
            std_score=stdev(scores) if len(scores) > 1 else 0.0,
            max_score=max(scores),
            min_score=min(scores),
            avg_idle_ratio=mean(idle_ratios),
            avg_expired=mean(expireds),
            avg_clear_asm=mean(clear_asms),
            avg_serve_gap=mean(serve_gaps),
            avg_none_ratio=mean(none_ratios),
            avg_stockpile_in=mean(stock_ins),
            avg_stockpile_out=mean(stock_outs),
            avg_stockpile_max=mean(stock_maxs),
            has_metrics=True,
        )

    return StrategyStats(
        name=results[0].strategy_name,
        games=len(results),
        avg_reward=mean(rewards),
        std_reward=stdev(rewards) if len(rewards) > 1 else 0.0,
        avg_steps=mean(steps),
        avg_actions=mean(actions),
        max_reward=max(rewards),
        min_reward=min(rewards),
        scoring_version=scoring_version,
        avg_score=mean(scores),
        std_score=stdev(scores) if len(scores) > 1 else 0.0,
        max_score=max(scores),
        min_score=min(scores),
    )


def paired_t_test(a: list[float], b: list[float]) -> tuple[float, float]:
    """
    配对 t 检验（向后兼容入口，实现在 bench/stats.py）。

    p 值按 df = n-1 的 t 分布双侧真实计算（不再做正态近似分档）。

    Returns:
        (t_statistic, p_value)
    """
    stats = paired_comparison(a, b)
    if stats is None:
        return 0.0, 1.0
    return stats.t_stat, stats.p_value


def histogram(values: list[float], bins: int = 10) -> list[int]:
    """把数值序列等宽分桶，返回各桶（升序）样本数。

    - 空序列返回 []
    - 全部等值退化为在 ``[v-0.5, v+0.5]`` 内等宽展开
    """
    return _bin_spec(values, bins)[2]


def _bin_spec(values: list[float], bins: int = 10) -> tuple[float, float, list[int]]:
    """返回 (左边界, 桶宽, 各桶计数)。纯观测，不依赖任何阈值。"""
    if not values:
        return 0.0, 0.0, []
    lo, hi = min(values), max(values)
    if lo == hi:
        lo -= 0.5
        hi += 0.5
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        idx = int((v - lo) / width)
        if idx >= bins:
            idx = bins - 1
        counts[idx] += 1
    return lo, width, counts


def print_distributions(
    results: dict[str, list[EpisodeResult]], bins: int = 10
) -> None:
    """输出每策略的 SrvGap 与 Idle% 分布直方图（只观测，不卡阈值）。

    数据源：每局 EfficiencyMetrics 的 avg_serve_interval 与 cooker_idle_ratio。
    """
    print("\n" + "-" * 80)
    print("SrvGap / Idle distributions (per-game; observe only — no thresholds)")

    for name, rs in results.items():
        srv = [
            round(m.avg_serve_interval, 2)
            for r in rs
            if (m := r.metrics) is not None
        ]
        idle = [
            round(m.cooker_idle_ratio * 100, 2)
            for r in rs
            if (m := r.metrics) is not None
        ]

        print(f"\n[{name}] SrvGap ({len(srv)} games):")
        _print_histogram(srv, bins=bins, unit="s")
        print(f"[{name}] Idle% ({len(idle)} games):")
        _print_histogram(idle, bins=bins, unit="%")

    print("-" * 80)


def _print_histogram(values: list[float], bins: int = 10, unit: str = "") -> None:
    """渲染单个 ASCII 直方图。"""
    if not values:
        print("  (no samples)")
        return

    lo, width, counts = _bin_spec(values, bins)
    max_count = max(counts) if counts else 1
    bar_width = 40

    for i, count in enumerate(counts):
        bar = "#" * round(count / max_count * bar_width) if max_count else ""
        lo_edge = lo + i * width
        hi_edge = lo + (i + 1) * width
        print(f"  {lo_edge:>6.2f}{unit} - {hi_edge:>6.2f}{unit}: {bar:<40} {count}")


def _fmt_p(p: float) -> str:
    """p 值格式化：常规保留 4 位小数，过小用科学计数法"""
    return f"{p:.4f}" if p >= 1e-4 else f"{p:.1e}"


def print_comparison(results: dict[str, list[EpisodeResult]]) -> None:
    """打印策略对比表格"""
    stats = {name: compute_stats(rs) for name, rs in results.items()}
    names = list(stats.keys())

    print("\n" + "=" * 80)
    print("Benchmark Results")
    versions = {s.scoring_version for s in stats.values()}
    print(f"Scoring version: {','.join(sorted(versions))} "
          f"(v1=sum only, v2=sum+final visibility)")
    print("Score caliber: final_score (v2; same column as CSV export)")
    print("=" * 80)

    # 表头
    print(f"\n{'Strategy':<20} {'Games':>6} {'Avg Score':>12} {'Std':>8} {'Max':>8} {'Min':>8} {'Actions':>8}")
    print("-" * 80)

    # 按平均 score（final_score 口径）排序
    sorted_names = sorted(names, key=lambda n: stats[n].avg_score, reverse=True)
    baseline_name = sorted_names[0]

    for name in sorted_names:
        s = stats[name]
        marker = " ★" if name == baseline_name else ""
        print(
            f"{s.name:<20} {s.games:>6} {s.avg_score:>12.1f} {s.std_score:>8.1f} "
            f"{s.max_score:>8.0f} {s.min_score:>8.0f} {s.avg_actions:>8.1f}{marker}"
        )

    # 配对对比（final_score 口径）
    if len(names) > 1:
        print("\n" + "-" * 80)
        print(f"Paired comparison (vs {baseline_name}) — score caliber: final_score")
        print("CRN note: shared seeds pair initial conditions only; random streams")
        print("diverge once strategies act differently — treat p-values as approximate.")
        cohen_hdr = "Cohen's d"
        print(f"{'Strategy':<20} {'Δ Score':>10} {'t-stat':>8} {'p-value':>10} {cohen_hdr:>9} {'95% CI':>22} {'Sig':>4}")
        print("-" * 80)

        baseline_scores = [_result_final(r) for r in results[baseline_name]]

        for name in sorted_names[1:]:
            scores = [_result_final(r) for r in results[name]]
            # Δ = 本策略 - baseline（正数 = 优于 baseline，与旧版口径一致）；
            # t / Cohen's d / CI 与 Δ 同号
            ps = paired_comparison(scores, baseline_scores)
            if ps is None:
                print(f"{name:<20}  (n/a: paired comparison needs >= 2 games)")
                continue
            delta = ps.mean_diff
            sig = "***" if ps.p_value <= 0.01 else "**" if ps.p_value <= 0.05 else "*" if ps.p_value <= 0.10 else ""
            print(
                f"{name:<20} {delta:>+10.1f} {ps.t_stat:>8.2f} {_fmt_p(ps.p_value):>10} "
                f"{ps.cohen_d:>9.2f} [{ps.ci_low:>9.1f}, {ps.ci_high:>9.1f}] {sig:>4}"
            )
            if ps.degenerate == "zero-variance":
                print(f"{'':<20} (degenerate: zero variance, p floored at 1e-12)")
            elif ps.degenerate == "identical":
                print(f"{'':<20} (degenerate: identical runs, p meaningless)")

    # 效率指标表
    if any(s.has_metrics for s in stats.values()):
        print("\n" + "-" * 80)
        print("Efficiency Metrics (averages)")
        print(f"{'Strategy':<20} {'Idle%':>6} {'Expired':>8} {'ClrAsm':>7} {'SrvGap':>7} {'None%':>6} {'StkIn':>6} {'StkOut':>6} {'StkMax':>6}")
        print("-" * 80)
        for name in sorted_names:
            s = stats[name]
            if s.has_metrics:
                print(
                    f"{s.name:<20} {s.avg_idle_ratio*100:>5.1f}% {s.avg_expired:>8.1f} "
                    f"{s.avg_clear_asm:>7.1f} {s.avg_serve_gap:>7.1f}s {s.avg_none_ratio*100:>5.1f}% "
                    f"{s.avg_stockpile_in:>6.1f} {s.avg_stockpile_out:>6.1f} {s.avg_stockpile_max:>6.1f}"
                )

    # SrvGap / Idle 分布直方图（每策略；只观测，不卡阈值）
    if any(s.has_metrics for s in stats.values()):
        print_distributions(results)

    print("=" * 80)


def export_csv(results: dict[str, list[EpisodeResult]], filepath: str) -> None:
    """导出为 CSV（含效率指标）"""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        header = ["strategy", "seed", "reward", "steps", "actions",
                  "final_score", "total_visibility", "scoring_version",
                  "idle_ratio", "expired", "clear_asm", "serve_gap",
                  "none_ratio", "stockpile_in", "stockpile_out", "stockpile_max"]
        writer.writerow(header)
        for name, rs in results.items():
            for r in rs:
                m = r.metrics
                row = [name, r.seed, r.total_reward, r.steps, r.actions_taken,
                       _result_final(r),
                       _result_visibility(r),
                       _result_version(r)]
                if m:
                    row.extend([
                        round(m.cooker_idle_ratio, 3),
                        m.expired_ingredients,
                        m.clear_assembly_count,
                        round(m.avg_serve_interval, 2),
                        round(m.none_ratio, 3),
                        m.stockpile_inserts,
                        m.stockpile_pulls,
                        m.stockpile_max_occupancy,
                    ])
                else:
                    row.extend([""] * 8)
                writer.writerow(row)

    print(f"Exported to {filepath}")


def export_json(results: dict[str, list[EpisodeResult]], filepath: str) -> None:
    """导出为 JSON"""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {}
    for name, rs in results.items():
        stats = compute_stats(rs)
        data[name] = {
            "stats": {
                "games": stats.games,
                "avg_reward": stats.avg_reward,
                "std_reward": stats.std_reward,
                "avg_score": stats.avg_score,
                "std_score": stats.std_score,
                "max_reward": stats.max_reward,
                "min_reward": stats.min_reward,
                "avg_steps": stats.avg_steps,
                "avg_actions": stats.avg_actions,
                "scoring_version": stats.scoring_version,
            },
            "games": [
                {
                    "seed": r.seed,
                    "reward": r.total_reward,
                    "final_score": _result_final(r),
                    "total_visibility": _result_visibility(r),
                    "scoring_version": _result_version(r),
                    "steps": r.steps,
                    "actions": r.actions_taken,
                }
                for r in rs
            ],
        }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Exported to {filepath}")
