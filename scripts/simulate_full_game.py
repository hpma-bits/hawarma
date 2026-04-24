"""
Run a full game simulation with CookingAgent against GameSimulator.

Shows detailed action-by-action log similar to real game logs.

Usage:
    python scripts/simulate_full_game.py
    python scripts/simulate_full_game.py --seed 42
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse

from hawarma.env_simulator import GameSimulator
from hawarma.bridge.simulator_environment import SimulatorEnvironment
from hawarma.agent.agent import (
    CookingAgent,
    Action,
    CookAction,
    MoveToAssemblyAction,
    MoveToStockpileAction,
    PullFromStockpileAction,
    AddCondimentAction,
    ServeOrderAction,
    ClearCookerAction,
    ClearAssemblyAction,
)


def run_full_simulation(seed: int = 42, recipe_file: str = "data/recipes.json", game_duration: float | None = None):
    """Run full simulation
    
    Args:
        seed: Random seed for recipe selection
        recipe_file: Path to recipes JSON file
        game_duration: Game duration in seconds (90-110), None for default (90s)
    """
    sim = GameSimulator(game_duration=game_duration)
    sim.load_recipes(recipe_file)
    selected = sim.select_recipes(count=4, random_seed=seed)
    sim.setup_from_recipes(selected)

    # Use new SimulatorEnvironment adapter
    env = SimulatorEnvironment(sim)

    # Build recipe adapters for agent
    # SimulatorEnvironment will provide recipe adapters through get_recipe_adapter
    # But we need to initialize the agent with something
    # Use the original simulator recipes - the agent will adapt them at runtime
    recipes = [sim.recipes[slug] for slug in selected]
    agent = CookingAgent(env, recipes)

    print("=" * 70)
    print(f"Full Game Simulation (seed={seed})")
    print("=" * 70)
    print(f"Recipes: {selected}")
    print(f"Cookers: {list(env.cookers.keys())}")
    print()

    tick_interval = 0.1
    action_count = 0
    orders_served = 0
    total_score = 0
    orders_timeout = 0

    while not env.is_game_over():
        # Process simulator events
        events = sim.tick(tick_interval)
        for event in events:
            et = event.event_type.name
            if et == "ORDER_APPEARED":
                rush_tag = "RUSH" if event.details.get("rush") else "normal"
                print(
                    f"[t={sim.time:.1f}s] NEW ORDER: {event.details['recipe']} ({rush_tag})"
                )
            elif et == "ORDER_TIMEOUT":
                orders_timeout += 1
                print(
                    f"[t={sim.time:.1f}s] ORDER TIMEOUT: {event.details.get('order_id', '?')}"
                )
            elif et == "ORDER_SERVED":
                orders_served += 1
                score = event.details.get("score", 0)
                total_score += score
                print(
                    f"[t={sim.time:.1f}s] SERVED order {event.details.get('order_id', '?')} | score={score}"
                )
            elif et == "COOKING_STARTED":
                pass  # Logged via action
            elif et == "COOKING_COMPLETED":
                pass  # Logged via action

        # Agent decision
        if not env.is_in_animation_window() or True:  # Agent runs always
            action = agent.step()
            if action:
                action_count += 1
                exec_stats = _execute_and_log(env, action, sim.time, sim)
                orders_served += exec_stats.get("orders_served", 0)
                total_score += exec_stats.get("total_score", 0)

    print()
    print("=" * 70)
    print(f"Game Over @ {sim.time:.1f}s")
    print("=" * 70)
    print(f"Orders served:  {orders_served}")
    print(f"Orders timeout: {orders_timeout}")
    print(f"Total score:    {total_score}")
    print(f"Total actions:  {action_count}")

    # Calculate efficiency metrics
    game_duration = sim.time

    # Calculate theoretical max score
    # Base score for each order type:
    # - RUSH: 218 (fast serve bonus)
    # - Normal: ~165 (base)
    # Perfect play: serve every order immediately when ready
    total_orders = orders_served + orders_timeout
    theoretical_max_score = 0
    for event in sim._event_history:
        if event.event_type.name == "ORDER_APPEARED":
            if event.details.get("rush"):
                theoretical_max_score += 218
            else:
                theoretical_max_score += 166

    # Efficiency: actual score / theoretical max score
    score_efficiency = (
        (total_score / theoretical_max_score * 100) if theoretical_max_score > 0 else 0
    )

    # Order success rate
    success_rate = (orders_served / total_orders * 100) if total_orders > 0 else 0

    print(
        f"Success rate:   {success_rate:.0f}% ({orders_served}/{total_orders} orders)"
    )
    print(f"Score eff:      {score_efficiency:.0f}% (actual vs optimal)")


def _execute_and_log(
    env: SimulatorEnvironment, action: Action, game_time: float, sim
) -> dict:
    """Execute action and print log line. Returns stats dict with any order served info."""
    stats = {"orders_served": 0, "total_score": 0}
    action_type = type(action).__name__

    if isinstance(action, CookAction):
        ok = env.start_cooking(action.ingredient, action.cooker, action.duration)
        if ok:
            print(
                f"[t={game_time:.1f}s] COOK {action.ingredient} on {action.cooker} ({action.duration}s)"
            )

    elif isinstance(action, MoveToAssemblyAction):
        ok = env.move_to_assembly(action.cooker)
        if ok:
            print(f"[t={game_time:.1f}s] MOVE {action.cooker} -> assembly")

    elif isinstance(action, MoveToStockpileAction):
        ok = env.move_to_stockpile(action.cooker, action.slot)
        if ok:
            print(f"[t={game_time:.1f}s] STORE {action.cooker} -> {action.slot}")

    elif isinstance(action, PullFromStockpileAction):
        ok = env.pull_from_stockpile(action.slot)
        if ok:
            print(
                f"[t={game_time:.1f}s] PULL {action.slot} ({action.ingredient}) -> assembly"
            )

    elif isinstance(action, AddCondimentAction):
        ok = env.add_condiment(action.condiment)
        if ok:
            print(f"[t={game_time:.1f}s] CONDIMENT {action.condiment}")

    elif isinstance(action, ServeOrderAction):
        result = sim.serve_order(action.slot_idx)
        if result.success:
            print(f"[t={game_time:.1f}s] SERVE slot {action.slot_idx} (animation 1.5s)")
            stats["orders_served"] = 1
            stats["total_score"] = result.score_earned
            # Process events from serve result
            for event in result.events:
                if event.event_type.name == "ORDER_SERVED":
                    order_id = event.details.get("order_id", "?")
                    score = event.details.get("score", 0)
                    print(
                        f"[t={game_time:.1f}s] SERVED order {order_id} | score={score}"
                    )

    elif isinstance(action, ClearCookerAction):
        ok = env.clear_cooker(action.cooker)
        if ok:
            print(f"[t={game_time:.1f}s] CLEAR {action.cooker}")

    elif isinstance(action, ClearAssemblyAction):
        ok = env.clear_assembly()
        if ok:
            print(f"[t={game_time:.1f}s] CLEAR assembly")

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--recipes", type=str, default="data/recipes.json")
    parser.add_argument("--game-duration", type=float, default=None,
                        help="Game duration in seconds (90-110), default 90")
    args = parser.parse_args()
    run_full_simulation(seed=args.seed, recipe_file=args.recipes, game_duration=args.game_duration)
