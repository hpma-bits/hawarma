"""
core: 数据层定义

项目核心数据类型，不含业务逻辑。
被 Strategy、Env、Bridge 共同引用。
"""

from .actions import (
    Action,
    CookAction,
    MoveToAssemblyAction,
    MoveToStockpileAction,
    PullFromStockpileAction,
    AddCondimentAction,
    ServeOrderAction,
    ClearCookerAction,
    ClearAssemblyAction,
)
from .state import UnifiedState

__all__ = [
    "Action",
    "CookAction",
    "MoveToAssemblyAction",
    "MoveToStockpileAction",
    "PullFromStockpileAction",
    "AddCondimentAction",
    "ServeOrderAction",
    "ClearCookerAction",
    "ClearAssemblyAction",
    "UnifiedState",
]