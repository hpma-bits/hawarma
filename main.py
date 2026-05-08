"""
Hawarma - 烹饪游戏自动化 Agent

通过图像检测识别订单，使用贪心策略在 90 秒内最大化订单完成数。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import questionary
from loguru import logger

from hawarma.config import load_config
from hawarma.services.recipe_manager import RecipeManager
from hawarma.patches import apply_patch
from hawarma.log import setup_logging
from hawarma.device import setup_device


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


async def run_game(config, ordered_recipes, strategy=None):
    """Run the agent game loop.

    Args:
        config: AppConfig instance
        ordered_recipes: List of selected Recipe objects
        strategy: Optional strategy instance to use. Defaults to config.strategy.
    """
    from hawarma.game import Runner
    from hawarma.agent.registry import get_strategy

    # 使用配置中的策略，可通过参数覆盖
    if strategy is None:
        strategy = get_strategy(config.strategy)

    bridge = Runner(config, ordered_recipes, strategy)

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
    import argparse

    parser = argparse.ArgumentParser(description="Hawarma - Cooking Game Agent")
    parser.add_argument(
        "--strategy",
        type=str,
        default=None,
        help="Strategy name (default, cpm, preempt_score, visibility_aware)",
    )
    args = parser.parse_args()

    setup_logging()

    config = load_config()
    setup_device(config.adb_address)
    apply_patch()

    # 命令行参数可覆盖配置文件中的策略
    if args.strategy:
        from hawarma.agent.registry import get_strategy
        strategy = get_strategy(args.strategy)
        logger.info(f"Using strategy from CLI: {args.strategy}")
    else:
        strategy = None
        logger.info(f"Using strategy from config: {config.strategy}")

    recipe_manager = RecipeManager(recipes_path="data/recipes.json")
    all_recipes = recipe_manager.get_all_recipes()

    while True:
        ordered_recipes = get_recipe_selection(all_recipes)
        if not ordered_recipes:
            if questionary.confirm("Exit?").ask():
                break
            continue

        try:
            asyncio.run(run_game(config, ordered_recipes, strategy=strategy))
        except KeyboardInterrupt:
            logger.info("Interrupted.")
        except Exception as e:
            logger.error(f"Game error: {e}", exc_info=True)

        if not questionary.confirm("Play again with new recipes?").ask():
            break


if __name__ == "__main__":
    main()
