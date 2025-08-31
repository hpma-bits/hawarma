# hawarma/services/cooking_service.py
import asyncio
import time
from typing import Dict, List, Tuple

from airtest.core.api import swipe
from loguru import logger

from hawarma.models import Order, OrderStage


class CookingService:
    """
    Handles the physical actions of cooking an order in the game.

    This service is responsible for translating a recipe's instructions into
    a series of swipe actions to move ingredients, cook them, add condiments,
    and serve the final dish.
    """

    def __init__(
        self,
        raw_ingredients_mapping: Dict[str, Tuple[int, int]],
        cookers_mapping: Dict[str, Tuple[int, int]],
        condiments_mapping: Dict[str, Tuple[int, int]],
        assembly_station_pos: Tuple[int, int],
        pickup_stations_pos: List[Tuple[int, int]],
    ):
        """
        Initializes the CookingService.

        Args:
            raw_ingredients_mapping: A dictionary mapping raw ingredient names to their screen positions.
            cookers_mapping: A dictionary mapping cooker names to their screen positions.
            condiments_mapping: A dictionary mapping condiment names to their screen positions.
            assembly_station_pos: The screen position of the assembly station.
            pickup_stations_pos: A list of screen positions for the pickup stations.
        """
        self.raw_ingredients_mapping = raw_ingredients_mapping
        self.cookers_mapping = cookers_mapping
        self.condiments_mapping = condiments_mapping
        self.assembly_station = assembly_station_pos
        self.pickup_stations = pickup_stations_pos

    async def process_order(self, order: Order, slot: int) -> None:
        """
        Processes the complete lifecycle of a cooking order.

        This method orchestrates the entire cooking process for a given order,
        optimizing the workflow by moving ingredients to assembly as soon as they're
        cooked and allowing the next order to start once ingredients are assembled.

        Args:
            order: The order to be processed.
            slot: The order slot index, used to determine the serving position.
        """
        try:
            logger.info(
                f"Starting to process order {order.order_id}: {order.recipe.name}"
            )

            # Start cooking and move ingredients as they finish
            order.current_stage = OrderStage.HEATING
            await self._heat_and_move(order)
            await asyncio.sleep(0.1)

            # Season and serve
            order.current_stage = OrderStage.SEASONING
            await self._season(order)
            logger.debug(f"Order {order.order_id}: Dish has been seasoned.")
            # await asyncio.sleep(0.5)

            order.current_stage = OrderStage.SERVING
            await self._serve_dish(order, slot=0)
            logger.info(f"Order {order.order_id}: Successfully served.")

            order.done = True
            order.current_stage = OrderStage.COMPLETED
            order.served_ts = asyncio.get_event_loop().time()

        except Exception as e:
            logger.error(
                f"An error occurred while processing order {order.order_id}: {e}"
            )
            order.current_stage = OrderStage.FAILED

    async def _start_cooking(self, order: Order) -> List[Tuple[str, float]]:
        """
        Places raw ingredients on cookers and returns a list of (cooker, cook_time) pairs.
        """
        recipe = order.recipe
        raw_ingredients = recipe.raw_ingredients
        cookers = recipe.cookers
        cook_durations = recipe.cook_durations

        # Sort ingredients by cooking time (longest first) to optimize cooking
        cook_info = list(zip(raw_ingredients, cookers, cook_durations))
        cook_info.sort(key=lambda x: x[2], reverse=True)

        cooking_schedule = []
        for raw_ingredient, cooker, duration in cook_info:
            swipe(
                self.raw_ingredients_mapping[raw_ingredient],
                self.cookers_mapping[cooker],
                duration=0.1,
            )
            cooking_schedule.append((cooker, duration))

        return cooking_schedule

    async def _heat_and_move(self, order: Order):
        """Manages the cooking process and moves ingredients to assembly as they finish."""
        cooking_schedule = await self._start_cooking(order)

        # Track when each ingredient started cooking
        start_time = time.time()
        idle_cookers = set()

        while len(idle_cookers) < len(cooking_schedule):
            current_time = time.time()
            elapsed = current_time - start_time
            outstanding_time = 1

            # Check each ingredient and move if it's done
            for cooker, duration in cooking_schedule:
                if cooker not in idle_cookers and elapsed >= duration:
                    order.current_stage = OrderStage.OFF_HEAT
                    swipe(
                        self.cookers_mapping[cooker],
                        self.assembly_station,
                        duration=0.1,
                    )
                    idle_cookers.add(cooker)
                    logger.debug(f"Moved cooked ingredient from {cooker} to assembly")
                elif (remaining_time := duration - elapsed) < 1:
                    outstanding_time = min(outstanding_time, remaining_time)

            await asyncio.sleep(outstanding_time)

        # Mark as ready for next order once ingredients are at assembly
        order.current_stage = OrderStage.READY_TO_SEASON
        logger.debug(f"Order {order.order_id}: All ingredients at assembly station")

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
        swipe(self.assembly_station, self.pickup_stations[slot], duration=0.15)
        # swipe(self.assembly_station, self.pickup_stations[slot], duration=0.15)
