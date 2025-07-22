import itertools
import threading
from typing import ClassVar

from hawarma.config import load_config
from hawarma.models import Recipe

config = load_config()


class IngredientHandler:
    def __init__(self, ingredient):
        self.ingredient = ingredient

    def prepare(self):
        # Placeholder for preparation logic
        return f"Prepared {self.ingredient}"

    def cook(self):
        # Placeholder for cooking logic
        return f"Cooked {self.ingredient}"

    def serve(self):
        # Placeholder for serving logic
        return f"Served {self.ingredient}"


class Cooker:
    _instance: ClassVar[dict[str, "Cooker"]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __new__(cls, cooker_name: str):
        if cooker_name not in cls._instance:
            with cls._lock:
                if cooker_name not in cls._instance:
                    instance = super().__new__(cls)
                    instance._initialize(cooker_name)
                    cls._instance[cooker_name] = instance
        return cls._instance[cooker_name]

    def _initialize(self, cooker_name: str):
        self.type = cooker_name
        self.current_ingredient = None
        self._status_lock = threading.Lock()


class ResourceManager:
    """Manages positions of cookers, ingredients and condiments"""

    def __init__(self, recipes: list[Recipe]):
        self.recipes = recipes

    def get_cookers_positions(self) -> dict[str, tuple[int, int]]:
        """Get positions for all required cookers"""
        cookers = list(
            dict.fromkeys(
                cooker
                for recipe in self.recipes
                for cooker in recipe.cookers
                if cooker in config.cookers
            ).keys()
        )

        # logger.debug(f"Cookers: {cookers}")
        cookers_count = len(cookers)

        return {
            cooker: config.cookers_potential_positions[
                idx + 1 if cookers_count < 3 else idx
            ]
            for idx, cooker in enumerate(cookers)
        }

    def get_raw_ingredients_positions(self) -> dict[str, tuple[int, int]]:
        """Get positions for all required raw ingredients"""
        ingredients = list(
            dict.fromkeys(
                itertools.chain.from_iterable(
                    recipe.raw_ingredients for recipe in self.recipes
                )
            ).keys()
        )
        ingredients.reverse()  # Reverse to match screen positions

        # logger.debug(f"Raw ingredients: {ingredients}")
        return {
            ingredient: config.raw_ingredients_potential_positions[idx]
            for idx, ingredient in enumerate(ingredients)
        }

    def get_condiments_positions(self) -> dict[str, tuple[int, int]]:
        """Get positions for all required condiments"""
        condiments = list(
            dict.fromkeys(
                itertools.chain.from_iterable(
                    recipe.condiments for recipe in self.recipes
                )
            ).keys()
        )

        # logger.debug(f"Condiments: {condiments}")
        return {
            condiment: config.condiments_potential_positions[idx]
            for idx, condiment in enumerate(condiments)
        }
