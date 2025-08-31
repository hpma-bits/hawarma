# hawarma/app.py
import asyncio
import itertools
from typing import Dict, List, Tuple

from loguru import logger

from hawarma.config import AppConfig
from hawarma.models import Order, OrderStage, Recipe
from hawarma.services.cooking_service import CookingService
from hawarma.services.detection_service import DetectionService
from hawarma.services.recipe_manager import RecipeManager


class CookingBotApp:
    """
    The main application class for the Cooking Bot.

    This class orchestrates the entire cooking process, from detecting orders
    to managing the cooking pipeline and interacting with the game.
    """

    def __init__(self, config: AppConfig):
        """
        Initializes the CookingBotApp.

        Args:
            config: The application configuration.
        """
        self.config = config
        self.is_running = False
        self.max_slots = 4
        self.order_slots: List[Order | None] = [None] * self.max_slots
        self.completed_orders_count = 0
        self.last_order_completion_time = 0.0  # Track when last order was completed
        self.scan_task = None  # Background task for scanning orders

        # Services are initialized in the setup method
        self.recipe_manager: RecipeManager
        self.detection_service: DetectionService
        self.cooking_service: CookingService

    def setup(self, ordered_recipes: List[Recipe]):
        """
        Initializes and sets up the application's services.

        This method prepares the detection and cooking services based on the
        recipes that will be used in the current session.

        Args:
            ordered_recipes: A list of recipes to be used.
        """
        logger.info("Setting up application services...")

        self.detection_service = DetectionService(
            recipes=ordered_recipes, config=self.config
        )

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
        logger.info("Application setup complete.")

    async def run(self):
        """
        The main application loop.

        This loop continuously processes orders and manages the cooking pipeline
        until the application is stopped. Order scanning runs as a background task.
        """
        self.is_running = True
        logger.info("Cooking Bot is running. Press Ctrl+C to stop.")
        try:
            # Start the background order scanning task
            self.scan_task = asyncio.create_task(self._scan_for_new_orders())

            while self.is_running:
                self._advance_completed_orders()
                await self._process_order_pipeline()
                await asyncio.sleep(0.1)

        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.warning("Application run loop interrupted.")
        finally:
            if self.scan_task:
                self.scan_task.cancel()
            await self.stop()

    async def stop(self):
        """
        Stops the application and cleans up resources.
        """
        self.is_running = False
        logger.info("Stopping the Cooking Bot...")
        for order in self.order_slots:
            if order and order.processing_task and not order.processing_task.done():
                order.processing_task.cancel()
        await asyncio.sleep(0.5)
        logger.info("Cooking Bot has been stopped.")

    def _advance_completed_orders(self):
        """
        Checks if the first order is completed and advances the pipeline.
        """
        if self.order_slots[0] and self.order_slots[0].done:
            self.completed_orders_count += 1
            logger.info(
                f"Order in slot 0 is complete. Advancing pipeline. "
                f"Total completed: {self.completed_orders_count}"
            )
            # Update the completion time when an order is completed
            self.last_order_completion_time = asyncio.get_event_loop().time()
            self.order_slots.pop(0)
            self.order_slots.append(None)

    async def _scan_for_new_orders(self):
        """
        Continuously scans for new orders in the background.

        This method runs as a background task, periodically checking for empty
        order slots and using the detection service to find new orders.
        The blocking detection call is run in a separate thread to avoid
        blocking the main asyncio event loop.
        """
        while self.is_running:
            # Wait for screen to update if an order was recently completed
            if any(self.order_slots):
                elapsed = (
                    asyncio.get_event_loop().time() - self.last_order_completion_time
                )
                if (
                    elapsed < 1.0
                ):  # Wait if less than 1 second has passed since last completion
                    await asyncio.sleep(1.0 - elapsed)

            for i in range(
                2
            ):  # Only scan the first two slots for new orders rather than self.max_slots
                if self.order_slots[i] is None:
                    # Run the blocking detection call in a separate thread
                    new_order = await asyncio.to_thread(
                        self.detection_service.detect_order, i
                    )
                    if new_order:
                        self.order_slots[i] = new_order
                        logger.info(f"New order detected in slot {i}: {new_order}")
                    else:
                        break  # Stop scanning after the first empty slot
            await asyncio.sleep(0.2)  # Wait a bit before the next scan cycle

    async def _process_order_pipeline(self):
        """
        Manages the concurrent processing of orders in the pipeline.
        Starts second order as soon as first order's ingredients are at assembly.
        """
        # Start first order if not started
        if (order := self.order_slots[0]) and not order.processing_task:
            logger.debug(f"Starting processing for order {order.order_id} in slot 0.")
            order.processing_task = asyncio.create_task(
                self.cooking_service.process_order(order, slot=0)
            )
            await asyncio.sleep(0.1)

        # Start second order when first order has ingredients at assembly
        if (order1 := self.order_slots[0]) and (order2 := self.order_slots[1]):
            if (
                not order2.processing_task
                and order1.current_stage == OrderStage.READY_TO_SEASON
            ):
                logger.debug(
                    f"Starting processing for order {order2.order_id} in slot 1. "
                    f"First order stage: {order1.current_stage}"
                )
                order2.processing_task = asyncio.create_task(
                    self.cooking_service.process_order(order2, slot=1)
                )

    def _get_cookers_positions(
        self, recipes: List[Recipe]
    ) -> Dict[str, Tuple[int, int]]:
        """
        Calculates the positions of the cookers based on the selected recipes.
        """
        cookers_in_use = list(
            dict.fromkeys(
                itertools.chain.from_iterable(r.cookers_layout for r in recipes)
            )
        )
        count = len(cookers_in_use)
        positions = self.config.screen.cookers_positions
        logger.debug(f"Assigning positions for cookers: {cookers_in_use}")
        return {
            cooker: positions[idx + 1 if count < 3 else idx]
            for idx, cooker in enumerate(cookers_in_use)
        }

    def _get_raw_ingredients_positions(
        self, recipes: List[Recipe]
    ) -> Dict[str, Tuple[int, int]]:
        """
        Calculates the positions of raw ingredients based on the selected recipes.
        """
        ingredients_in_use = list(
            dict.fromkeys(
                itertools.chain.from_iterable(r.raw_ingredients for r in recipes)
            )
        )
        ingredients_in_use.reverse()
        positions = self.config.screen.raw_ingredients_positions
        logger.debug(f"Assigning positions for ingredients: {ingredients_in_use}")
        return {
            ingredient: positions[idx]
            for idx, ingredient in enumerate(ingredients_in_use)
        }

    def _get_condiments_positions(
        self, recipes: List[Recipe]
    ) -> Dict[str, Tuple[int, int]]:
        """
        Calculates the positions of condiments based on the selected recipes.
        """
        condiments_in_use = list(
            dict.fromkeys(itertools.chain.from_iterable(r.condiments for r in recipes))
        )
        positions = self.config.screen.condiments_positions
        logger.debug(f"Assigning positions for condiments: {condiments_in_use}")
        return {
            condiment: positions[idx] for idx, condiment in enumerate(condiments_in_use)
        }
