# tests/test_recipe_manager.py
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from hawarma.services.recipe_manager import RecipeManager
from hawarma.models import Recipe

class TestRecipeManager(unittest.TestCase):
    def setUp(self):
        self.test_recipes_data = [
            {
                "slug": "test-recipe-1",
                "name": "Test Recipe 1",
                "raw_ingredients": ["ingredient-a", "ingredient-b"],
                "cookers": ["grill", "oven"],
                "cook_durations": [10.0, 15.0],
                "condiments": ["condiment-x"],
            },
            {
                "slug": "test-recipe-2",
                "name": "Test Recipe 2",
                "raw_ingredients": ["ingredient-c"],
                "cookers": ["pan"],
                "cook_durations": [5.0],
                "condiments": ["condiment-y", "condiment-z"],
            },
        ]
        self.test_recipes_path = Path("tests/test_recipes.json")
        with open(self.test_recipes_path, "w") as f:
            json.dump(self.test_recipes_data, f)

    def tearDown(self):
        if self.test_recipes_path.exists():
            self.test_recipes_path.unlink()

    def test_load_recipes(self):
        recipe_manager = RecipeManager(recipes_path=self.test_recipes_path)
        recipe_manager.load_recipes()
        
        self.assertEqual(len(recipe_manager.get_all_recipes()), 2)
        self.assertIsInstance(recipe_manager.get_all_recipes()[0], Recipe)

    def test_get_all_recipes(self):
        recipe_manager = RecipeManager(recipes_path=self.test_recipes_path)
        recipes = recipe_manager.get_all_recipes()
        
        self.assertEqual(len(recipes), 2)
        self.assertEqual(recipes[0].name, "Test Recipe 1")

    def test_get_recipe_by_slug(self):
        recipe_manager = RecipeManager(recipes_path=self.test_recipes_path)
        recipe = recipe_manager.get_recipe_by_slug("test-recipe-1")
        
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.name, "Test Recipe 1")
        
        non_existent_recipe = recipe_manager.get_recipe_by_slug("non-existent")
        self.assertIsNone(non_existent_recipe)

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_load_recipes_file_not_found(self, mock_open):
        recipe_manager = RecipeManager(recipes_path="non_existent_file.json")
        recipe_manager.load_recipes()
        
        self.assertEqual(len(recipe_manager.get_all_recipes()), 0)

    @patch("json.load", side_effect=json.JSONDecodeError("mock error", "", 0))
    def test_load_recipes_json_error(self, mock_json_load):
        recipe_manager = RecipeManager(recipes_path=self.test_recipes_path)
        recipe_manager.load_recipes()
        
        self.assertEqual(len(recipe_manager.get_all_recipes()), 0)

if __name__ == "__main__":
    unittest.main()
