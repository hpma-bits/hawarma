"""
策略注册表

按 Station 分组的两个用户级策略：
  - "gastronome": 美食站 — 10 级贪心瀑布 + CPM + visibility + 单食材 + 延迟感知
  - "dessert":    甜点站 — 搅拌盆流水线
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hawarma.agent.strategy import Strategy

_STRATEGY_REGISTRY: dict[str, str] = {
    "gastronome": "hawarma.agent.strategies.gastronome:GastronomeStrategy",
    "dessert": "hawarma.agent.strategies.dessert:DessertStrategy",
}


def list_strategies() -> list[str]:
    """返回所有可用的策略名称"""
    return sorted(_STRATEGY_REGISTRY.keys())


def list_user_strategies() -> list[str]:
    """返回用户级策略名称（CLI/TUI 使用）"""
    return ["gastronome", "dessert"]


def get_strategy(name: str) -> Strategy:
    """
    根据名称获取策略实例。

    Args:
        name: 策略名称（如 "gastronome", "dessert"）

    Returns:
        Strategy: 策略实例

    Raises:
        ValueError: 策略名称不存在
    """
    name = name.lower().strip()
    path = _STRATEGY_REGISTRY.get(name)
    if not path:
        available = ", ".join(list_strategies())
        raise ValueError(f"Unknown strategy '{name}'. Available: {available}")

    mod_path, cls_name = path.split(":")
    mod = __import__(mod_path, fromlist=[cls_name])
    cls = getattr(mod, cls_name)
    return cls()


def register_strategy(name: str, import_path: str) -> None:
    """
    注册新策略（用于扩展）。

    Args:
        name: 策略名称
        import_path: "module.path:ClassName" 格式
    """
    _STRATEGY_REGISTRY[name.lower().strip()] = import_path
