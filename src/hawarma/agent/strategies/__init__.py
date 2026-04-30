"""
内置策略集合

所有策略都接收 UnifiedState，返回 Action | None。

可用策略：
- DefaultStrategy: 安全默认策略（主动预烹饪 + 决策优先级优化）
- CPMStrategy: 关键路径法（SPT 优先，高吞吐）
- VisibilityAwareStrategy: CPM + visibility 阈值感知（当前最佳）
- PreemptScoreStrategy: 分数权重抢占（激进型变体）

已存档策略（见 archive/）：
- AgedCPMStrategy, ScoreAwareCPMStrategy, ScorePreemptStrategy
- BaselineStrategy, BaselineWithStockpileStrategy, PipelineBaselineStrategy
- CookingFirstV2Strategy, StockpileFirstStrategy

基准测试排名（50局）：
  1. VisibilityAwareStrategy  3916  (baseline)
  2. CPMStrategy              3878  (Δ -38, n.s.)
  3. PreemptScoreStrategy     3793  (Δ -124, p=0.01)
  4. DefaultStrategy          3736  (Δ -180, p=0.01)
"""

from __future__ import annotations

from .default import DefaultStrategy
from .cpm import CPMStrategy
from .visibility_aware import VisibilityAwareStrategy
from .preempt_score import PreemptScoreStrategy

__all__ = [
    "DefaultStrategy",
    "CPMStrategy",
    "VisibilityAwareStrategy",
    "PreemptScoreStrategy",
]
