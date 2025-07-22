# hawarma/app.py
import asyncio
import itertools
from typing import List, Dict, Tuple

from loguru import logger

from hawarma.config import AppConfig, load_config
from hawarma.models import Order, Recipe
from hawarma.services.recipe_manager import RecipeManager
from hawarma.services.detection_service import DetectionService
from hawarma.services.cooking_service import CookingService

class CookingBotApp:
    """The main application class."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.is_running = False
        self.max_slots = 4
        self.order_slots: List[Order | None] = [None] * self.max_slots
        self.completed_orders_count = 0
        
        # These will be initialized in an async context
        self.recipe_manager: RecipeManager
        self.detection_service: DetectionService
        self.cooking_service: CookingService

    def setup(self, ordered_recipes: List[Recipe]):
        """Initialize services and mappings based on selected recipes."""
        logger.info("Setting up application services...")
        
        # Initialize services
        self.detection_service = DetectionService(
            recipes=ordered_recipes,
            config=self.config
        )
        
        # Calculate position mappings
        cookers_mapping = self._get_cookers_positions(ordered_recipes)
        raw_ingredients_mapping = self._get_raw_ingredients_positions(ordered_recipes)
        condiments_mapping = self._get_condiments_positions(ordered_recipes)

        self.cooking_service = CookingService(
            raw_ingredients_mapping=raw_ingredients_mapping,
            cookers_mapping=cookers_mapping,
            condiments_mapping=condiments_mapping,
            assembly_station_pos=self.config.screen.assembly_station_position,
            pickup_stations_pos=self.config.screen.pickup_stations_positions,
        )
        logger.info("Setup complete.")

    async def run(self):
        """Main application loop."""
        self.is_running = True
        logger.info("Gastronomy Helper is running...")
        try:
            while self.is_running:
                await self._scan_and_advance_orders()
                await self._process_order_pipeline()
                await asyncio.sleep(0.1) # Main loop delay
        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.warning("Application run loop interrupted.")
        finally:
            await self.stop()

    async def stop(self):
        """Stops the application and cleans up resources."""
        self.is_running = False
        logger.info("Stopping application...")
        # Cancel any ongoing tasks
        for order in self.order_slots:
            if order and order.processing_task and not order.processing_task.done():
                order.processing_task.cancel()
        await asyncio.sleep(0.5) # Give tasks time to cancel
        logger.info("Application stopped.")

    async def _scan_and_advance_orders(self):
        """Scans for new orders and advances the pipeline if the first is done."""
        # Advance pipeline if first order is complete
        if self.order_slots[0] and self.order_slots[0].done:
            self.completed_orders_count += 1
            logger.info(f"Order in slot 0 completed. Advancing pipeline. Total completed: {self.completed_orders_count}")
            # Shift all orders forward
            for i in range(self.max_slots - 1):
                self.order_slots[i] = self.order_slots[i + 1]
            self.order_slots[-1] = None
            await asyncio.sleep(1.0) # Wait for game animation

        # Scan for new orders in empty slots
        for i in range(self.max_slots):
            if self.order_slots[i] is None:
                if new_order := self.detection_service.detect_order(i):
                    self.order_slots[i] = new_order
                    logger.info(f"New order detected in slot {i}: {new_order}")
                else:
                    # Stop scanning if we find an empty slot, as orders appear sequentially
                    break

    async def _process_order_pipeline(self):
        """Manages the concurrent processing of orders."""
        # Process the first order if it's pending
        if (order := self.order_slots[0]) and not order.processing_task:
            logger.debug(f"Starting processing for order {order.order_id} in slot 0.")
            order.processing_task = asyncio.create_task(
                self.cooking_service.process_order(order, slot=0)
            )

        # Process the second order if the first is far enough along
        if (order1 := self.order_slots[0]) and (order2 := self.order_slots[1]):
            if not order2.processing_task and order1.current_stage in ("OFF_HEAT", "SEASONING"):
                logger.debug(f"Starting processing for order {order2.order_id} in slot 1.")
                order2.processing_task = asyncio.create_task(
                    self.cooking_service.process_order(order2, slot=1)
                )

    def _get_cookers_positions(self, recipes: List[Recipe]) -> Dict[str, Tuple[int, int]]:
        cookers_in_use = list(dict.fromkeys(itertools.chain.from_iterable(r.cookers for r in recipes)))
        count = len(cookers_in_use)
        positions = self.config.screen.cookers_positions
        logger.debug(f"Assigning positions for cookers: {cookers_in_use}")
        return {
            cooker: positions[idx + 1 if count < 3 else idx]
            for idx, cooker in enumerate(cookers_in_use)
        }

    def _get_raw_ingredients_positions(self, recipes: List[Recipe]) -> Dict[str, Tuple[int, int]]:
        ingredients_in_use = list(dict.fromkeys(itertools.chain.from_iterable(r.raw_ingredients for r in recipes)))
        ingredients_in_use.reverse() # Original logic
        positions = self.config.screen.raw_ingredients_positions
        logger.debug(f"Assigning positions for ingredients: {ingredients_in_use}")
        return {
            ingredient: positions[idx]
            for idx, ingredient in enumerate(ingredients_in_use)
        }

    def _get_condiments_positions(self, recipes: List[Recipe]) -> Dict[str, Tuple[int, int]]:
        condiments_in_use = list(dict.fromkeys(itertools.chain.from_iterable(r.condiments for r in recipes)))
        positions = self.config.screen.condiments_positions
        logger.debug(f"Assigning positions for condiments: {condiments_in_use}")
        return {
            condiment: positions[idx]
            for idx, condiment in enumerate(condiments_in_use)
        }
