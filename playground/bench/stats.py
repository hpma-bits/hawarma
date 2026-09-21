"""
基准统计工具（Issue #15）

纯统计函数：t 分布 CDF / 分位数、配对 t 检验（真实双侧 p 值）、
配对 Cohen's d、Δ 均值 95% CI。

不引入第三方依赖：t 分布概率用正则化不完全 beta 函数实现
（``math.lgamma`` + 连分式 betacf，Numerical Recipes 标准算法）。

边界规则（保守处理）：
- 差值序列零方差（d_std == 0）：
  - d_mean != 0：t = +inf，p 取下限 ``DEGENERATE_P_FLOOR``（1e-12）并标注
    ``degenerate="zero-variance"``，不再硬编码 0.0
  - d_mean == 0（两组完全一致）：t = 0，p = 1.0，标注 ``degenerate="identical"``
- 样本数 < 2 或两组长度不一致：``paired_comparison`` 返回 None

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean, stdev

DEGENERATE_P_FLOOR = 1e-12
"""零方差但均值非零时的 p 值下限（真实 p 更小，保守取该值避免硬编码 0.0）"""


@dataclass
class PairedStats:
    """配对比较统计结果（差值 = a - b）"""

    n: int
    """配对样本数"""
    df: int
    """自由度 = n - 1"""
    mean_diff: float
    """Δ 均值 = mean(a) - mean(b)"""
    std_diff: float
    """差值样本标准差"""
    t_stat: float
    """配对 t 统计量"""
    p_value: float
    """双侧 p 值（df = n-1 的 t 分布）"""
    cohen_d: float
    """配对 Cohen's d = mean_diff / std_diff"""
    ci_low: float
    """Δ 均值 95% CI 下界"""
    ci_high: float
    """Δ 均值 95% CI 上界"""
    degenerate: str | None = None
    """退化情形标注：'zero-variance'（差值全等但非零）/ 'identical'（两组完全一致）"""


def _betacf(a: float, b: float, x: float, max_iter: int = 300, eps: float = 3e-12) -> float:
    """正则化不完全 beta 函数的连分式（modified Lentz，Numerical Recipes §6.4）"""
    tiny = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """I_x(a, b)：正则化不完全 beta 函数"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_bt = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log(1.0 - x)
    )
    bt = math.exp(ln_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_two_sided_p(t: float, df: int) -> float:
    """t 分布双侧尾概率 P(|T| >= |t|)，df 为自由度"""
    if df <= 0:
        return float("nan")
    x = df / (df + t * t)
    return regularized_incomplete_beta(df / 2.0, 0.5, x)


def t_cdf(t: float, df: int) -> float:
    """t 分布累计分布函数 P(T <= t)"""
    if df <= 0:
        return float("nan")
    tail = 0.5 * t_two_sided_p(t, df)
    return 1.0 - tail if t >= 0 else tail


def t_ppf(prob: float, df: int) -> float:
    """t 分布分位数（CDF 反函数），二分法求根；prob ∈ (0, 1)"""
    lo, hi = -1e3, 1e3
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if t_cdf(mid, df) < prob:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def paired_comparison(a: list[float], b: list[float]) -> PairedStats | None:
    """
    配对 t 检验 + 效应量。

    Args:
        a: baseline 序列（每局分数）
        b: 对照序列（每局分数，与 a 按 seed 一一配对）

    Returns:
        PairedStats；样本 < 2 或长度不一致时返回 None
    """
    if len(a) != len(b) or len(a) < 2:
        return None

    diffs = [x - y for x, y in zip(a, b)]
    n = len(diffs)
    df = n - 1
    d_mean = mean(diffs)
    d_std = stdev(diffs)

    if d_std == 0.0:
        if d_mean == 0.0:
            return PairedStats(
                n=n, df=df, mean_diff=0.0, std_diff=0.0,
                t_stat=0.0, p_value=1.0, cohen_d=0.0,
                ci_low=0.0, ci_high=0.0, degenerate="identical",
            )
        return PairedStats(
            n=n, df=df, mean_diff=d_mean, std_diff=0.0,
            t_stat=math.inf, p_value=DEGENERATE_P_FLOOR, cohen_d=math.inf,
            ci_low=d_mean, ci_high=d_mean, degenerate="zero-variance",
        )

    se = d_std / math.sqrt(n)
    t = d_mean / se
    p = t_two_sided_p(t, df)
    tcrit = t_ppf(0.975, df)
    return PairedStats(
        n=n, df=df, mean_diff=d_mean, std_diff=d_std,
        t_stat=t, p_value=p, cohen_d=d_mean / d_std,
        ci_low=d_mean - tcrit * se, ci_high=d_mean + tcrit * se,
    )


def paired_t_test(a: list[float], b: list[float]) -> tuple[float, float]:
    """
    配对 t 检验（向后兼容入口）。

    与旧版的区别：p 值按 df = n-1 的 t 分布双侧真实计算，
    不再做 1.645/1.96/2.576 正态近似分档。

    Returns:
        (t_statistic, p_value)
    """
    stats = paired_comparison(a, b)
    if stats is None:
        return 0.0, 1.0
    return stats.t_stat, stats.p_value
