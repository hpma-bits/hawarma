# hawarma/recipe.py
"""
数据模型定义模块

地位：定义项目中的所有数据结构，是整个系统的基础类型层

输入：JSON数据或构造参数
输出：验证后的模型对象（Recipe等）

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, field_validator


@dataclass
class Ingredient:
    """配方中的食材-灶台-时长三元组"""

    name: str
    cooker: str
    duration: float


class Station(Enum):
    """制作台类型"""

    GASTRONOME = "gastronome"
    DESSERT = "dessert"


class Recipe(BaseModel):
    """Represents a cooking recipe."""

    slug: str
    name: str
    station: Station = Station.GASTRONOME
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

    @property
    def ingredients(self) -> list[Ingredient]:
        """将并行列表转为结构化对象"""
        return [
            Ingredient(name, cooker, duration)
            for name, cooker, duration in zip(
                self.raw_ingredients, self.cookers, self.cook_durations
            )
        ]
