"""
内置策略集合

美食站两个策略 + 甜点站一个策略：
  - GastronomeStrategy: 美食站（10 级贪心瀑布 + CPM + visibility + 单食材 + 延迟感知）
  - PlannerStrategy:    美食站（deadline 感知的滚动时域调度，Issue #21）
  - DessertStrategy:    甜点站（搅拌盆流水线，独立实现）
"""

from __future__ import annotations

from .gastronome import GastronomeStrategy
from .planner import PlannerStrategy
from .dessert import DessertStrategy

__all__ = [
    "GastronomeStrategy",
    "PlannerStrategy",
    "DessertStrategy",
]
