from pathlib import Path
import json
from hawarma.models import Recipe


class RecipeManager:
    _instance = None
    _recipes = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RecipeManager, cls).__new__(cls)
            cls._instance.__init__()
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True

    def load_recipes(
        self, recipe_file: str | Path = "wow_recipes.json"
    ) -> list[Recipe]:
        """Load and cache recipes from a JSON file.
        Subsequent calls will return cached recipes.

        Args:
            recipe_file: Path to the recipes JSON file. Defaults to "recipes.json" in current dir.

        Returns:
            List of validated Recipe objects

        Raises:
            FileNotFoundError: If recipe file doesn't exist
            ValueError: If recipe validation fails
        """
        if self._recipes is not None:
            return self._recipes

        recipe_path = Path(recipe_file)
        if not recipe_path.exists():
            raise FileNotFoundError(f"Recipe file not found: {recipe_path.absolute()}")

        try:
            with recipe_path.open("r", encoding="utf-8") as f:
                recipes_data = json.load(f)
            self._recipes = [Recipe(**recipe) for recipe in recipes_data]
            return self._recipes
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in recipe file: {e}")
        except Exception as e:
            raise ValueError(f"Error loading recipes: {e}")


RECIPES = RecipeManager().load_recipes()
