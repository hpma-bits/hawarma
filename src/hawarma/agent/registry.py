"""
策略注册表

支持通过配置字符串动态加载策略类。

使用方式：
    strategy = get_strategy("cpm")
    action = strategy.decide(env.get_unified_state())

注册新策略：
    在 _STRATEGY_REGISTRY 中添加映射即可

可用策略：
- default: DefaultStrategy（安全默认）
- cpm: CPMStrategy（关键路径法）
- visibility_aware: VisibilityAwareStrategy（CPM + visibility 阈值）
- preempt_score: PreemptScoreStrategy（分数权重抢占）
- cpm_enhanced: CPMEnhancedStrategy（CPM 增强，当前最佳）
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hawarma.agent.strategy import Strategy


_STRATEGY_REGISTRY: dict[str, str] = {
    "default": "hawarma.agent.strategies.default:DefaultStrategy",
    "cpm": "hawarma.agent.strategies.cpm:CPMStrategy",
    "visibility_aware": "hawarma.agent.strategies.visibility_aware:VisibilityAwareStrategy",
    "preempt_score": "hawarma.agent.strategies.preempt_score:PreemptScoreStrategy",
    "cpm_enhanced": "hawarma.agent.strategies.cpm_enhanced:CPMEnhancedStrategy",
    "dessert": "hawarma.agent.strategies.dessert:DessertStrategy",
}


def list_strategies() -> list[str]:
    """返回所有可用的策略名称"""
    return sorted(_STRATEGY_REGISTRY.keys())


def get_strategy(name: str) -> Strategy:
    """
    根据名称获取策略实例。

    Args:
        name: 策略名称（如 "default", "cpm"）

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