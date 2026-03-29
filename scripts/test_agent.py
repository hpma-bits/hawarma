"""
Agent 性能测试脚本

运行 agent 并统计游戏表现。
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from hawarma.env_simulator import GameSimulator
from hawarma.agent import CookingAgent
from hawarma.agent.v2 import CookingAgentV2


def run_agent_test(seed: int = 42, tick: float = 0.1, version: int = 2, 
                   verbose: bool = True) -> dict:
    """
    运行 agent 测试
    
    Args:
        seed: 随机种子
        tick: 决策间隔
        version: agent 版本 (1 或 2)
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
        print(f"=== Agent v{version} Test (seed={seed}, tick={tick}s) ===")
        print(f"Selected recipes: {selected}")
        print()
    
    # 创建并运行 agent
    if version == 2:
        agent = CookingAgentV2(sim)
    else:
        agent = CookingAgent(sim)
    
    stats = agent.run(tick_interval=tick)
    
    if verbose:
        print(f"\n=== Results ===")
        print(f"Time: {stats['time']:.1f}s")
        print(f"Orders served: {stats['orders_served']}")
        print(f"Total score: {stats['total_score']}")
        if 'actions_taken' in stats:
            print(f"Actions taken: {stats['actions_taken']}")
        print(f"Events: {stats['events_count']}")
    
    return stats


def run_multiple_tests(seeds: list[int] = None, tick: float = 0.1, 
                       version: int = 2) -> None:
    """
    运行多次测试并统计平均表现
    """
    if seeds is None:
        seeds = list(range(10))
    
    results = []
    for seed in seeds:
        stats = run_agent_test(seed=seed, tick=tick, version=version, verbose=False)
        results.append(stats)
        print(f"Seed {seed}: served={stats['orders_served']}, score={stats['total_score']}")
    
    # 计算平均值
    avg_served = sum(s['orders_served'] for s in results) / len(results)
    avg_score = sum(s['total_score'] for s in results) / len(results)
    max_served = max(s['orders_served'] for s in results)
    max_score = max(s['total_score'] for s in results)
    
    print(f"\n=== Average over {len(results)} runs (v{version}, tick={tick}s) ===")
    print(f"Orders served: avg={avg_served:.1f}, max={max_served}")
    print(f"Total score: avg={avg_score:.0f}, max={max_score}")
    
    # 理论上限
    print(f"\n=== Theoretical Max ===")
    print(f"Max orders: 22")
    print(f"Max score: 4840")
    print(f"Current efficiency: {avg_score / 4840 * 100:.1f}%")


def compare_ticks(version: int = 2) -> None:
    """比较不同 tick 的性能"""
    ticks = [0.5, 0.2, 0.1, 0.05]
    
    print(f"=== Agent v{version} Tick Comparison ===\n")
    for tick in ticks:
        scores = []
        orders = []
        for seed in range(5):
            stats = run_agent_test(seed=seed, tick=tick, version=version, verbose=False)
            scores.append(stats['total_score'])
            orders.append(stats['orders_served'])
        
        avg_score = sum(scores) / len(scores)
        avg_orders = sum(orders) / len(orders)
        print(f"tick={tick:.2f}s: avg_score={avg_score:.0f}, avg_orders={avg_orders:.1f}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Cooking Agent")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--tick", type=float, default=0.1, help="Tick interval")
    parser.add_argument("--version", type=int, default=2, help="Agent version (1 or 2)")
    parser.add_argument("--multi", action="store_true", help="Run multiple tests")
    parser.add_argument("--compare", action="store_true", help="Compare different ticks")
    
    args = parser.parse_args()
    
    if args.compare:
        compare_ticks(version=args.version)
    elif args.multi:
        run_multiple_tests(tick=args.tick, version=args.version)
    else:
        run_agent_test(seed=args.seed, tick=args.tick, version=args.version)
