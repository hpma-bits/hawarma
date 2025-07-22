# hawarma/services/detection_service.py
import time
from collections import defaultdict
from typing import List, Dict, Tuple
from pathlib import Path

import cv2
import numpy as np
from airtest.core.api import G, Template
from loguru import logger

from hawarma.models import Order, Recipe
from hawarma.utils.image_utils import local_match

class DetectionService:
    """Detects customer orders from the screen."""

    def __init__(
        self,
        recipes: List[Recipe],
        config: "AppConfig", # Using string forward reference
    ):
        self.recipes = recipes
        self.config = config
        self.image_dir = config.image_directory
        self.ingredient_regions = config.screen.ingredients_regions
        self.matching_strategy = config.matching.ingredients_strategy

    def detect_order(self, slot: int) -> Order | None:
        """Detect if an order exists in the specified slot."""
        screen = G.DEVICE.snapshot()

        if best_match_recipe := self._detect_recipe(order_slot=slot, screen=screen):
            is_rush = self._detect_rush_order(slot, screen)
            condiment_pref = self._detect_condiments(
                slot=slot, recipe=best_match_recipe, screen=screen
            )
            
            # For debugging, similar to original
            log_path = Path(self.config.log_directory)
            log_path.mkdir(exist_ok=True)
            cv2.imwrite(
                f"{log_path}/slot{slot}-{best_match_recipe.slug}-{tuple(condiment_pref.values())}-{time.perf_counter():.4f}.jpg",
                screen,
            )
            
            return Order(
                recipe=best_match_recipe,
                is_rush=is_rush,
                condiment_preference=condiment_pref,
            )
        return None

    def _detect_recipe(self, order_slot: int, screen: np.ndarray) -> Recipe | None:
        """Identifies the recipe in an order slot by its first ingredient."""
        best_match_recipe, best_match_confidence = None, 0.0
        # The first ingredient is unique enough to identify a recipe
        roi = self._get_ingredient_roi(order_slot, 0)

        for recipe in self.recipes:
            first_ingredient_path = f"{self.image_dir}/ingredient-{recipe.raw_ingredients[0]}.jpg"
            template = Template(first_ingredient_path)
            
            match_result = local_match(target=template, roi=roi, screen=screen)
            
            if match_result and float(match_result["confidence"]) > best_match_confidence:
                best_match_recipe = recipe
                best_match_confidence = float(match_result["confidence"])
        
        return best_match_recipe

    def _get_ingredient_roi(self, order_slot: int, ingredient_slot: int) -> Tuple[int, int, int, int]:
        rect = self.ingredient_regions[order_slot]
        width = rect[2] - rect[0]
        quarter_width = width // 4
        return (
            rect[0] + ingredient_slot * quarter_width,
            rect[1],
            rect[2] - (3 - ingredient_slot) * quarter_width,
            rect[3],
        )

    def _detect_rush_order(self, slot: int, screen: np.ndarray) -> bool:
        """Detects if an order is a rush order."""
        # This logic was not implemented in the original script.
        # Placeholder for future implementation.
        return False

    def _detect_condiments(self, slot: int, recipe: Recipe, screen: np.ndarray) -> Dict[str, int]:
        """Detects condiment preferences for an order."""
        preference = defaultdict(lambda: 0)
        condiment_candidates = recipe.condiments
        
        # Determine which slots to check for condiments based on number of raw ingredients
        condiment_slots = [1, 2] if len(recipe.raw_ingredients) == 1 else [2, 3]

        # Check first condiment slot
        roi1 = self._get_condiment_roi(slot, condiment_slots[0])
        if self._match_condiment(condiment_candidates[0], roi1, screen):
            preference[condiment_candidates[0]] = self._get_condiment_count(roi1, screen)
            
            # If first condiment found, check second slot for second condiment
            roi2 = self._get_condiment_roi(slot, condiment_slots[1])
            if len(condiment_candidates) > 1 and self._match_condiment(condiment_candidates[1], roi2, screen):
                preference[condiment_candidates[1]] = self._get_condiment_count(roi2, screen)
        
        # If first condiment not in first slot, it must be the second condiment
        elif len(condiment_candidates) > 1 and self._match_condiment(condiment_candidates[1], roi1, screen):
            preference[condiment_candidates[1]] = self._get_condiment_count(roi1, screen)

        return preference

    def _match_condiment(self, condiment_name: str, roi: list, screen: np.ndarray) -> bool:
        template_path = f"{self.image_dir}/ingredient-{condiment_name}.jpg"
        return local_match(
            Template(template_path),
            roi=roi,
            strategy=self.matching_strategy,
            screen=screen,
        ) is not None

    def _get_condiment_count(self, roi: list, screen: np.ndarray) -> int:
        double_icon_path = f"{self.image_dir}/icon-double.jpg"
        if local_match(
            Template(double_icon_path, threshold=0.7),
            roi=roi,
            strategy=self.matching_strategy,
            screen=screen,
        ):
            return 2
        return 1

    def _get_condiment_roi(self, order_slot: int, condiment_slot: int) -> List[int]:
        rect = self.ingredient_regions[order_slot]
        width = rect[2] - rect[0]
        quarter = width // 4
        return [
            rect[0] + quarter * condiment_slot,
            rect[1],
            rect[2] - quarter * (3 - condiment_slot),
            rect[3],
        ]
