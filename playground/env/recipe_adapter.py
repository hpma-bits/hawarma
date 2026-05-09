"""
Recipe Adapter

将 env_simulator_types.Recipe 转换为 Agent/Strategy 期望的格式。
提供统一的属性访问接口。
"""

from __future__ import annotations


class RecipeAdapter:
    """Recipe adapter: converts simulator Recipe to Agent-expected format"""

    def __init__(self, sim_recipe):
        self._recipe = sim_recipe

    @property
    def slug(self) -> str:
        return self._recipe.slug

    @property
    def name(self) -> str:
        return self._recipe.name

    @property
    def raw_ingredients(self) -> list[str]:
        return [ing.name for ing in self._recipe.ingredients]

    @property
    def cookers(self) -> list[str]:
        return [ing.cooker for ing in self._recipe.ingredients]

    @property
    def cook_durations(self) -> list[float] | None:
        return [ing.duration for ing in self._recipe.ingredients]

    @property
    def condiments(self) -> dict[str, int]:
        return self._recipe.condiments
