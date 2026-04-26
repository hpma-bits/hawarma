"""
内置策略集合

所有策略都接收 UnifiedState，返回 Action | None。
"""

from __future__ import annotations

from .default import DefaultStrategy
from .cooking_first_v2 import CookingFirstV2Strategy
from .stockpile_first import StockpileFirstStrategy

__all__ = ["DefaultStrategy", "CookingFirstV2Strategy", "StockpileFirstStrategy"]
