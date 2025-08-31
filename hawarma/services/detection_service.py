# hawarma/services/detection_service.py
import time
from collections import defaultdict
from typing import List, Dict, Tuple
from pathlib import Path

import cv2
import numpy as np
from airtest.core.api import G, Template
from loguru import logger

from hawarma.config import AppConfig
from hawarma.models import Order, Recipe
from hawarma.utils.image_utils import local_match


class DetectionService:
    """
    A service responsible for detecting customer orders from the screen.

    This service analyzes screenshots of the game to identify which recipes have
    been ordered, whether they are rush orders, and what condiments are required.
    """

    def __init__(self, recipes: List[Recipe], config: AppConfig):
        """
        Initializes the DetectionService.

        Args:
            recipes: A list of all possible recipes that can be ordered.
            config: The application configuration.
        """
        self.recipes = recipes
        self.config = config
        self.image_dir = Path(config.image_directory)
        self.ingredient_regions = config.screen.ingredients_regions
        self.matching_strategy = config.matching.ingredients_strategy
        self.recipe_confidence_threshold = 0.8  # Minimum confidence to detect a recipe

    def detect_order(self, slot: int) -> Order | None:
        """
        Detects if a valid order exists in the specified order slot.

        Args:
            slot: The index of the order slot to check.

        Returns:
            An Order object if an order is detected, otherwise None.
        """
        screen = None
        while screen is None:
            # wait for a valid screenshot
            screen = G.DEVICE.snapshot()

        best_match_recipe, confidence = self._detect_recipe(
            order_slot=slot, screen=screen
        )

        if best_match_recipe and confidence > self.recipe_confidence_threshold:
            logger.info(
                f"Detected recipe '{best_match_recipe.name}' in slot {slot} with confidence {confidence:.2f}."
            )

            is_rush = self._detect_rush_order(slot, screen)
            condiment_pref = self._detect_condiments(
                slot=slot, recipe=best_match_recipe, screen=screen
            )

            self._save_debug_screenshot(slot, best_match_recipe, condiment_pref, screen)

            return Order(
                recipe=best_match_recipe,
                is_rush=is_rush,
                condiment_preference=condiment_pref,
            )
        return None

    def _detect_recipe(
        self, order_slot: int, screen: np.ndarray
    ) -> Tuple[Recipe | None, float]:
        """
        Identifies the recipe in an order slot by matching its first ingredient.

        Args:
            order_slot: The index of the order slot to check.
            screen: The current screen snapshot.

        Returns:
            A tuple containing the best matching recipe and the confidence score.
        """
        best_match_recipe, best_confidence = None, 0.0
        roi = self._get_ingredient_roi(order_slot, 0)

        for recipe in self.recipes:
            # The first ingredient is unique enough to identify a recipe
            first_ingredient_path = (
                self.image_dir / f"ingredient-{recipe.raw_ingredients[0]}.jpg"
            )
            if not first_ingredient_path.exists():
                logger.warning(f"Template image not found: {first_ingredient_path}")
                continue

            template = Template(str(first_ingredient_path))
            match_result = local_match(target=template, roi=roi, screen=screen)

            if (
                match_result
                and (confidence := float(match_result["confidence"])) > best_confidence
            ):
                best_match_recipe = recipe
                best_confidence = confidence

        return best_match_recipe, best_confidence

    def _get_ingredient_roi(
        self, order_slot: int, ingredient_slot: int
    ) -> Tuple[int, int, int, int]:
        """Calculates the region of interest (ROI) for a specific ingredient in an order."""
        x1, y1, x2, y2 = self.ingredient_regions[order_slot]
        width = x2 - x1
        quarter_width = width // 4
        return (
            x1 + ingredient_slot * quarter_width,
            y1,
            x1 + (ingredient_slot + 1) * quarter_width,
            y2,
        )

    def _detect_rush_order(self, slot: int, screen: np.ndarray) -> bool:
        """Detects if an order is a rush order (indicated by a timer icon)."""
        timer_icon_path = self.image_dir / "icon-timer.jpg"
        if not timer_icon_path.exists():
            return False

        # Define a region where the rush icon appears (adjust as needed)
        x1, y1, x2, y2 = self.config.screen.orders_regions[slot]
        roi = (x1, y1, x2, y1 + 50)  # Check the top part of the order region

        match = local_match(
            Template(str(timer_icon_path), threshold=0.8), roi=roi, screen=screen
        )
        return match is not None

    def _detect_condiments(
        self, slot: int, recipe: Recipe, screen: np.ndarray
    ) -> Dict[str, int]:
        """Detects the condiment preferences for an order."""
        preference = defaultdict(int)
        condiment_candidates = recipe.condiments
        if not condiment_candidates:
            return preference

        # Determine which slots to check for condiments
        condiment_slots = [1, 2] if len(recipe.raw_ingredients) == 1 else [2, 3]

        for slot_index in condiment_slots:
            roi = self._get_ingredient_roi(slot, slot_index)
            for condiment in condiment_candidates:
                if self._match_condiment(condiment, roi, screen):
                    preference[condiment] = self._get_condiment_count(roi, screen)
                    break  # Move to the next slot once a condiment is found
        return preference

    def _match_condiment(
        self, condiment_name: str, roi: list, screen: np.ndarray
    ) -> bool:
        """Checks if a specific condiment exists in a given region."""
        template_path = self.image_dir / f"ingredient-{condiment_name}.jpg"
        if not template_path.exists():
            return False
        return (
            local_match(Template(str(template_path)), roi=roi, screen=screen)
            is not None
        )

    def _get_condiment_count(self, roi: list, screen: np.ndarray) -> int:
        """Determines if a condiment has a 'double' icon."""
        double_icon_path = self.image_dir / "icon-double.jpg"
        if not double_icon_path.exists():
            return 1

        match = local_match(
            Template(str(double_icon_path), threshold=0.8), roi=roi, screen=screen
        )
        return 2 if match else 1

    def _save_debug_screenshot(
        self, slot: int, recipe: Recipe, prefs: Dict[str, int], screen: np.ndarray
    ):
        """Saves a screenshot of the detected order for debugging."""
        log_path = Path(self.config.log_directory)
        log_path.mkdir(exist_ok=True)
        prefs_str = "-".join(f"{k}{v}" for k, v in prefs.items())
        filename = f"{log_path}/slot{slot}-{recipe.slug}-{prefs_str}-{time.perf_counter():.4f}.jpg"
        cv2.imwrite(filename, screen)
