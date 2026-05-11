"""
内置策略集合

所有策略都接收 UnifiedState，返回 Action | None。

可用策略：
- DefaultStrategy: 安全默认策略（主动预烹饪 + 决策优先级优化）
- CPMStrategy: 关键路径法（SPT 优先，高吞吐）
- VisibilityAwareStrategy: CPM + visibility 阈值感知
- PreemptScoreStrategy: 分数权重抢占（激进型变体）
- CPMEnhancedStrategy: CPM 增强（单食材优先 + visibility 阈值，当前最佳）

基准测试排名（100局）：
  1. CPMEnhancedStrategy       3934  (baseline)
  2. VisibilityAwareStrategy   3923  (Δ -11, n.s.)
  3. CPMStrategy               3878  (Δ -56, n.s.)
  4. PreemptScoreStrategy      3793  (Δ -141, p=0.01)
  5. DefaultStrategy           3736  (Δ -198, p=0.01)
"""

from __future__ import annotations

from .default import DefaultStrategy
from .cpm import CPMStrategy
from .visibility_aware import VisibilityAwareStrategy
from .preempt_score import PreemptScoreStrategy
from .cpm_enhanced import CPMEnhancedStrategy
from .delay_aware import DelayAwareCPMStrategy
from .dessert import DessertStrategy

__all__ = [
    "DefaultStrategy",
    "CPMStrategy",
    "VisibilityAwareStrategy",
    "PreemptScoreStrategy",
    "CPMEnhancedStrategy",
    "DelayAwareCPMStrategy",
    "DessertStrategy",
]
