"""
Playground Strategy 兼容层

所有策略已下沉到 hawarma.agent.strategies。
此文件保留向后兼容的 re-export。
"""

from __future__ import annotations

from hawarma.agent.strategy import Strategy

__all__ = ["Strategy"]
