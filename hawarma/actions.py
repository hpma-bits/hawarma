"""
Action Definitions

地位：定义Scheduler返回的所有行动计划类型，是决策与执行之间的契约。
Scheduler决定"做什么"，Executor决定"怎么做"。

输入：Scheduler决策结果
输出：Executor可执行的原子动作对象

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from dataclasses import dataclass
from typing import Literal


@dataclass
class Action:
    """
    Base class for all actions.
    
    Actions are returned by Scheduler and executed by Executor.
    Each action is atomic: either fully completed or not executed at all.
    """
    pass


@dataclass
class CookIngredient(Action):
    """
    Cook one raw ingredient and move it to destination.
    
    Atomic operation:
    1. Acquire cooker lock
    2. Swipe raw ingredient → cooker
    3. Sleep for cook duration
    4. Swipe cooker → destination (assembly or stockpile)
    5. Update GameState
    6. Release cooker lock
    
    Attributes:
        order_id: The order this ingredient belongs to. None for stockpile prep.
        ingredient_name: Which ingredient to cook.
        cooker_name: Which cooker to use.
        destination: "assembly" or "stockpile".
        stockpile_slot: Required if destination="stockpile".
    """
    order_id: int | None
    ingredient_name: str
    cooker_name: str
    destination: Literal["assembly", "stockpile"]
    stockpile_slot: int | None = None
    _move_only: bool = False


@dataclass
class PullFromStockpile(Action):
    """
    Move a cooked ingredient from stockpile slot to assembly station.
    
    Atomic operation:
    1. Acquire stockpile slot lock
    2. Decrement stockpile count in GameState
    3. Swipe stockpile → assembly
    4. Update assembly state in GameState
    5. Release stockpile slot lock
    
    Attributes:
        order_id: The order this ingredient belongs to.
        ingredient_name: Which ingredient to pull.
        stockpile_slot: Which stockpile slot to pull from.
    """
    order_id: int
    ingredient_name: str
    stockpile_slot: int


@dataclass
class FinishOrder(Action):
    """
    Season and serve a complete order to its pickup station.
    
    Atomic operation:
    1. Apply all condiments (swipe each condiment → assembly)
    2. Swipe assembly → pickup station
    3. Update GameState (order.done=True, counts)
    4. Advance slots to fill gaps
    
    Prerequisites (enforced by Scheduler):
    - All ingredients for the order must be at assembly
    - Assembly must be owned by this order
    
    Attributes:
        order_id: The order to finish.
        pickup_slot: Which pickup station to serve to.
    """
    order_id: int
    pickup_slot: int
