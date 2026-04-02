"""
Hawarma - 烹饪游戏自动化 Agent

通过图像检测识别订单，使用贪心策略在 90 秒内最大化订单完成数。
"""

import asyncio
import sys
from pathlib import Path

import questionary
from airtest.core.api import init_device, touch
from airtest.core.settings import Settings as ST
from loguru import logger

from hawarma.config import load_config
from hawarma.services.recipe_manager import RecipeManager
from hawarma.monkey_patches import apply_patch
from hawarma.logging_setup import setup_logging


def setup_airtest():
    """Initialize Airtest device and settings."""
    ST.CVSTRATEGY = ["tpl"]
    ST.OPDELAY = 0.05
    ST.THRESHOLD = 0.7
    try:
        logger.info("Connecting to Airtest device...")
        device = init_device(
            platform="Android",
            uuid="127.0.0.1:16384",
            cap_method="minicap",
            touch_method="maxtouch",
        )
        touch((0, 0))
        logger.info("Airtest device connected.")
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


async def run_game(config, ordered_recipes):
    """Run the agent game loop."""
    from hawarma.bridge import RealGameBridge
    from hawarma.agent import CookingAgent

    bridge = RealGameBridge(config, ordered_recipes)
    agent = CookingAgent(bridge.env, ordered_recipes)
    bridge.set_agent(agent)

    logger.info("=" * 60)
    logger.info("Starting game...")
    logger.info(f"Recipes: {[r.name for r in ordered_recipes]}")
    logger.info(f"Cookers: {list(config.cookers)}")
    logger.info("=" * 60)

    stats = await bridge.run()

    logger.info("=" * 60)
    logger.info("Game over!")
    logger.info(f"  Time:        {stats['time']:.1f}s")
    logger.info(f"  Orders done: {stats['orders_served']}")
    logger.info(f"  Score:       {stats['total_score']}")
    logger.info(f"  Timed out:   {stats['orders_timeout']}")
    logger.info(f"  Actions:     {stats['actions_taken']}")
    logger.info("=" * 60)

    return stats


def main():
    """Main entry point."""
    setup_logging()
    apply_patch()
    device = setup_airtest()

    config = load_config()
    recipe_manager = RecipeManager(recipes_path="data/recipes.json")
    all_recipes = recipe_manager.get_all_recipes()

    while True:
        ordered_recipes = get_recipe_selection(all_recipes)
        if not ordered_recipes:
            if questionary.confirm("Exit?").ask():
                break
            continue

        try:
            asyncio.run(run_game(config, ordered_recipes))
        except KeyboardInterrupt:
            logger.info("Interrupted.")
        except Exception as e:
            logger.error(f"Game error: {e}", exc_info=True)

        if not questionary.confirm("Play again with new recipes?").ask():
            break


if __name__ == "__main__":
    main()
