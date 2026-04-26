"""
Playground CookingFirstV2Strategy 兼容层

策略已下沉到 hawarma.agent.strategies.cooking_first_v2。
此文件保留向后兼容的 re-export。
"""

from __future__ import annotations

from hawarma.agent.strategies.cooking_first_v2 import CookingFirstV2Strategy

__all__ = ["CookingFirstV2Strategy"]
