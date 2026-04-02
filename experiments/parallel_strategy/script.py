"""
实验：多订单并行策略

实验目的：验证利用所有订单需要的食材是否能提高效率

Usage:
    python script.py
    python script.py --seeds 30
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse

from scripts.benchmark_utils import run_benchmark, print_results
from scripts.base_strategies import BASE_STRATEGIES


def main():
    parser = argparse.ArgumentParser(description="平行策略实验")
    parser.add_argument("--seeds", type=int, default=30, help="测试局数")
    parser.add_argument("--recipes", type=str, default="data/recipes.json")
    
    args = parser.parse_args()
    
    # 要对比的策略
    strategies = {
        "naive": BASE_STRATEGIES["naive"],
        "parallel": BASE_STRATEGIES["parallel"],
    }
    
    # 运行基准测试
    results = run_benchmark(
        strategies=strategies,
        num_games=args.seeds,
        recipes_file=args.recipes,
        debug_strategy="parallel"
    )
    
    # 打印结果
    print_results(results)


if __name__ == "__main__":
    main()
