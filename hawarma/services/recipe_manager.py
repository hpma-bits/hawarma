# hawarma/services/recipe_manager.py
import json
from pathlib import Path
from typing import List, Dict

from hawarma.models import Recipe

class RecipeManager:
    """Handles loading and accessing recipe data."""

    def __init__(self, recipes_path: Path | str = "data/recipes.json"):
        self._recipes_path = Path(recipes_path)
        self._recipes: List[Recipe] = []
        self._recipes_by_slug: Dict[str, Recipe] = {}

    def load_recipes(self) -> None:
        """Loads recipes from the JSON file and caches them."""
        if not self._recipes:
            with open(self._recipes_path, "r", encoding="utf-8") as f:
                recipes_data = json.load(f)
            
            self._recipes = [Recipe(**data) for data in recipes_data]
            self._recipes_by_slug = {recipe.slug: recipe for recipe in self._recipes}
            print(f"Loaded {len(self._recipes)} recipes.")

    def get_all_recipes(self) -> List[Recipe]:
        """Returns a list of all loaded recipes."""
        if not self._recipes:
            self.load_recipes()
        return self._recipes

    def get_recipe_by_slug(self, slug: str) -> Recipe | None:
        """Finds a recipe by its unique slug."""
        if not self._recipes_by_slug:
            self.load_recipes()
        return self._recipes_by_slug.get(slug)

