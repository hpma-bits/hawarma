# hawarma/services/detection_service.py
"""
订单检测服务

地位：从屏幕截图中检测客户订单，识别配方、加急状态和调料偏好

输入：配置对象、配方列表、屏幕截图
输出：Order对象或None（当无订单时）

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

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
        Identifies the recipe in an order slot using first ingredient + cooker combination.

        Strategy:
        1. Detect the first ingredient
        2. If only one recipe matches that ingredient, return directly
        3. If multiple recipes match (conflict), detect the cooker to differentiate

        Args:
            order_slot: The index of the order slot to check.
            screen: The current screen snapshot.

        Returns:
            A tuple containing the best matching recipe and the confidence score.
        """
        # Step 1: Detect first ingredient, collect all matching recipes
        ingredient_matches = self._detect_first_ingredient(order_slot, screen)

        if not ingredient_matches:
            return None, 0.0

        # Step 2: No conflict - only one recipe uses this first ingredient
        if len(ingredient_matches) == 1:
            recipe, confidence = ingredient_matches[0]
            return recipe, confidence

        # Step 3: Conflict detected - use cooker to differentiate
        return self._resolve_cooker_conflict(ingredient_matches, order_slot, screen)

    def _detect_first_ingredient(
        self, order_slot: int, screen: np.ndarray
    ) -> list[Tuple[Recipe, float]]:
        """
        Detects the first ingredient and returns all recipes that use it.
        
        Returns:
            List of (recipe, confidence) tuples for all matching recipes
        """
        matches = []
        roi = self._get_ingredient_roi(order_slot, 0)

        for recipe in self.recipes:
            first_ingredient_path = (
                self.image_dir / f"ingredient-{recipe.raw_ingredients[0]}.jpg"
            )
            if not first_ingredient_path.exists():
                logger.warning(f"Template image not found: {first_ingredient_path}")
                continue

            template = Template(str(first_ingredient_path))
            match_result = local_match(target=template, roi=roi, screen=screen)

            if match_result and (confidence := float(match_result["confidence"])) > 0.7:
                matches.append((recipe, confidence))

        return matches

    def _resolve_cooker_conflict(
        self,
        candidate_recipes: list[Tuple[Recipe, float]],
        order_slot: int,
        screen: np.ndarray,
    ) -> Tuple[Recipe | None, float]:
        """
        Resolves conflict by detecting the cooker icon in the order region.
        
        The first ingredient's corresponding cooker icon is located at the 
        leftmost 1/4 of the order region (same area as first ingredient).
        """
        best_match = None
        best_confidence = 0.0
        
        # Get the order region for cooker detection
        order_region = self.config.screen.orders_regions[order_slot]

        for recipe, ingredient_confidence in candidate_recipes:
            # Get the cooker for the first ingredient
            cooker = recipe.cookers[0]
            cooker_icon_path = self.image_dir / f"icon-{cooker}.jpg"

            if not cooker_icon_path.exists():
                logger.warning(f"Coaker icon not found: {cooker_icon_path}")
                continue

            match = local_match(
                Template(str(cooker_icon_path), threshold=0.7),
                roi=order_region,
                screen=screen,
            )

            if match:
                # Combine confidences: ingredient * cooker
                combined_confidence = ingredient_confidence * float(match["confidence"])
                if combined_confidence > best_confidence:
                    best_match = recipe
                    best_confidence = combined_confidence

        return best_match, best_confidence

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

    def wait_for_game_start(self, timeout: int = 60):
        """
        Waits for the game to start by detecting the timer icon.

        Args:
            timeout: The maximum time to wait in seconds.
        """
        logger.info("Waiting for game to start... (looking for timer icon)")
        start_time = time.time()
        timer_icon_path = self.image_dir / "icon-timer.jpg"
        if not timer_icon_path.exists():
            logger.error("Timer icon template not found, cannot detect game start.")
            return

        while time.time() - start_time < timeout:
            screen = G.DEVICE.snapshot()
            if screen is None:
                time.sleep(0.5)
                continue

            # Define a broad region at the top of the screen to search for the icon
            w, h = self.config.screen.resolution
            roi = (0, 0, w, h // 4)  # Search in the top quarter of the screen

            match = local_match(
                Template(str(timer_icon_path), threshold=0.85), roi=roi, screen=screen
            )
            if match:
                logger.success("Game start detected!")
                time.sleep(3)  # Give some buffer time after detection
                return

        logger.warning("Timeout reached while waiting for game to start.")

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
        self, condiment_name: str, roi: tuple[int, int, int, int], screen: np.ndarray
    ) -> bool:
        """Checks if a specific condiment exists in a given region."""
        template_path = self.image_dir / f"ingredient-{condiment_name}.jpg"
        if not template_path.exists():
            return False
        return (
            local_match(Template(str(template_path)), roi=roi, screen=screen)
            is not None
        )

    def _get_condiment_count(
        self, roi: tuple[int, int, int, int], screen: np.ndarray
    ) -> int:
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
