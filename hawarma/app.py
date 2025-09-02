# hawarma/app.py
import asyncio
import itertools
from collections import Counter
from typing import Dict, List, Tuple

from loguru import logger

from hawarma.config import AppConfig
from hawarma.models import Order, OrderStage, Recipe
from hawarma.services.cooking_service import CookingService
from hawarma.services.detection_service import DetectionService


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

        # Background tasks
        self.scan_task = None
        self.stockpile_task = None

        # Stockpiling state
        self.prep_area_assignments: Dict[
            str, str
        ] = {}  # Maps prep area index to ingredient name
        self.ingredient_stock_counts: Dict[str, int] = Counter()

        # Services are initialized in the setup method
        self.ordered_recipes: List[Recipe] = []
        self.detection_service: DetectionService
        self.cooking_service: CookingService

    def setup(self, ordered_recipes: List[Recipe]):
        """
        Initializes and sets up the application's services and stockpiling strategy.
        This method prepares the detection and cooking services based on the
        recipes that will be used in the current session.
        Args:
            ordered_recipes: A list of recipes to be used.
        """
        logger.info("Setting up application services...")

        # Store ordered recipes for use in stockpiling
        self.ordered_recipes = ordered_recipes

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
            prep_area_positions=self.config.screen.prep_area_positions,
        )

        # Determine and set up the stockpiling strategy for the current session
        self._assign_ingredients_to_prep_areas(ordered_recipes)

        logger.info("Application setup complete.")

    def _assign_ingredients_to_prep_areas(self, recipes: List[Recipe]):
        """
        Analyzes recipes to determine the most strategic ingredients to stockpile.
        It prioritizes ingredients based on frequency, cooker contention, and cook time.
        """
        ingredient_scores = Counter()
        all_raw_ingredients = [ing for r in recipes for ing in r.raw_ingredients]
        cooker_usage = Counter(
            itertools.chain.from_iterable(r.cookers for r in recipes)
        )

        # Score each unique ingredient
        for ingredient in set(all_raw_ingredients):
            score = 0
            for recipe in recipes:
                if ingredient in recipe.raw_ingredients:
                    # 1. Score by frequency
                    score += all_raw_ingredients.count(ingredient)

                    idx = recipe.raw_ingredients.index(ingredient)
                    cooker = recipe.cookers[idx]
                    duration = recipe.cook_durations[idx]

                    # 2. Score by cooker contention (higher score for more used cookers)
                    score += cooker_usage[cooker] * 0.5

                    # 3. Score by cook time (higher score for longer cooking times)
                    score += duration * 0.2

            ingredient_scores[ingredient] = score

        # Assign the top 3 ingredients to the prep areas
        top_ingredients = [ing for ing, _ in ingredient_scores.most_common(3)]
        self.prep_area_assignments = {
            f"prep_area_{i}": name for i, name in enumerate(top_ingredients)
        }
        logger.info(f"Prep area assignments: {self.prep_area_assignments}")

    async def run(self):
        """
        The main application loop.
        This loop continuously processes orders and manages the cooking pipeline
        until the application is stopped. Order scanning runs as a background task.
        """
        self.is_running = True
        logger.info("Cooking Bot is running. Press Ctrl+C to stop.")
        try:
            # Start background tasks
            self.scan_task = asyncio.create_task(self._scan_for_new_orders())
            self.stockpile_task = asyncio.create_task(self._manage_stockpile_task())

            while self.is_running:
                self._advance_completed_orders()
                await self._process_order_pipeline()
                await asyncio.sleep(0.1)

        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.warning("Application run loop interrupted.")
        finally:
            if self.scan_task:
                self.scan_task.cancel()
            if self.stockpile_task:
                self.stockpile_task.cancel()
            await self.stop()

    async def stop(self):
        """
        Stops the application and cleans up resources.
        """
        self.is_running = False
        logger.info("Stopping the Cooking Bot...")
        for order in self.order_slots:
            if order:
                if order.ingredient_prep_task and not order.ingredient_prep_task.done():
                    order.ingredient_prep_task.cancel()
                if order.finish_order_task and not order.finish_order_task.done():
                    order.finish_order_task.cancel()
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
        Ensures proper timing between order completion and new scans.
        """
        while self.is_running:
            # Wait for screen update after order completion
            elapsed = asyncio.get_event_loop().time() - self.last_order_completion_time
            if elapsed < 1.0:  # Ensure 1 second wait after order completion
                logger.debug("Waiting for order list update...")
                await asyncio.sleep(1.0 - elapsed)
                continue

            # Only scan if we have empty slots in the first two positions
            empty_slots = [i for i in range(2) if self.order_slots[i] is None]
            if empty_slots:
                for slot_idx in empty_slots:
                    new_order = await asyncio.to_thread(
                        self.detection_service.detect_order, slot_idx
                    )
                    if new_order:
                        self.order_slots[slot_idx] = new_order
                        logger.info(
                            f"New order detected in slot {slot_idx}: {new_order}"
                        )
                        # Reset completion time to prevent immediate re-scan
                        self.last_order_completion_time = (
                            asyncio.get_event_loop().time()
                        )
                    else:
                        break  # Stop if no order found in current slot

            # Dynamic sleep time based on slot status
            await asyncio.sleep(0.2 if None in self.order_slots[:2] else 0.5)

    async def _manage_stockpile_task(self):
        """
        Proactively cooks and stockpiles strategic ingredients.
        This task runs in the background with lower priority than order processing.
        """
        while self.is_running:
            # Check if we have pending or processing orders
            has_active_orders = any(
                order is not None and not order.done for order in self.order_slots[:2]
            )

            # If we have active orders, wait longer before checking again
            if has_active_orders:
                logger.debug("Active orders detected, pausing stockpile operations")
                await asyncio.sleep(2.0)
                continue

            for (
                prep_area_idx_str,
                ingredient_name,
            ) in self.prep_area_assignments.items():
                # Check again for new orders before each stockpile attempt
                if any(
                    order is not None and not order.done
                    for order in self.order_slots[:2]
                ):
                    logger.debug(
                        "New orders detected, interrupting stockpile operations"
                    )
                    break

                prep_area_idx = int(prep_area_idx_str.split("_")[-1])
                # If stock is below target, try to cook more
                if self.ingredient_stock_counts[ingredient_name] < 5:
                    # Find a recipe from user-selected recipes that can produce this ingredient
                    recipe_for_ingredient = next(
                        (
                            r
                            for r in self.ordered_recipes
                            if ingredient_name in r.raw_ingredients
                        ),
                        None,
                    )
                    if not recipe_for_ingredient:
                        logger.debug(
                            f"No recipe found for stockpiling {ingredient_name}"
                        )
                        continue

                    # Get the cooker index and duration for this ingredient
                    try:
                        ing_idx = recipe_for_ingredient.raw_ingredients.index(
                            ingredient_name
                        )
                        required_cooker = recipe_for_ingredient.cookers[ing_idx]
                        cook_duration = recipe_for_ingredient.cook_durations[ing_idx]

                        # Skip long-cooking ingredients for stockpiling
                        if (
                            cook_duration > 5.0
                        ):  # Skip ingredients that take too long to cook
                            logger.debug(
                                f"Skipping stockpile of {ingredient_name}: cook time {cook_duration}s too long"
                            )
                            continue
                    except (ValueError, IndexError) as e:
                        logger.error(f"Error finding cooker for {ingredient_name}: {e}")
                        continue
                    cooker_lock = self.cooking_service.cooker_locks[required_cooker]

                    if (
                        not cooker_lock.locked()
                    ):  # Non-blocking check for cooker availability
                        logger.info(
                            f"Cooker '{required_cooker}' is available. "
                            f"Attempting to stockpile {ingredient_name}."
                        )
                        # Create a task that awaits completion before incrementing the count
                        asyncio.create_task(
                            self._cook_and_update_stock(
                                recipe_for_ingredient,
                                ingredient_name,
                                self.config.screen.prep_area_positions[prep_area_idx],
                            )
                        )

            await asyncio.sleep(1)  # Check every second

    async def _cook_and_update_stock(
        self, recipe: Recipe, ingredient_name: str, destination: Tuple[int, int]
    ):
        """Helper to cook a single ingredient and update stock count upon completion."""
        await self.cooking_service.prepare_ingredients(
            recipe, destination, ingredient_name_to_cook=ingredient_name
        )
        self.ingredient_stock_counts[ingredient_name] += 1
        logger.info(
            f"Successfully stockpiled {ingredient_name}. "
            f"New count: {self.ingredient_stock_counts[ingredient_name]}"
        )

    async def _process_order_pipeline(self):
        """
        Manages the intelligent, concurrent processing of orders.
        - Fulfills orders using a hybrid of stocked and freshly cooked ingredients.
        - Starts finishing the current order in parallel with preparing the next.
        """
        # Stage 1: Start ingredient preparation for any new order in an open slot
        for i, order in enumerate(self.order_slots):
            if order and not order.ingredient_prep_task:
                # Only start if the previous slot is ready for its finishing task
                if i == 0 or (
                    self.order_slots[i - 1]
                    and self.order_slots[i - 1].current_stage
                    == OrderStage.READY_TO_SEASON
                ):
                    logger.info(f"Starting ingredient prep for order {order.order_id}.")
                    order.ingredient_prep_task = asyncio.create_task(
                        self._gather_ingredients_for_order(order)
                    )

        # Stage 2: Start the finishing task for orders with all ingredients assembled
        for i, order in enumerate(self.order_slots):
            if (
                order
                and order.current_stage == OrderStage.READY_TO_SEASON
                and not order.finish_order_task
            ):
                logger.info(f"Starting finishing task for order {order.order_id}.")
                order.finish_order_task = asyncio.create_task(
                    self.cooking_service.finish_order(order, slot=i)
                )

    async def _gather_ingredients_for_order(self, order: Order):
        """
        Gathers all necessary ingredients for an order, using stock first,
        and cooking only the specific missing ingredients.
        """
        order.current_stage = OrderStage.HEATING
        required_ingredients = Counter(order.recipe.raw_ingredients)
        tasks = []

        for ingredient, count in required_ingredients.items():
            for _ in range(count):
                if self.ingredient_stock_counts[ingredient] > 0:
                    # Use a stocked ingredient
                    logger.debug(
                        f"Using stocked {ingredient} for order {order.order_id}"
                    )
                    prep_area_idx = list(self.prep_area_assignments.values()).index(
                        ingredient
                    )
                    tasks.append(
                        self.cooking_service.use_stocked_ingredient(
                            prep_area_idx, self.config.screen.assembly_station_position
                        )
                    )
                    self.ingredient_stock_counts[ingredient] -= 1
                else:
                    # Cook the specific ingredient from scratch
                    logger.debug(
                        f"Cooking {ingredient} from scratch for order {order.order_id}"
                    )
                    tasks.append(
                        self.cooking_service.prepare_ingredients(
                            order.recipe,
                            self.config.screen.assembly_station_position,
                            ingredient_name_to_cook=ingredient,
                        )
                    )

        await asyncio.gather(*tasks)
        order.current_stage = OrderStage.READY_TO_SEASON
        logger.info(
            f"All ingredients for order {order.order_id} are at the assembly station."
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
