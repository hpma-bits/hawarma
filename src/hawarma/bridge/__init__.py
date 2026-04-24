"""
Bridge 模块

地位：连接 Agent 与游戏环境的桥接层
       提供 GameEnvironment（真实游戏）和 SimulatorEnvironment（模拟器适配器）
       以及 OrderScanner、UIRunner 和 RealGameBridge

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from .base_environment import BaseEnvironment, CookerState, AssemblyState, StockpileSlot, OrderInfo
from .environment import GameEnvironment
from .simulator_environment import SimulatorEnvironment
 
# scanner / ui_runner / bridge 依赖 airtest，在 airtest 不可用时延迟导入
__all__ = [
    "BaseEnvironment",
    "GameEnvironment",
    "SimulatorEnvironment",
    "CookerState",
    "AssemblyState",
    "StockpileSlot",
    "OrderInfo",
    "OrderScanner",
    "DetectedOrder",
    "UIRunner",
    "RealGameBridge",
]


def __getattr__(name: str):
    if name in ("OrderScanner", "DetectedOrder"):
        from .scanner import OrderScanner, DetectedOrder
        return {"OrderScanner": OrderScanner, "DetectedOrder": DetectedOrder}[name]
    if name == "UIRunner":
        from .ui_runner import UIRunner
        return UIRunner
    if name == "RealGameBridge":
        from .bridge import RealGameBridge
        return RealGameBridge
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
