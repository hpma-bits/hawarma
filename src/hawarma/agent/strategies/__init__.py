"""
内置策略集合 — 贪心瀑布（Greedy Cascade）架构

所有 Gastronome 策略共享 GreedyCascadeStrategy 的 10 级贪心瀑布决策框架，
仅覆写 _prioritized_orders / _try_clear_assembly / _try_parallel_cooking 等来
调整排序、抢占、烹饪策略。

Gastronome 策略（按基准测试排名）：
  1. CPMEnhancedCascadeStrategy   3934  (baseline, 当前最佳)
  2. VisibilityAwareCascadeStrategy  3923  (Δ -11, n.s.)
  3. CPMCascadeStrategy             3878  (Δ -56, n.s.)
  4. PreemptScoreCascadeStrategy    3793  (Δ -141, p=0.01)
  5. GreedyCascadeStrategy          3736  (Δ -198, p=0.01)

Dessert 策略：
  - DessertStrategy: 独立贪心瀑布（搅拌盆流水线）
"""

from __future__ import annotations

from .default import GreedyCascadeStrategy
from .cpm import CPMCascadeStrategy
from .visibility_aware import VisibilityAwareCascadeStrategy
from .preempt_score import PreemptScoreCascadeStrategy
from .cpm_enhanced import CPMEnhancedCascadeStrategy
from .delay_aware import DelayAwareCascadeStrategy
from .dessert import DessertStrategy

# 向后兼容别名
DefaultStrategy = GreedyCascadeStrategy
CPMStrategy = CPMCascadeStrategy
VisibilityAwareStrategy = VisibilityAwareCascadeStrategy
PreemptScoreStrategy = PreemptScoreCascadeStrategy
CPMEnhancedStrategy = CPMEnhancedCascadeStrategy
DelayAwareCPMStrategy = DelayAwareCascadeStrategy

__all__ = [
    "GreedyCascadeStrategy",
    "CPMCascadeStrategy",
    "VisibilityAwareCascadeStrategy",
    "PreemptScoreCascadeStrategy",
    "CPMEnhancedCascadeStrategy",
    "DelayAwareCascadeStrategy",
    "DessertStrategy",
    # 向后兼容别名
    "DefaultStrategy",
    "CPMStrategy",
    "VisibilityAwareStrategy",
    "PreemptScoreStrategy",
    "CPMEnhancedStrategy",
    "DelayAwareCPMStrategy",
]
