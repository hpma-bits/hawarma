"""
策略注册表

支持通过配置字符串动态加载策略类。

使用方式：
    strategy = get_strategy("gastronome")   # 推荐：用户界面使用
    strategy = get_strategy("dessert")      # 甜点模式
    strategy = get_strategy("cpm_cascade")  # 内部/benchmark 使用

注册表分组：
  - 用户级（推荐 CLI/TUI 使用）：gastronome, dessert
  - 内部级（bench/playground 使用）：全部策略名

架构说明：
  所有 Gastronome 策略都基于 GreedyCascadeStrategy 的贪心瀑布框架。
  最佳策略是 CPMEnhancedCascadeStrategy（benchmark: 3934 avg reward）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hawarma.agent.strategy import Strategy

_STRATEGY_REGISTRY: dict[str, str] = {
    # ── 用户级（推荐 CLI/TUI 使用） ──
    "gastronome": "hawarma.agent.strategies.cpm_enhanced:CPMEnhancedCascadeStrategy",
    "dessert": "hawarma.agent.strategies.dessert:DessertStrategy",

    # ── 内部级（bench/playground 精确指定） ──
    "greedy_cascade": "hawarma.agent.strategies.default:GreedyCascadeStrategy",
    "cpm_cascade": "hawarma.agent.strategies.cpm:CPMCascadeStrategy",
    "visibility_cascade": "hawarma.agent.strategies.visibility_aware:VisibilityAwareCascadeStrategy",
    "preempt_cascade": "hawarma.agent.strategies.preempt_score:PreemptScoreCascadeStrategy",
    "cpm_enhanced_cascade": "hawarma.agent.strategies.cpm_enhanced:CPMEnhancedCascadeStrategy",
    "delay_cascade": "hawarma.agent.strategies.delay_aware:DelayAwareCascadeStrategy",

    # ── 向后兼容旧名 ──
    "default": "hawarma.agent.strategies.default:GreedyCascadeStrategy",
    "cpm": "hawarma.agent.strategies.cpm:CPMCascadeStrategy",
    "visibility_aware": "hawarma.agent.strategies.visibility_aware:VisibilityAwareCascadeStrategy",
    "preempt_score": "hawarma.agent.strategies.preempt_score:PreemptScoreCascadeStrategy",
    "cpm_enhanced": "hawarma.agent.strategies.cpm_enhanced:CPMEnhancedCascadeStrategy",
    "delay_aware": "hawarma.agent.strategies.delay_aware:DelayAwareCascadeStrategy",
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
        name: 策略名称（如 "gastronome", "cpm_cascade"）

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
