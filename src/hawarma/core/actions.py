"""
核心动作类型定义

Strategy 产出 Action，Env 消费 Action。
Action 是 Strategy 和 Env 之间的操作契约。

按 station 分组：
  - 基础动作：两种 station 共享
  - Gastronome 专用
  - Dessert 专用（预留）
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Action:
    """动作基类"""


# ── 基础动作（两种 station 共享） ──

@dataclass
class AddCondimentAction(Action):
    """调味"""
    condiment: str


@dataclass
class ClearCookerAction(Action):
    """清理灶台"""
    cooker: str


@dataclass
class ClearAssemblyAction(Action):
    """清空组装站"""


# ── Gastronome 专用 ──

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


# ── Dessert 专用（预留） ──