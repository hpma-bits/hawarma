import os
from pathlib import Path
import time
from unittest import TestCase

import cv2
from hawarma.order_detector import ImageMatcher, OrderDetector
from hawarma.models import Recipe
from hawarma.config_loader import get_config
from hawarma.recipes import RECIPES


class TestOrderDetector(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.TEST_DIR = Path(__file__).parent / "testset"
        cls.sample_images = {
            img_name: cv2.imread(str(cls.TEST_DIR / img_name))
            for img_name in os.listdir(cls.TEST_DIR)
        }
        cls.config = get_config()

    def setUp(self):
        # Initialize OrderDetector with real recipes and image matcher
        self.recipes = RECIPES  # Replace with real recipes
        self.image_matcher = ImageMatcher()  # Replace with real image matcher
        self.order_detector = OrderDetector(self.recipes, self.image_matcher)
        self.test_start = time.perf_counter()

    def tearDown(self):
        # Clean up if necessary
        end = time.perf_counter()
        print(
            f"\nTest {self._testMethodName} completed in {end - self.test_start:.4f} seconds"
        )

    def _parse_test_metadata(self, filename):
        """
        Extract test parameters from standardized filenames
        Format: slot{0-3}-recipe{id}-[condiment_flags].jpg
        Example: slot1-recipe42-110.jpg -> {'slot': 1, 'recipe_id': 42, 'condiments': [1,1,0]}
        """
        stem = Path(filename).stem
        try:
            parts = stem.split("-")
            if len(parts) != 4:
                raise ValueError("Filename must contain exactly 3 hyphens")

            return {
                "slot": int(parts[0].replace("order", "")),
                "recipe_id": int(parts[1]),
                "condiments": [int(x) for x in parts[2]],
                "is_rush": parts[3] == "rush",
            }
        except (ValueError, AttributeError) as e:
            raise ValueError(f"Invalid test image name '{filename}': {str(e)}")

    def test_detect_recipe(self):
        # Test the detect_recipe method with a real order slot and screen
        for img_name, screen in self.sample_images.items():
            with self.subTest(test_img_name=img_name):
                try:
                    meta = self._parse_test_metadata(img_name)
                    result = self.order_detector.detect_recipe(meta["slot"], screen)
                    self.assertIsInstance(
                        result,
                        Recipe,
                        f"Expected dict for {img_name}, got {type(result)}",
                    )
                    self.assertEqual(
                        result.slug,
                        self.recipes[meta["recipe_id"]].slug,
                        f"Recipe slug mismatch for {img_name}",
                    )
                except Exception as e:
                    self.fail(f"Error processing {img_name}: {e}")

    def test_detect_condiments_preference(self):
        # Test the detect_condiments_preference method with a real recipe and screen
        for img_name, screen in self.sample_images.items():
            with self.subTest(test_img_name=img_name):
                try:
                    meta = self._parse_test_metadata(img_name)
                    recipe = self.recipes[meta["recipe_id"]]
                    result = self.order_detector.detect_condiments_preference(
                        meta["slot"], recipe, screen
                    )
                    self.assertIsInstance(
                        result,
                        dict,
                        f"Expected dict for {img_name}, got {type(result)}",
                    )

                    self.assertEqual(
                        list(result.values()),
                        meta["condiments"],
                        f"Condiment preference mismatch for {img_name}",
                    )
                except Exception as e:
                    self.fail(f"Error processing {img_name}: {e}")
