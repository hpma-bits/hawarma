# main.py
import asyncio
from logging import getLogger

import questionary
from airtest.core.api import init_device, touch
from airtest.core.settings import Settings as ST
from loguru import logger

from hawarma.app import CookingBotApp
from hawarma.config import load_config
from hawarma.services.recipe_manager import RecipeManager
from hawarma.monkey_patches import apply_patch


def setup_logging():
    """Configures Loguru logger."""
    logger.remove()
    logger.add(
        "app.log",
        enqueue=True,
        rotation="10 MB",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )
    # Configure airtest logger to be less verbose if needed
    airtest_logger = getLogger("airtest")
    airtest_logger.setLevel("WARNING")
    logger.info("Logging configured.")


def setup_airtest():
    """Initializes Airtest device and settings."""
    ST.CVSTRATEGY = ["tpl"]
    ST.OPDELAY = 0.05
    ST.THRESHOLD = 0.7
    try:
        logger.info("Attempting to connect to Airtest device...")
        init_device(
            platform="Android",
            uuid="127.0.0.1:16384",  # mumu
            cap_method="javacap",
            touch_method="maxtouch",
        )
        touch((0, 0))  # Wake up screen
        logger.info("Airtest device initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize Airtest device: {e}")
        raise


def main():
    """Main application entry point."""
    # 1. Setup environment
    setup_logging()
    setup_airtest()
    apply_patch()

    # 2. Load configuration and data
    config = load_config()
    recipe_manager = RecipeManager(recipes_path="data/recipes.json")
    all_recipes = recipe_manager.get_all_recipes()

    # 3. Get user input for recipe selection and order (HARDCODED FOR TESTING)
    logger.warning("Using hardcoded recipe selection for non-interactive mode.")
    selected_recipes = all_recipes[:1]
    ordered_recipes = selected_recipes
    # selected_names = questionary.checkbox(
    #     "Select recipes to use:", choices=[r.name for r in all_recipes]
    # ).ask()

    # if not selected_names:
    #     logger.warning("No recipes selected. Exiting.")
    #     return

    # selected_recipes = [r for r in all_recipes if r.name in selected_names]

    # order_input = questionary.text(
    #     f"Specify preparation order for {len(selected_recipes)} recipes (e.g., '012'):"
    # ).ask()

    # ordered_recipes = selected_recipes
    # if order_input and all(c.isdigit() for c in order_input) and len(order_input) == len(selected_recipes):
    #     try:
    #         ordered_recipes = [selected_recipes[int(idx)] for idx in list(order_input)]
    #     except IndexError:
    #         logger.error("Invalid order index. Using default order.")

    # 4. Initialize and run the application
    app = CookingBotApp(config)
    app.setup(ordered_recipes=ordered_recipes)

    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("Application terminated by user.")


if __name__ == "__main__":
    main()
