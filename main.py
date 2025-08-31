# main.py
import asyncio

import questionary
from airtest.core.api import init_device, touch
from airtest.core.settings import Settings as ST
from loguru import logger

from hawarma.app import CookingBotApp
from hawarma.config import load_config
from hawarma.services.recipe_manager import RecipeManager
from hawarma.monkey_patches import apply_patch
from hawarma.logging_setup import setup_logging


def setup_airtest():
    """Initializes Airtest device and settings."""
    ST.CVSTRATEGY = ["tpl"]
    ST.OPDELAY = 0.05
    ST.THRESHOLD = 0.7
    try:
        logger.info("Attempting to connect to Airtest device...")
        device = init_device(
            platform="Android",
            uuid="127.0.0.1:16384",  # mumu
            cap_method="minicap",
            touch_method="maxtouch",
        )
        touch((0, 0))  # Wake up screen
        logger.info("Airtest device initialized.")
        return device

    except Exception as e:
        logger.error(f"Failed to initialize Airtest device: {e}")
        raise


def get_recipe_selection(all_recipes):
    """Get user input for recipe selection and ordering."""
    selected_names = questionary.checkbox(
        "Select recipes to use:", choices=[r.name for r in all_recipes]
    ).ask()

    if not selected_names:
        logger.warning("No recipes selected.")
        return None

    selected_recipes = [r for r in all_recipes if r.name in selected_names]

    order_input = questionary.text(
        f"Specify preparation order for {len(selected_recipes)} recipes (e.g., '012'):"
    ).ask()

    ordered_recipes = selected_recipes
    if (
        order_input
        and all(c.isdigit() for c in order_input)
        and len(order_input) == len(selected_recipes)
    ):
        try:
            ordered_recipes = [selected_recipes[int(idx)] for idx in list(order_input)]
        except IndexError:
            logger.error("Invalid order index. Using default order.")

    return ordered_recipes


def main():
    """Main application entry point."""
    # Setup environment
    setup_logging(log_level="DEBUG")
    device = setup_airtest()
    apply_patch()

    # Load configuration and data
    config = load_config()
    recipe_manager = RecipeManager(recipes_path="data/recipes.json")
    all_recipes = recipe_manager.get_all_recipes()

    while True:
        # Get recipe selection from user
        ordered_recipes = get_recipe_selection(all_recipes)
        if not ordered_recipes:
            if questionary.confirm("Would you like to exit?").ask():
                break
            continue

        # Initialize and run the application
        app = CookingBotApp(config)
        app.setup(ordered_recipes=ordered_recipes)

        try:
            asyncio.run(app.run())
        except KeyboardInterrupt:
            logger.info("Application paused. Press Ctrl+C again to exit completely.")
            try:
                # Allow time to press Ctrl+C again if user wants to exit
                asyncio.run(asyncio.sleep(1))
            except KeyboardInterrupt:
                logger.info("Application terminated by user.")
                break

            # Ask if user wants to continue with new recipes
            if not questionary.confirm(
                "Would you like to continue with new recipes?"
            ).ask():
                break


if __name__ == "__main__":
    main()
