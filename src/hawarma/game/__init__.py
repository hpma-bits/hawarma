"""
Game 模块

游戏控制层，管理游戏生命周期、环境状态、UI 操作和订单检测。

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from .game_env import GameEnv
from hawarma.core.models import CookerState, AssemblyState, StockpileSlot, Order, MixingBowlState

__all__ = [
    "GameEnv",
    "CookerState",
    "AssemblyState",
    "MixingBowlState",
    "StockpileSlot",
    "Order",
    "Scanner",
    "DetectedOrder",
    "Operator",
    "Runner",
]


def __getattr__(name: str):
    if name in ("Scanner", "DetectedOrder"):
        from .scanner import Scanner, DetectedOrder
        return {"Scanner": Scanner, "DetectedOrder": DetectedOrder}[name]
    if name == "Operator":
        from .operator import Operator
        return Operator
    if name == "Runner":
        from .runner import Runner
        return Runner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")