"""
核心动作类型定义

Strategy 产出 Action，Env 消费 Action。
Action 是 Strategy 和 Env 之间的操作契约。

按 station 分组：
  - 共享：ClearCookerAction
  - Gastronome 专用：AddCondimentAction, ClearAssemblyAction, CookAction,
    MoveToAssemblyAction, MoveToStockpileAction, PullFromStockpileAction,
    ServeOrderAction
  - Dessert 专用：MoveToMixingBowlAction, AddCondimentToMixingBowlAction,
    StirAction, MoveMixingBowlToCookerAction, ServeFromCookerAction,
    ClearMixingBowlAction
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Action:
    """动作基类"""


# ── 共享（两种 station 都用） ──

@dataclass
class ClearCookerAction(Action):
    """清理灶台"""
    cooker: str


# ── Gastronome 专用 ──

@dataclass
class AddCondimentAction(Action):
    """调料区 → 组装站"""
    condiment: str


@dataclass
class ClearAssemblyAction(Action):
    """清空组装站"""


@dataclass
class CookAction(Action):
    """食材区 → 灶台烹饪"""
    ingredient: str
    cooker: str
    duration: float
    order_id: int | None = None


@dataclass
class MoveToAssemblyAction(Action):
    """灶台 → 组装站"""
    cooker: str
    order_id: int | None = None


@dataclass
class MoveToStockpileAction(Action):
    """灶台 → 库存"""
    cooker: str
    slot: str


@dataclass
class PullFromStockpileAction(Action):
    """库存 → 组装站"""
    slot: str
    ingredient: str


@dataclass
class ServeOrderAction(Action):
    """组装站 → 取餐台"""
    slot_idx: int


# ── Dessert 专用 ──

@dataclass
class MoveToMixingBowlAction(Action):
    """食材区 → 搅拌盆"""
    ingredient: str


@dataclass
class AddCondimentToMixingBowlAction(Action):
    """调料区 → 搅拌盆"""
    condiment: str


@dataclass
class StirAction(Action):
    """搅拌（从搅拌盆坐标向左水平滑动）"""
    distance: float = 400.0
    duration: float = 1.5
    steps: int = 10


@dataclass
class MoveMixingBowlToCookerAction(Action):
    """搅拌盆 → 灶台"""
    cooker: str


@dataclass
class ServeFromCookerAction(Action):
    """灶台 → 取餐台"""
    cooker: str
    slot_idx: int


@dataclass
class ClearMixingBowlAction(Action):
    """清空搅拌盆"""
    pass