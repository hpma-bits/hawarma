"""
实验：快速送餐策略

实验目的：验证优先完成简单订单（1种食材）是否能提高效率

策略思路：
1. 优先处理简单订单（1种食材）
2. 优先处理rush订单
3. 利用立即刷新规则，让新订单尽快出现

Usage:
    python script.py
    python script.py --seeds 30
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse

from hawarma.env_simulator import GameSimulator
from scripts.benchmark_utils import (
    run_benchmark, print_results, get_needed_ingredients, get_stockpile_info
)
from scripts.base_strategies import BASE_STRATEGIES


def get_order_priority(sim: GameSimulator) -> list[tuple[int, int, int]]:
    """
    获取订单优先级列表
    
    返回: [(slot_idx, ingredient_count, is_rush), ...]
    按 ingredient_count 升序排列（简单订单优先）
    """
    priorities = []
    for i, order in enumerate(sim._state.orders):
        if order and not order.is_completed:
            ingredient_count = len(order.recipe.ingredients)
            # TODO: 检测rush订单（暂时都当作普通订单）
            is_rush = 0
            priorities.append((i, ingredient_count, is_rush))
    
    # 按食材数量升序排列（简单订单优先）
    priorities.sort(key=lambda x: (x[1], x[2]))
    return priorities


def quick_serve_strategy(sim: GameSimulator) -> list:
    """
    快速送餐策略 - 优先完成简单订单
    
    核心思想：
    1. 优先处理简单订单（1种食材）
    2. 优先处理rush订单
    3. 利用立即刷新规则，让新订单尽快出现
    """
    actions = []
    assembly = sim._state.assembly
    assembly_ings = [ing[0] for ing in assembly.ingredients]
    
    # 检查动画窗口
    if sim.is_in_animation_window():
        return []
    
    # 获取订单优先级
    order_priorities = get_order_priority(sim)
    
    # 1. 送餐（检查所有订单，不仅仅是第一个）
    for slot_idx, _, _ in order_priorities:
        order = sim._state.orders[slot_idx]
        if order and not order.is_completed:
            recipe = order.recipe
            recipe_ings = [ing.name for ing in recipe.ingredients]
            if sorted(assembly_ings) == sorted(recipe_ings):
                condiments_ok = True
                for cond, count in recipe.condiments.items():
                    if assembly.condiments.get(cond, 0) < count:
                        condiments_ok = False
                        break
                if condiments_ok:
                    actions.append(('serve', slot_idx))
                    return actions
    
    # 2. 添加调料（食材齐全时）
    for slot_idx, _, _ in order_priorities:
        order = sim._state.orders[slot_idx]
        if order and not order.is_completed:
            recipe = order.recipe
            recipe_ings = [ing.name for ing in recipe.ingredients]
            if sorted(assembly_ings) == sorted(recipe_ings):
                for cond, needed in recipe.condiments.items():
                    current = assembly.condiments.get(cond, 0)
                    if current < needed:
                        actions.append(('add_condiment', cond))
                        return actions
    
    # 3. 移动完成食材到组装站（检查兼容性）
    for cooker_name, cooker in sim._state.cookers.items():
        if cooker.busy and cooker.done_at and sim.time >= cooker.done_at:
            if sim.time < cooker.expired_at:
                ingredient_name = cooker.ingredient_name
                # 检查assembly是否可以接受该食材
                if assembly.can_add_ingredient(ingredient_name, cooker.cooker_type):
                    actions.append(('move_to_assembly', cooker_name))
                    return actions
                # 如果assembly不兼容，尝试移到stockpile
                for slot_name, slot in sim._state.stockpile.items():
                    if slot.can_add(ingredient_name, cooker.cooker_type):
                        actions.append(('move_to_stockpile', cooker_name, slot_name))
                        return actions
    
    # 4. 开始烹饪（优先简单订单需要的食材）
    for slot_idx, _, _ in order_priorities:
        order = sim._state.orders[slot_idx]
        if order and not order.is_completed:
            for ing in order.recipe.ingredients:
                # 检查是否已在烹饪或已在assembly
                already_cooking = any(
                    c.busy and c.ingredient_name == ing.name 
                    for c in sim._state.cookers.values()
                )
                if ing.name in assembly_ings:
                    already_cooking = True
                
                if not already_cooking:
                    cooker_state = sim._state.cookers.get(ing.cooker_type)
                    if cooker_state and not cooker_state.busy:
                        actions.append(('cook', ing.name, ing.cooker_type))
                        return actions
    
    # 5. 从库存取用
    for slot_idx, _, _ in order_priorities:
        order = sim._state.orders[slot_idx]
        if order and not order.is_completed:
            for ing in order.recipe.ingredients:
                for slot_name, slot in sim._state.stockpile.items():
                    if slot.ingredient_name == ing.name and slot.count > 0:
                        if assembly.can_add_ingredient(ing.name, ing.cooker_type):
                            actions.append(('pull_from_stockpile', slot_name))
                            return actions
    
    # 6. 清理过期食材
    for cooker_name, cooker in sim._state.cookers.items():
        if cooker.busy and cooker.expired_at and sim.time >= cooker.expired_at:
            actions.append(('clear', cooker_name))
            return actions
    
    return actions


def main():
    parser = argparse.ArgumentParser(description="快速送餐策略实验")
    parser.add_argument("--seeds", type=int, default=30, help="测试局数")
    
    args = parser.parse_args()
    
    # 使用绝对路径
    recipes_file = str(Path(__file__).parent.parent.parent / "data" / "recipes.json")
    
    # 要对比的策略
    strategies = {
        "naive": BASE_STRATEGIES["naive"],
        "quick_serve": quick_serve_strategy,
    }
    
    # 运行基准测试
    results = run_benchmark(
        strategies=strategies,
        num_games=args.seeds,
        recipes_file=recipes_file,
        debug_strategy="quick_serve"
    )
    
    # 打印结果
    print_results(results)


if __name__ == "__main__":
    main()
