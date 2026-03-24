# hawarma/services/recipe_manager.py
"""
配方管理服务

地位：从JSON文件加载配方数据，提供配方查询接口

输入：JSON文件路径
输出：Recipe对象列表

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

import json
from pathlib import Path

from loguru import logger

from hawarma.models import Recipe


class RecipeManager:
    """
    Handles loading, accessing, and managing recipe data from a JSON file.
    """

    def __init__(self, recipes_path: Path | str = "data/recipes.json"):
        """
        Initializes the RecipeManager.

        Args:
            recipes_path: The path to the JSON file containing recipe data.
        """
        self._recipes_path = Path(recipes_path)
        self._recipes: list[Recipe] = []
        self._recipes_by_slug: dict[str, Recipe] = {}

    def load_recipes(self) -> None:
        """
        Loads recipes from the JSON file into memory.

        This method reads the recipe data, parses it, and creates a list of
        Recipe objects. It also creates a mapping from recipe slugs to Recipe
        objects for quick lookups.
        """
        if self._recipes:
            return  # Avoid reloading if already loaded

        try:
            with open(self._recipes_path, "r", encoding="utf-8") as f:
                recipes_data = json.load(f)

            self._recipes = [Recipe(**data) for data in recipes_data]
            self._recipes_by_slug = {recipe.slug: recipe for recipe in self._recipes}
            logger.info(
                f"Successfully loaded {len(self._recipes)} recipes from {self._recipes_path}."
            )
        except FileNotFoundError:
            logger.error(f"Recipe file not found at: {self._recipes_path}")
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from recipe file: {self._recipes_path}")
        except Exception as e:
            logger.error(f"An unexpected error occurred while loading recipes: {e}")

    def get_all_recipes(self) -> list[Recipe]:
        """
        Returns a list of all loaded recipes.

        If the recipes have not been loaded yet, this method will trigger
        the loading process.

        Returns:
            A list of all Recipe objects.
        """
        if not self._recipes:
            self.load_recipes()
        return self._recipes

    def get_recipe_by_slug(self, slug: str) -> Recipe | None:
        """
        Finds a recipe by its unique slug.

        Args:
            slug: The slug of the recipe to find.

        Returns:
            The Recipe object if found, otherwise None.
        """
        if not self._recipes_by_slug:
            self.load_recipes()
        return self._recipes_by_slug.get(slug)
