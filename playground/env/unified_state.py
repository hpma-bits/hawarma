"""
Playground UnifiedState 兼容层

UnifiedState 已下沉到 hawarma.agent.unified_state。
此文件保留向后兼容的 re-export。
"""

from __future__ import annotations

from hawarma.agent.unified_state import UnifiedState

__all__ = ["UnifiedState"]
