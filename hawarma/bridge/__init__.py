"""
Bridge 模块

地位：连接 Agent 与真实游戏环境的桥接层
      提供 GameEnvironment、OrderScanner、UIRunner 和 RealGameBridge

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from .environment import GameEnvironment, CookerState, AssemblyState, StockpileSlot, OrderInfo

# scanner / ui_runner / bridge 依赖 airtest，在 airtest 不可用时延迟导入
__all__ = [
    "GameEnvironment",
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
