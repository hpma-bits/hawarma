# hawarma/services/cooking_service.py
import asyncio
from collections import defaultdict
from typing import Dict, List, Tuple

from airtest.core.api import swipe
from loguru import logger

from hawarma.models import Order, Recipe


class CookingService:
    """
    Handles the physical actions of cooking, stockpiling, and serving in the game.
    This service translates recipes into swipe actions, manages cooker contention,
    and interacts with both the assembly station and prep areas.
    """

    def __init__(
        self,
        raw_ingredients_mapping: Dict[str, Tuple[int, int]],
        cookers_mapping: Dict[str, Tuple[int, int]],
        condiments_mapping: Dict[str, Tuple[int, int]],
        assembly_station_pos: Tuple[int, int],
        pickup_stations_pos: List[Tuple[int, int]],
        prep_area_positions: List[Tuple[int, int]],
    ):
        """
        Initializes the CookingService.
        """
        self.raw_ingredients_mapping = raw_ingredients_mapping
        self.cookers_mapping = cookers_mapping
        self.condiments_mapping = condiments_mapping
        self.assembly_station = assembly_station_pos
        self.pickup_stations = pickup_stations_pos
        self.prep_area_positions = prep_area_positions

        # Initialize locks for thread-safe access
        self.cooker_locks = {
            name: asyncio.Lock() for name in self.cookers_mapping.keys()
        }
        self.assembly_lock = asyncio.Lock()  # Lock for assembly station access
        self.stockpile_locks = {
            i: asyncio.Lock() for i in range(len(prep_area_positions))
        }  # Locks for each prep area

    async def prepare_ingredients(
        self,
        recipe: Recipe,
        destination: Tuple[int, int],
        ingredient_name_to_cook: str | None = None,
    ) -> None:
        """
        Prepares ingredients for a recipe and moves them to a destination.

        If `ingredient_name_to_cook` is specified, it only cooks that single
        ingredient. Otherwise, it cooks all raw ingredients in the recipe.
        This method intelligently handles cooker contention.
        """
        cooker_schedule = defaultdict(list)
        ingredients_to_process = (
            [ingredient_name_to_cook]
            if ingredient_name_to_cook
            else recipe.raw_ingredients
        )

        # Group ingredients by the cooker they require
        for i, ingredient_name in enumerate(recipe.raw_ingredients):
            if ingredient_name in ingredients_to_process:
                ingredient_info = {
                    "name": ingredient_name,
                    "duration": recipe.cook_durations[i],
                }
                cooker_schedule[recipe.cookers[i]].append(ingredient_info)

        preparation_tasks = []
        for cooker_name, ingredients in cooker_schedule.items():
            task = self._cook_on_single_cooker(cooker_name, ingredients, destination)
            preparation_tasks.append(task)

        await asyncio.gather(*preparation_tasks)
        log_msg = (
            f"Ingredient {ingredient_name_to_cook} is prepared."
            if ingredient_name_to_cook
            else f"All ingredients for recipe {recipe.name} are prepared."
        )
        logger.info(log_msg)

    async def _cook_on_single_cooker(
        self,
        cooker_name: str,
        ingredients: List[Dict],
        destination: Tuple[int, int],
    ):
        """
        Cooks a sequence of ingredients on a single cooker.
        Uses async lock to ensure exclusive access to the cooker.
        """
        cooker_pos = self.cookers_mapping[cooker_name]

        async with self.cooker_locks[cooker_name]:
            logger.debug(f"Acquired lock for cooker '{cooker_name}'")

            for ingredient in ingredients:
                ingredient_name = ingredient["name"]
                duration = ingredient["duration"]
                raw_ingredient_pos = self.raw_ingredients_mapping[ingredient_name]

                # Start cooking
                logger.debug(
                    f"Cooking {ingredient_name} on {cooker_name} for {duration}s."
                )
                swipe(raw_ingredient_pos, cooker_pos, duration=0.1)
                await asyncio.sleep(duration)

                # Move to destination (with assembly lock if needed)
                logger.debug(
                    f"Moving cooked {ingredient_name} from {cooker_name} to {destination}."
                )
                if destination == self.assembly_station:
                    async with self.assembly_lock:
                        swipe(cooker_pos, destination, duration=0.1)
                        await asyncio.sleep(0.1)  # Small delay for game animation
                else:
                    swipe(cooker_pos, destination, duration=0.1)
                    await asyncio.sleep(0.1)  # Small delay for game animation

            logger.debug(f"Released lock for cooker '{cooker_name}'")

    async def finish_order(self, order: Order, slot: int) -> None:
        """
        Finishes a prepared order by seasoning and serving it.
        Uses assembly lock to ensure exclusive access during finishing.
        """
        try:
            async with self.assembly_lock:
                await self._season(order)
                logger.debug(f"Order {order.order_id}: Dish has been seasoned.")

                await self._serve_dish(order, slot)
                logger.info(f"Order {order.order_id}: Successfully served.")

            order.done = True
            order.served_ts = asyncio.get_event_loop().time()
        except Exception as e:
            logger.error(
                f"An error occurred while finishing order {order.order_id}: {e}"
            )

    async def use_stocked_ingredient(
        self, prep_area_index: int, destination: Tuple[int, int]
    ):
        """
        Moves a stocked ingredient from a prep area to a destination.
        Uses both prep area and assembly station locks to prevent conflicts.
        """
        async with self.stockpile_locks[prep_area_index]:
            prep_area_pos = self.prep_area_positions[prep_area_index]
            logger.debug(f"Using stocked ingredient from prep area {prep_area_index}.")

            # If moving to assembly station, acquire its lock
            if destination == self.assembly_station:
                async with self.assembly_lock:
                    swipe(prep_area_pos, destination, duration=0.1)
                    await asyncio.sleep(0.1)
            else:
                swipe(prep_area_pos, destination, duration=0.1)
                await asyncio.sleep(0.1)

    async def _season(self, order: Order):
        """Adds the required condiments to the dish."""
        for condiment, count in order.condiment_preference.items():
            for _ in range(count):
                swipe(
                    self.condiments_mapping[condiment],
                    self.assembly_station,
                    duration=0.1,
                )

    async def _serve_dish(self, order: Order, slot: int):
        """Serves the completed dish to the customer."""
        swipe(self.assembly_station, self.pickup_stations[slot], duration=0.2)
