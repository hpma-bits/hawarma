# hawarma/recipe.py
"""
配方数据模型

统一定义，供真实环境和模拟器共享。
Recipe 是两个环境之间共享配方信息的唯一模型，
不再有模拟器专有的 Recipe 类型。

输入：JSON数据或构造参数
输出：验证后的模型对象

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, field_validator


@dataclass
class IngredientRequirement:
    """配方中的食材需求：名称、灶台类型、烹饪时长"""

    name: str
    cooker_type: str
    duration: float


class Station(Enum):
    """制作台类型"""

    GASTRONOME = "gastronome"
    DESSERT = "dessert"


class Recipe(BaseModel):
    """Represents a cooking recipe.

    Shared by both real environment and simulator.
    condiments supports both list[str] (from JSON) and dict[str, int] formats.
    """

    slug: str
    name: str
    station: Station = Station.GASTRONOME
    raw_ingredients: list[str]
    cookers: list[str]
    cookers_layout: list[str]
    cook_durations: list[float]
    condiments: dict[str, int]

    @field_validator("cook_durations")
    @classmethod
    def check_durations_length(cls, v, values):
        if "cookers" in values.data and len(v) != len(values.data["cookers"]):
            raise ValueError("cook_durations length must match cookers length")
        return v

    @field_validator("condiments", mode="before")
    @classmethod
    def normalize_condiments(cls, v):
        if isinstance(v, list):
            return {name: 1 for name in v}
        return v

    @property
    def ingredients(self) -> list[IngredientRequirement]:
        """将并行列表转为结构化对象"""
        return [
            IngredientRequirement(name=name, cooker_type=cooker, duration=duration)
            for name, cooker, duration in zip(
                self.raw_ingredients, self.cookers, self.cook_durations
            )
        ]
