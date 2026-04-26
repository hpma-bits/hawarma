"""
Playground StockpileFirstStrategy 兼容层

策略已下沉到 hawarma.agent.strategies.stockpile_first。
此文件保留向后兼容的 re-export。
"""

from __future__ import annotations

from hawarma.agent.strategies.stockpile_first import StockpileFirstStrategy

__all__ = ["StockpileFirstStrategy"]
