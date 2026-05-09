"""
MixingBowlState 单元测试
"""

import unittest

from hawarma.core.models import MixingBowlState


class TestMixingBowlState(unittest.TestCase):

    def test_default_initialization(self):
        bowl = MixingBowlState()
        self.assertEqual(bowl.ingredients, [])
        self.assertEqual(bowl.condiments, {})
        self.assertIsNone(bowl.target_recipe_slug)
        self.assertFalse(bowl.is_stirred)

    def test_is_empty_true_by_default(self):
        bowl = MixingBowlState()
        self.assertTrue(bowl.is_empty)

    def test_is_empty_false_with_ingredients(self):
        bowl = MixingBowlState()
        bowl.ingredients.append("flour")
        self.assertFalse(bowl.is_empty)

    def test_is_free_true_by_default(self):
        bowl = MixingBowlState()
        self.assertTrue(bowl.is_free)

    def test_is_free_false_with_target_recipe(self):
        bowl = MixingBowlState()
        bowl.target_recipe_slug = "domeFigueMiel"
        self.assertFalse(bowl.is_free)

    def test_is_ready_to_cook_with_two_ingredients_and_stirred(self):
        bowl = MixingBowlState()
        bowl.ingredients = ["flour", "honey"]
        bowl.is_stirred = True
        self.assertTrue(bowl.is_ready_to_cook)

    def test_is_ready_to_cook_false_not_stirred(self):
        bowl = MixingBowlState()
        bowl.ingredients = ["flour", "honey"]
        bowl.is_stirred = False
        self.assertFalse(bowl.is_ready_to_cook)

    def test_is_ready_to_cook_false_single_ingredient(self):
        bowl = MixingBowlState()
        bowl.ingredients = ["flour"]
        bowl.is_stirred = True
        self.assertFalse(bowl.is_ready_to_cook)

    def test_is_ready_to_cook_false_empty(self):
        bowl = MixingBowlState()
        bowl.is_stirred = True
        self.assertFalse(bowl.is_ready_to_cook)

    def test_reset_clears_all(self):
        bowl = MixingBowlState()
        bowl.ingredients = ["flour", "honey"]
        bowl.condiments = {"sugar": 1}
        bowl.target_recipe_slug = "domeFigueMiel"
        bowl.is_stirred = True

        bowl.reset()

        self.assertEqual(bowl.ingredients, [])
        self.assertEqual(bowl.condiments, {})
        self.assertIsNone(bowl.target_recipe_slug)
        self.assertFalse(bowl.is_stirred)


if __name__ == "__main__":
    unittest.main()
