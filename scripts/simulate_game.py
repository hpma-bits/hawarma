"""
游戏模拟脚本

用于手动调试和观察 env_simulator 的行为。
不与真实游戏交互，仅用于验证环境逻辑。

Usage:
    python scripts/simulate_game.py
    python scripts/simulate_game.py --seed 42
    python scripts/simulate_game.py --tick 0.5
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from hawarma.env_simulator import GameSimulator


def run_simulation(
    recipe_file: str = "data/recipes.json",
    seed: int = 42,
    tick_interval: float = 0.1,
    max_time: float = 90.0,
) -> None:
    """
    运行一局游戏模拟
    
    Args:
        recipe_file: 配方文件路径
        seed: 随机种子（用于可复现）
        tick_interval: 每次tick的时间间隔（秒）
        max_time: 游戏最大时长
    """
    # 初始化
    sim = GameSimulator()
    sim.load_recipes(recipe_file)
    
    # 选菜单并配置游戏
    selected = sim.select_recipes(count=4, random_seed=seed)
    sim.setup_from_recipes(selected)
    
    print(f"=== Game Simulation (seed={seed}, tick={tick_interval}s) ===")
    print(f"Selected recipes: {selected}")
    print(f"Available cookers: {sim.game_config.available_cookers}")
    print(f"Available ingredients: {sim.game_config.available_ingredients}")
    print()
    
    # 游戏主循环
    while not sim.is_game_over():
        events = sim.tick(tick_interval)
        
        for event in events:
            if event.event_type.name == "ORDER_APPEARED":
                print(f"[t={sim.time:.1f}s] NEW ORDER: {event.details['recipe']} "
                      f"(rush={event.details['rush']})")
            elif event.event_type.name == "ORDER_TIMEOUT":
                print(f"[t={sim.time:.1f}s] TIMEOUT: order_id={event.details['order_id']}")
            elif event.event_type.name == "ORDER_SERVED":
                print(f"[t={sim.time:.1f}s] SERVED: order_id={event.details['order_id']}, "
                      f"score={event.details.get('score', 0)}")
    
    print(f"\n=== Game Over @ {sim.time:.1f}s ===")
    print(f"Total events: {len(sim.events)}")


def main():
    parser = argparse.ArgumentParser(description="Run game simulation")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--tick", type=float, default=0.1, help="Tick interval (seconds)")
    parser.add_argument("--recipes", type=str, default="data/recipes.json", 
                        help="Recipe file path")
    
    args = parser.parse_args()
    
    run_simulation(
        recipe_file=args.recipes,
        seed=args.seed,
        tick_interval=args.tick,
    )


if __name__ == "__main__":
    main()