# hawarma/models.py
"""
数据模型定义模块

地位：定义项目中的所有数据结构，是整个系统的基础类型层

输入：JSON数据或构造参数
输出：验证后的模型对象（Recipe、Order等）

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

import asyncio
import itertools
from dataclasses import dataclass, field
from enum import Enum, auto

from pydantic import BaseModel, field_validator


class Recipe(BaseModel):
    """Represents a cooking recipe."""

    slug: str
    name: str
    raw_ingredients: list[str]
    cookers: list[str]
    cookers_layout: list[str]
    cook_durations: list[float]
    condiments: list[str]

    @field_validator("cook_durations")
    def check_durations_length(cls, v, values):
        if "cookers" in values.data and len(v) != len(values.data["cookers"]):
            raise ValueError("cook_durations length must match cookers length")
        return v


class OrderStage(Enum):
    """Represents the different stages of an order."""

    PENDING = auto()
    HEATING = auto()
    OFF_HEAT = auto()  # Ingredients being moved to assembly
    READY_TO_SEASON = auto()  # All ingredients at assembly, ready for seasoning
    SEASONING = auto()
    SERVING = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class Order:
    """Represents a single cooking order."""

    recipe: Recipe
    is_rush: bool
    condiment_preference: dict[str, int]
    order_id: int = field(default_factory=itertools.count().__next__)
    done: bool = False
    current_stage: OrderStage = OrderStage.PENDING
    ingredient_prep_task: asyncio.Task | None = None
    finish_order_task: asyncio.Task | None = None
    served_ts: float | None = None  # Set when order is actually served
    ingredients_at_assembly: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"Order(id={self.order_id}, recipe={self.recipe.name}, rush={self.is_rush})"
        )
