import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Sequence

import cv2
import numpy as np
from airtest.aircv import crop_image
from airtest.core.api import G, Template

from hawarma.config_loader import Config
from hawarma.models import Order, Recipe
from hawarma.monkey_patches import apply_patch

config = Config.get_config()
apply_patch()


def get_screen(save: bool = config.save_screenshots):
    screenshot = G.DEVICE.snapshot()

    if save:
        cv2.imwrite(f"{config.log_dir} / s_{time.perf_counter()}.jpg", screenshot)  # type: ignore
    return screenshot


@dataclass
class ImageMatcher:
    """Handles all image matching operationns with caching"""

    _template_cache: dict[str, Template] = field(default_factory=dict)

    def get_template(self, image_path: str, **kwargs):
        """Get template with caching"""
        if image_path not in self._template_cache:
            self._template_cache[image_path] = Template(image_path, **kwargs)
        return self._template_cache[image_path]

    def local_match(
        self,
        image_path: str,
        roi: Sequence[int] | None = None,
        strategy: list[str] = config.matching_strategy,
        screen: np.ndarray | None = None,
        save_cropped: bool = False,
        **template_kwargs,
    ):
        """
        Check if a template exists in the specified region of interest.

        Args:
            image_path: Path to the template image
            roi: Region of interest (x1, y1, x2, y2)
            strategy: Matching strategy
            screen: Optional screenshot to use
            save_cropped: Whether to save cropped image for debugging
            template_kwargs: Additional kwargs for Template creation

        Returns:
            Coordinate if match found, None otherwise
        """
        if screen is None:
            screen = get_screen()

        cropped = crop_image(screen, roi) if roi is not None else screen

        if save_cropped:
            cv2.imwrite(f"{config.log_dir} / m_{time.perf_counter()}.jpg", cropped)  # type: ignore

        template = self.get_template(image_path, **template_kwargs)
        return template._cv_match(cropped, strategy)  # type: ignore # monkey patch


class OrderDetector:
    """Handles order detection and validation"""

    def __init__(
        self, recipes: list[Recipe], image_matcher: ImageMatcher = ImageMatcher()
    ) -> None:
        self.recipes: list[Recipe] = recipes
        self.matcher: ImageMatcher = image_matcher

    def detect_recipe(
        self, order_slot: int, screen: np.ndarray | None = None
    ) -> Recipe | None:
        """Validate which recipe is in the order slot by the first ingredient(which is unique)"""
        best_match_recipe, best_match_confidence = None, 0.0
        roi = self._get_ingredient_roi(order_slot, 0)
        for recipe in self.recipes:
            first_ingredient_path = (
                f"{config.image_dir}/ingredient-{recipe.raw_ingredients[0]}.jpg"
            )
            if (
                match_result := self.matcher.local_match(
                    image_path=first_ingredient_path,
                    roi=roi,
                    strategy=config.ingredients_matching_strategy,
                    screen=screen,
                    save_cropped=config.save_best_match_images,
                )
            ) and float(match_result["confidence"]) > best_match_confidence:
                best_match_recipe = recipe
                best_match_confidence = float(match_result["confidence"])
        return best_match_recipe

    def detect_rush_order(self, order_slot, screen):
        return False

    def detect_condiments_preference(self, order_slot, recipe: Recipe, screen):
        condiment_pref = defaultdict(int)
        condiment_candidates = recipe.condiments
        ingredient_slots = [
            0 + len(recipe.raw_ingredients),
            1 + len(recipe.raw_ingredients),
        ]

        for candidate_idx, candidate in enumerate(condiment_candidates):
            condiment_path = f"{config.image_dir}/ingredient-{candidate}.jpg"
            roi = self._get_ingredient_roi(order_slot, ingredient_slots[candidate_idx])
            double_path = f"{config.image_dir}/icon-double.jpg"
            if self.matcher.local_match(
                image_path=condiment_path,
                roi=roi,
                strategy=config.ingredients_matching_strategy,
                screen=screen,
                threshold=config.ingredients_matching_threshold,
            ):
                condiment_pref[candidate] = (
                    2
                    if self.matcher.local_match(
                        image_path=double_path,
                        roi=roi,
                        strategy=config.ingredients_matching_strategy,
                        screen=screen,
                        threshold=config.ingredients_matching_threshold,
                    )
                    else 1
                )
            else:
                if (
                    candidate_idx == 0
                ):  # If first candidate is not found, we assume the second one is the only one
                    condiment_pref[condiment_candidates[0]] = 0
                    condiment_pref[condiment_candidates[1]] = (
                        2
                        if self.matcher.local_match(
                            image_path=double_path,
                            roi=roi,
                            strategy=config.ingredients_matching_strategy,
                            screen=screen,
                            threshold=config.ingredients_matching_threshold,
                        )
                        else 1
                    )
                    break
                else:
                    condiment_pref[candidate] = 0

        return condiment_pref

    def _get_ingredient_roi(self, order_slot, ingredient_slot):
        rect = config.ingredients_potential_regions[order_slot]
        width = rect[2] - rect[0]
        quarter_width = width // 4
        return (
            rect[0] + ingredient_slot * quarter_width,
            rect[1],
            rect[2] - (3 - ingredient_slot) * quarter_width,
            rect[3],
        )

    def detect_order(self, order_slot: int, screen: np.ndarray | None) -> None | Order:
        """Detect and validate an order in a specific slot."""
        validated_recipe = self.detect_recipe(order_slot, screen)
        if validated_recipe is None:
            return None

        is_rush = self.detect_rush_order(order_slot, screen)
        condiments_pref = self.detect_condiments_preference(
            order_slot, validated_recipe, screen
        )

        return Order(validated_recipe, is_rush, condiments_pref)
