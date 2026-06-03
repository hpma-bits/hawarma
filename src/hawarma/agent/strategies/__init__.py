"""
内置策略集合

两个独立的 Station 各自一个策略：
  - GastronomeStrategy: 美食站（10 级贪心瀑布 + CPM + visibility + 单食材 + 延迟感知）
  - DessertStrategy:    甜点站（搅拌盆流水线，独立实现）
"""

from __future__ import annotations

from .gastronome import GastronomeStrategy
from .dessert import DessertStrategy

__all__ = [
    "GastronomeStrategy",
    "DessertStrategy",
]
