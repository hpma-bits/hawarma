"""
Agent 性能测试脚本

运行 agent 并统计游戏表现。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from hawarma.env_simulator import GameSimulator
from hawarma.agent import CookingAgent


def run_agent_test(seed: int = 42, verbose: bool = True) -> dict:
    """
    运行 agent 测试
    
    Args:
        seed: 随机种子
        verbose: 是否输出详细信息
        
    Returns:
        游戏统计
    """
    # 初始化模拟器
    sim = GameSimulator()
    sim.load_recipes("data/recipes.json")
    selected = sim.select_recipes(count=4, random_seed=seed)
    sim.setup_from_recipes(selected)
    
    if verbose:
        print(f"=== Agent Test (seed={seed}) ===")
        print(f"Selected recipes: {selected}")
        print()
    
    # 创建并运行 agent
    agent = CookingAgent(sim)
    stats = agent.run(tick_interval=0.5)
    
    if verbose:
        print(f"\n=== Results ===")
        print(f"Time: {stats['time']:.1f}s")
        print(f"Orders served: {stats['orders_served']}")
        print(f"Total score: {stats['total_score']}")
        print(f"Events: {stats['events_count']}")
    
    return stats


def run_multiple_tests(seeds: list[int] = None) -> None:
    """
    运行多次测试并统计平均表现
    """
    if seeds is None:
        seeds = list(range(10))
    
    results = []
    for seed in seeds:
        stats = run_agent_test(seed=seed, verbose=False)
        results.append(stats)
        print(f"Seed {seed}: served={stats['orders_served']}, score={stats['total_score']}")
    
    # 计算平均值
    avg_served = sum(s['orders_served'] for s in results) / len(results)
    avg_score = sum(s['total_score'] for s in results) / len(results)
    
    print(f"\n=== Average over {len(results)} runs ===")
    print(f"Orders served: {avg_served:.1f}")
    print(f"Total score: {avg_score:.1f}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Cooking Agent")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--multi", action="store_true", help="Run multiple tests")
    
    args = parser.parse_args()
    
    if args.multi:
        run_multiple_tests()
    else:
        run_agent_test(seed=args.seed)
