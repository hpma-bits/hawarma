"""planner 策略基准与失败案例分析脚本（Issue #21）.

复现 100 局配对基准（planner vs gastronome）并输出 CSV 不包含的维度：
每局 served/timeout 对比、rush 单服务数、食材过期数、最差局清单、
deadline 违约分布（ORDER_TIMEOUT 事件直方）与不可行订单统计。

运行方式（必须 PYTHONPATH=src 指向本 worktree；PYTHONHASHSEED 固定以消除
gastronome 预烹饪 set 迭代序的过程间抖动，与 report.md 主口径一致）：

    cd <worktree>
    PYTHONHASHSEED=0 PYTHONPATH=src python experiments/planner_strategy/script.py

依赖: playground/ 环境、hawarma.agent.strategies.planner（本仓库代码）
"""

from __future__ import annotations

import math
import statistics
import sys
from collections import Counter
from pathlib import Path

# 自包含路径：worktree 根（playground/）与 src/（hawarma/）
_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from playground.agents.base import Agent
from playground.bench.stats import paired_comparison
from playground.core.episode import run_episode
from playground.env.sim import SimEnv
from playground.env_simulator_types import EventType

from hawarma.agent.strategies.gastronome import GastronomeStrategy
from hawarma.agent.strategies.planner import PlannerStrategy

GAMES = 100
SEEDS = list(range(GAMES))
STRATEGIES = {
    "gastronome": GastronomeStrategy,
    "planner": PlannerStrategy,
}


def run_one(cls, seed: int) -> dict:
    """跑一局，收集事件级统计（比 EpisodeResult 更细的失败分析维度）."""
    env = SimEnv()
    agent = Agent(cls())
    obs, info = env.reset(seed=seed)
    agent.reset()
    agent.strategy.on_game_start(info.get("recipes", {}))
    serves: list[dict] = []
    timeouts = 0
    expired_ingredients = 0
    steps = 0
    while steps < 2000:
        action = agent.act(obs)
        result = env.step(action)
        agent.observe(result.observation, result.reward, result.terminated, result.info)
        obs = result.observation
        steps += 1
        for ev in result.info.get("events", []):
            if ev.event_type == EventType.ORDER_SERVED:
                serves.append(ev.details)
            elif ev.event_type == EventType.ORDER_TIMEOUT:
                timeouts += 1
            elif ev.event_type == EventType.INGREDIENT_EXPIRED:
                expired_ingredients += 1
        if result.terminated or result.truncated:
            break
    gaps = [
        b["served_at"] - a["served_at"] for a, b in zip(serves, serves[1:])
    ]
    return {
        "seed": seed,
        "final_score": env.finalize(),
        "served": len(serves),
        "rush_served": sum(1 for s in serves if s["score"] > 0 and _is_rush(s)),
        "timeouts": timeouts,
        "expired": expired_ingredients,
        "total_visibility": float(obs.total_visibility),
        "avg_serve_gap": statistics.mean(gaps) if gaps else float("nan"),
        "serves": serves,
    }


def _is_rush(serve_details: dict) -> bool:
    """从事件 details 推断 rush：不可直接判定时返回 False（保守）.

    事件不含 is_rush 字段；rush 单得分为 base_total × rush 倍率（≥1.6），
    normal ≤1.5。用 reward.csv 基准值比对推断。
    """
    from hawarma.core.reward import RecipeRewardLookup

    lookup = _is_rush._lookup
    row = lookup._data.get(serve_details["recipe"])
    if not row:
        return False
    base = row["base_with_cond"] + row["visibility_with_cond"]
    # multiplier = score / base；rush ≥ 1.6，normal ≤ 1.5
    return serve_details["score"] / base >= 1.55


_is_rush._lookup = None  # type: ignore[attr-defined]


def main() -> int:
    from hawarma.core.reward import RecipeRewardLookup

    _is_rush._lookup = RecipeRewardLookup()  # type: ignore[attr-defined]

    results: dict[str, list[dict]] = {name: [] for name in STRATEGIES}
    for i, seed in enumerate(SEEDS):
        for name, cls in STRATEGIES.items():
            results[name].append(run_one(cls, seed))
        if (i + 1) % 20 == 0:
            print(f"  completed {i + 1}/{GAMES} games", flush=True)

    print("\n=== per-strategy aggregates (100 games) ===")
    header = (
        f"{'strategy':<12} {'avg':>8} {'std':>8} {'served':>7} "
        f"{'rush':>5} {'timeout':>8} {'expired':>8} {'srvGap':>7} {'vis':>7}"
    )
    print(header)
    for name, rs in results.items():
        print(
            f"{name:<12} "
            f"{statistics.mean(r['final_score'] for r in rs):>8.1f} "
            f"{statistics.stdev(r['final_score'] for r in rs):>8.1f} "
            f"{statistics.mean(r['served'] for r in rs):>7.2f} "
            f"{statistics.mean(r['rush_served'] for r in rs):>5.2f} "
            f"{statistics.mean(r['timeouts'] for r in rs):>8.2f} "
            f"{statistics.mean(r['expired'] for r in rs):>8.2f} "
            f"{statistics.mean(r['avg_serve_gap'] for r in rs):>7.2f} "
            f"{statistics.mean(r['total_visibility'] for r in rs):>7.1f}"
        )

    g = [r["final_score"] for r in results["gastronome"]]
    p = [r["final_score"] for r in results["planner"]]
    ps = paired_comparison(p, g)
    print("\n=== paired comparison (planner - gastronome, final_score) ===")
    if ps:
        print(
            f"n={ps.n} Δ={ps.mean_diff:+.1f} t={ps.t_stat:.2f} p={ps.p_value:.4f} "
            f"d={ps.cohen_d:.2f} CI=[{ps.ci_low:.1f}, {ps.ci_high:.1f}]"
        )

    # 每局 served/timeout 差
    d_served = [rp["served"] - rg["served"] for rp, rg in zip(results["planner"], results["gastronome"])]
    d_timeouts = [rp["timeouts"] - rg["timeouts"] for rp, rg in zip(results["planner"], results["gastronome"])]
    print("\n=== per-game served/timeout deltas (planner - gastronome) ===")
    print(f"served delta: mean={statistics.mean(d_served):+.2f} "
          f"games_better={sum(1 for d in d_served if d > 0)} "
          f"games_worse={sum(1 for d in d_served if d < 0)} "
          f"games_equal={sum(1 for d in d_served if d == 0)}")
    print(f"timeout delta: mean={statistics.mean(d_timeouts):+.2f} "
          f"planner_total={sum(r['timeouts'] for r in results['planner'])} "
          f"gastronome_total={sum(r['timeouts'] for r in results['gastronome'])}")

    # deadline 违约分布（ORDER_TIMEOUT 总数为 0 时输出 0 直方）
    print("\n=== deadline violation distribution (ORDER_TIMEOUT per game) ===")
    for name, rs in results.items():
        dist = Counter(r["timeouts"] for r in rs)
        print(f"{name}: {dict(sorted(dist.items()))}")

    # 失败案例分析：planner 输得最多的 5 局
    deltas = sorted(
        (
            (rp["final_score"] - rg["final_score"], rp["seed"], rg, rp)
            for rp, rg in zip(results["planner"], results["gastronome"])
        ),
    )[:5]
    print("\n=== worst-5 planner losses (failure cases) ===")
    for delta, seed, rg, rp in deltas:
        print(
            f"seed={seed:<3} Δ={delta:>7.0f} | gastro score={rg['final_score']:.0f} "
            f"served={rg['served']} rush={rg['rush_served']} exp={rg['expired']} | "
            f"planner score={rp['final_score']:.0f} served={rp['served']} "
            f"rush={rp['rush_served']} exp={rp['expired']}"
        )

    # 不可行订单：timeout>0 的局（如为 0，说明当前模拟器参数下 deadline 不约束）
    infeasible = [r for r in results["planner"] if r["timeouts"] > 0]
    print(f"\nplanner games with order timeouts (infeasible orders): {len(infeasible)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
