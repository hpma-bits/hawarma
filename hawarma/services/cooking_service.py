# hawarma/services/cooking_service.py
import asyncio
import time
from typing import Dict, List, Tuple

from airtest.core.api import swipe
from loguru import logger

from hawarma.models import Order, OrderStage

class CookingService:
    """Handles the physical actions of cooking an order."""

    def __init__(
        self,
        raw_ingredients_mapping: Dict[str, Tuple[int, int]],
        cookers_mapping: Dict[str, Tuple[int, int]],
        condiments_mapping: Dict[str, Tuple[int, int]],
        assembly_station_pos: Tuple[int, int],
        pickup_stations_pos: List[Tuple[int, int]],
    ):
        self.raw_ingredients_mapping = raw_ingredients_mapping
        self.cookers_mapping = cookers_mapping
        self.condiments_mapping = condiments_mapping
        self.assembly_station = assembly_station_pos
        self.pickup_stations = pickup_stations_pos

    async def process_order(self, order: Order, slot: int) -> None:
        """Handle the complete lifecycle of an order."""
        try:
            logger.info(f"Processing order {order.order_id}: {order.recipe.name}")
            
            # Stage 1: Heat ingredients
            order.current_stage = OrderStage.HEATING
            await self._heat_up(order)
            logger.debug(f"Order {order.order_id}: Heated.")

            # Stage 2: Move to assembly
            order.current_stage = OrderStage.OFF_HEAT
            await self._off_heat(order)
            logger.debug(f"Order {order.order_id}: Off heat.")

            # Stage 3: Add condiments
            order.current_stage = OrderStage.SEASONING
            await self._season(order)
            logger.debug(f"Order {order.order_id}: Seasoned.")

            # Stage 4: Serve dish
            order.current_stage = OrderStage.SERVING
            await self._serve_dish(order, slot=slot)
            logger.info(f"Order {order.order_id}: Served from slot {slot}.")

            order.done = True
            order.current_stage = OrderStage.COMPLETED
            order.served_ts = time.time()

        except Exception as e:
            logger.error(f"Error processing order {order.order_id}: {e}")
            order.current_stage = OrderStage.FAILED

    async def _heat_up(self, order: Order):
        recipe = order.recipe
        raw_ingredients = recipe.raw_ingredients
        cookers = recipe.cookers

        # Ensure the ingredient with the longest cooking time starts first
        if len(recipe.cook_durations) == 2 and recipe.cook_durations[0] < recipe.cook_durations[1]:
            raw_ingredients = list(reversed(raw_ingredients))
            cookers = list(reversed(cookers))

        for raw_ingredient, cooker in zip(raw_ingredients, cookers):
            swipe(
                self.raw_ingredients_mapping[raw_ingredient],
                self.cookers_mapping[cooker],
                duration=0.1,
            )
        await asyncio.sleep(max(recipe.cook_durations))

    async def _off_heat(self, order: Order):
        for cooker in order.recipe.cookers:
            swipe(self.cookers_mapping[cooker], self.assembly_station, duration=0.1)
        await asyncio.sleep(0.2)

    async def _season(self, order: Order):
        for condiment, count in order.condiment_preference.items():
            for _ in range(count):
                swipe(self.condiments_mapping[condiment], self.assembly_station, duration=0.1)

    async def _serve_dish(self, order: Order, slot: int):
        swipe(self.assembly_station, self.pickup_stations[slot], duration=0.1)
        
