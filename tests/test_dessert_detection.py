"""
Dessert order detection tests.

Tests Scanner's conflict resolution via second ingredient detection.
Uses mocked template matching to isolate the decision logic.

Conflict scenarios:
  - blanquette_fig → domeFigueMiel vs wildbloomSalad
  - golden_moon_flour → 8 mooncake variants
  - snowy_rice_flour → 8 snowskin mooncake variants

Also tests rush order detection.
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from hawarma.config import AppConfig
from hawarma.game.scanner import Scanner
from hawarma.recipe import Station
from hawarma.services.recipe_manager import RecipeManager


class FakeMatch:
    """Minimal mock for a template match result."""
    def __init__(self, confidence=0.9):
        self._confidence = confidence
    def get(self, key, default=None):
        return self._confidence if key == "confidence" else default


class TestDessertDetection(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        rm = RecipeManager(recipes_path="data/recipes.json")
        all_recipes = rm.get_all_recipes()
        cls.dessert_recipes = [r for r in all_recipes if r.station == Station.DESSERT]
        cls.recipe_by_slug = {r.slug: r for r in cls.dessert_recipes}

    def setUp(self):
        config = self._make_config()
        self.scanner = Scanner(config, self.dessert_recipes)

    def _make_config(self) -> MagicMock:
        config = MagicMock(spec=AppConfig)
        config.image_directory = str(Path(__file__).parent.parent / "static" / "img")
        screen = MagicMock()
        screen.ingredients_regions = [
            (500, 80, 720, 210), (875, 80, 1095, 210),
            (1250, 80, 1470, 210), (1620, 80, 1840, 210),
        ]
        screen.resolution = (1920, 1080)
        config.screen = screen
        game = MagicMock()
        game.rush_detection_positions = [(480, 195), (860, 195), (1230, 195), (1600, 195)]
        game.rush_red_threshold = 180
        config.game = game
        config.debug = MagicMock()
        config.debug.save_order_screenshots = False
        config.debug.screenshot_directory = "logs/order_screenshots"
        config.matching = MagicMock()
        return config

    def _candidates_for_first_ing(self, ing_name):
        """Helper: get all recipes sharing the same first ingredient."""
        return self.scanner._recipes_by_first_ingredient.get(ing_name, [])

    # ========================================================================
    # Test second ingredient resolution directly
    # ========================================================================

    def test_dome_figue_miel_resolved_vs_wildbloom_salad(self):
        """blanquette_fig conflict: second ingredient sparkling_sugar resolves to domeFigueMiel."""
        candidates = self._candidates_for_first_ing("blanquette_fig")
        self.assertEqual(len(candidates), 2)
        with patch("hawarma.game.scanner.local_match") as mock_match:
            def side_effect(template, roi, screen):
                path = str(template)
                if "sparkling_sugar" in path:
                    return FakeMatch(0.85)
                if "wildbloom_thyme" in path:
                    return FakeMatch(0.3)
                return None
            mock_match.side_effect = side_effect
            result = self.scanner._resolve_by_second_ingredient(candidates, 0, MagicMock())
        self.assertIsNotNone(result)
        self.assertEqual(result.slug, "domeFigueMiel")

    def test_wildbloom_salad_resolved_vs_dome_figue_miel(self):
        """blanquette_fig conflict: second ingredient wildbloom_thyme resolves to wildbloomSalad."""
        candidates = self._candidates_for_first_ing("blanquette_fig")
        with patch("hawarma.game.scanner.local_match") as mock_match:
            def side_effect(template, roi, screen):
                path = str(template)
                if "sparkling_sugar" in path:
                    return FakeMatch(0.3)
                if "wildbloom_thyme" in path:
                    return FakeMatch(0.85)
                return None
            mock_match.side_effect = side_effect
            result = self.scanner._resolve_by_second_ingredient(candidates, 0, MagicMock())
        self.assertIsNotNone(result)
        self.assertEqual(result.slug, "wildbloomSalad")

    def test_mooncake_thyme_resolved_among_8(self):
        """golden_moon_flour conflict: second ingredient wildbloom_thyme → mooncakeThyme."""
        candidates = self._candidates_for_first_ing("golden_moon_flour")
        self.assertEqual(len(candidates), 8)
        with patch("hawarma.game.scanner.local_match") as mock_match:
            def side_effect(template, roi, screen):
                path = str(template)
                # Only mooncakeThyme has wildbloom_thyme as second ingredient
                if "wildbloom_thyme" in path:
                    return FakeMatch(0.85)
                return FakeMatch(0.3)
            mock_match.side_effect = side_effect
            result = self.scanner._resolve_by_second_ingredient(candidates, 0, MagicMock())
        self.assertIsNotNone(result)
        self.assertEqual(result.slug, "mooncakeThyme")

    def test_snow_skin_mooncake_beef_resolved_among_8(self):
        """snowy_rice_flour conflict: second ingredient prime_cut_beef → snowSkinMooncakeBeef."""
        candidates = self._candidates_for_first_ing("snowy_rice_flour")
        self.assertEqual(len(candidates), 8)
        with patch("hawarma.game.scanner.local_match") as mock_match:
            def side_effect(template, roi, screen):
                path = str(template)
                if "prime_cut_beef" in path:
                    return FakeMatch(0.85)
                return FakeMatch(0.3)
            mock_match.side_effect = side_effect
            result = self.scanner._resolve_by_second_ingredient(candidates, 0, MagicMock())
        self.assertIsNotNone(result)
        self.assertEqual(result.slug, "snowSkinMooncakeBeef")

    def test_conflict_all_second_ings_low_confidence_returns_none(self):
        """When all second ingredient matches are below threshold, resolve returns None."""
        candidates = self._candidates_for_first_ing("blanquette_fig")
        with patch("hawarma.game.scanner.local_match") as mock_match:
            mock_match.return_value = FakeMatch(0.3)
            result = self.scanner._resolve_by_second_ingredient(candidates, 0, MagicMock())
        self.assertIsNone(result)

    # ========================================================================
    # Test rush detection
    # ========================================================================

    def test_rush_order_detected_via_red_pixel(self):
        """Rush order detection: red pixel check below threshold."""
        # Simulate a red pixel (low red value)
        red_pixel = MagicMock()
        red_pixel.shape = (1080, 1920, 3)
        import numpy as np
        red_screen = np.zeros((1080, 1920, 3), dtype=np.uint8)
        red_screen[195, 480] = [50, 50, 50]  # BGR — low red means bright red
        is_rush = self.scanner._detect_rush(0, red_screen)
        self.assertTrue(is_rush)

    # ========================================================================
    # Test normal order (non-rush)
    # ========================================================================

    def test_normal_order_detected_via_red_pixel(self):
        """Normal order: high red pixel value means not rush."""
        import numpy as np
        non_red_screen = np.zeros((1080, 1920, 3), dtype=np.uint8)
        non_red_screen[195, 480] = [200, 200, 200]  # BGR — high red means pale
        is_rush = self.scanner._detect_rush(0, non_red_screen)
        self.assertFalse(is_rush)

    # ========================================================================
    # Test full _detect_order with mocked local_match
    # ========================================================================

    @patch("hawarma.game.scanner.local_match")
    @patch.object(Scanner, "_detect_rush", return_value=False)
    def test_unique_first_ingredient_detected(self, mock_rush, mock_local_match):
        """Unique first ingredient: direct detection, no conflict resolution."""
        self._mock_first_ingredient(mock_local_match, "brambleberry", 0.85)
        order = self.scanner._detect_order(0, MagicMock())
        self.assertIsNotNone(order)
        self.assertEqual(order.recipe_slug, "cocoaBerryBliss")

    @patch("hawarma.game.scanner.local_match")
    @patch.object(Scanner, "_detect_rush", return_value=False)
    def test_low_confidence_returns_none(self, mock_rush, mock_local_match):
        """Below-threshold confidence returns None."""
        self._mock_first_ingredient(mock_local_match, "brambleberry", 0.5)
        order = self.scanner._detect_order(0, MagicMock())
        self.assertIsNone(order)

    def _mock_first_ingredient(self, mock, ing_name, confidence):
        """Helper: mock local_match to return given confidence for a specific first ingredient."""
        def side_effect(template, roi, screen):
            path = str(template)
            if ing_name in path:
                return FakeMatch(confidence)
            return None
        mock.side_effect = side_effect


if __name__ == "__main__":
    unittest.main()
