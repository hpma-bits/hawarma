"""
基准测试工具模块

提供实验脚本可复用的功能：
- GameMetrics: 游戏指标数据类
- 辅助函数: count_active_cookers, get_needed_ingredients, get_stockpile_info
- execute_action: 执行动作
- run_single_game: 运行单局游戏
- run_benchmark: 运行基准测试

Usage:
    from scripts.benchmark_utils import GameMetrics, run_single_game, run_benchmark

⚠️ 重要：测试必须通过策略函数运行，不要直接调用模拟器方法！
   正确：run_single_game(sim, recipe_slugs, strategy_fn, seed)
   错误：sim.serve_order(0); sim.add_condiment(...)  # 会导致状态不一致
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import random
from dataclasses import dataclass, field
from typing import Callable
from hawarma.env_simulator import GameSimulator, ActionResult


@dataclass
class GameMetrics:
    """单局游戏指标"""
    orders_served: int = 0
    orders_timeout: int = 0
    total_score: int = 0
    
    # 时间利用
    idle_time: float = 0.0  # 灶台全部空闲的时间
    peak_cooker_usage: int = 0  # 同时使用的最多灶台数
    
    # 瓶颈分析
    waiting_for_order_time: float = 0.0  # 等待订单的时间
    waiting_for_cooker_time: float = 0.0  # 等待空闲灶台的时间
    
    # 订单完成时间
    order_completion_times: list[float] = field(default_factory=list)


def count_active_cookers(sim: GameSimulator) -> int:
    """计算当前忙碌的灶台数量"""
    count = 0
    for cooker in sim._state.cookers.values():
        if cooker.busy:
            count += 1
    return count


def get_needed_ingredients(sim: GameSimulator) -> list[str]:
    """获取当前订单需要的食材（去重），按烹饪时间降序排列"""
    needed = []
    seen = set()
    
    # 收集所有订单需要的食材及其烹饪时间
    ing_info = {}  # name -> (cooker, duration)
    for order in sim._state.orders:
        if order and not order.is_completed:
            for ing in order.recipe.ingredients:
                if ing.name not in seen:
                    seen.add(ing.name)
                    ing_info[ing.name] = (ing.cooker_type, ing.duration)
    
    # 按烹饪时间降序排列（优先烹饪时间长的）
    sorted_ings = sorted(ing_info.items(), key=lambda x: -x[1][1])
    return [name for name, _ in sorted_ings]


def get_stockpile_info(sim: GameSimulator) -> dict[str, tuple[str, str, int]]:
    """获取库存信息：slot_name -> (ingredient_name, cooker_type, count)"""
    info = {}
    for slot_name, slot in sim._state.stockpile.items():
        if slot.count > 0:
            info[slot_name] = (slot.ingredient_name, slot.cooker_type, slot.count)
    return info


def execute_action(sim: GameSimulator, action: tuple) -> ActionResult:
    """执行一个动作"""
    action_type = action[0]
    
    if action_type == 'serve':
        return sim.serve_order(action[1])
    elif action_type == 'add_condiment':
        return sim.add_condiment(action[1])
    elif action_type == 'move_to_assembly':
        return sim.move_to_assembly(action[1])
    elif action_type == 'cook':
        return sim.start_cooking(action[1], action[2])
    elif action_type == 'clear':
        return sim.clear_cooker(action[1])
    elif action_type == 'move_to_stockpile':
        return sim.move_to_stockpile(action[1], action[2])
    elif action_type == 'pull_from_stockpile':
        return sim.pull_from_stockpile(action[1])
    else:
        return ActionResult.failure_result(f"Unknown action: {action_type}")


def run_single_game(
    sim: GameSimulator,
    recipe_slugs: list[str],
    strategy_fn: Callable[[GameSimulator], list],
    seed: int = 42,
    debug: bool = False
) -> GameMetrics:
    """
    运行单局游戏并收集指标
    
    Args:
        sim: 游戏模拟器
        recipe_slugs: 菜谱列表
        strategy_fn: 策略函数，接受sim返回actions
        seed: 随机种子
        debug: 是否输出调试信息
    
    Returns:
        GameMetrics: 游戏指标
    """
    metrics = GameMetrics()
    
    # 设置游戏
    sim._state = type(sim._state)()  # 重置状态
    sim._event_history = []
    sim._next_order_id = 1
    sim._needs_immediate_refresh = False
    sim._last_order_time = 0.0
    sim._next_order_refresh_time = 4.0
    sim._animation_until = 0.0
    
    sim.setup_from_recipes(recipe_slugs)
    
    if debug:
        print(f"Recipe slugs: {recipe_slugs}")
    
    # 游戏主循环
    tick_interval = 0.1
    action_count = 0
    max_actions_per_tick = 5  # 每个tick最多执行的动作数
    
    while not sim.is_game_over():
        # 记录指标
        active_cookers = count_active_cookers(sim)
        if active_cookers == 0:
            metrics.idle_time += tick_interval
        metrics.peak_cooker_usage = max(metrics.peak_cooker_usage, active_cookers)
        
        has_order = any(o is not None for o in sim._state.orders)
        if not has_order:
            metrics.waiting_for_order_time += tick_interval
        
        # 执行动作（每个tick最多执行几个动作）
        actions_this_tick = 0
        while actions_this_tick < max_actions_per_tick:
            actions = strategy_fn(sim)
            
            if not actions:
                break
            
            for action in actions:
                result = execute_action(sim, action)
                action_count += 1
                actions_this_tick += 1
                
                # 收集动作返回的事件（特别是ORDER_SERVED）
                for event in result.events:
                    if event.event_type.name == "ORDER_SERVED":
                        metrics.orders_served += 1
                        metrics.total_score += event.details.get('score', 0)
                        if debug:
                            print(f"[t={sim.time:.1f}] ORDER SERVED! Score: {event.details.get('score', 0)}")
                
                if debug:
                    print(f"[t={sim.time:.1f}] Action: {action}, Success: {result.success}")
                    if not result.success:
                        print(f"  Error: {result.error_message}")
        
        # 推进时间
        events = sim.tick(tick_interval)
        
        # 收集事件指标
        for event in events:
            if event.event_type.name == "ORDER_SERVED":
                metrics.orders_served += 1
                metrics.total_score += event.details.get('score', 0)
                if debug:
                    print(f"[t={sim.time:.1f}] ORDER SERVED! Score: {event.details.get('score', 0)}")
            elif event.event_type.name == "ORDER_TIMEOUT":
                metrics.orders_timeout += 1
                if debug:
                    print(f"[t={sim.time:.1f}] ORDER TIMEOUT!")
            elif event.event_type.name == "ORDER_APPEARED" and debug:
                print(f"[t={sim.time:.1f}] NEW ORDER: {event.details.get('recipe')}")
    
    if debug:
        print(f"\nTotal actions: {action_count}")
        print(f"Final score: {metrics.total_score}, Served: {metrics.orders_served}")
    
    return metrics


def run_benchmark(
    strategies: dict[str, Callable[[GameSimulator], list]],
    num_games: int = 30,
    recipes_file: str = "data/recipes.json",
    debug_strategy: str | None = None
) -> dict[str, list[GameMetrics]]:
    """
    运行基准测试
    
    Args:
        strategies: 策略字典 {name: strategy_fn}
        num_games: 测试局数
        recipes_file: 菜谱文件路径
        debug_strategy: 要输出调试信息的策略名称
    
    Returns:
        dict: {strategy_name: [GameMetrics, ...]}
    """
    print("=" * 60)
    print("Agent 性能基准测试")
    print("=" * 60)
    
    sim = GameSimulator()
    sim.load_recipes(recipes_file)
    
    results = {name: [] for name in strategies}
    
    for seed in range(num_games):
        random.seed(seed)
        recipe_slugs = sim.select_recipes(count=4, random_seed=seed)
        
        for name, strategy_fn in strategies.items():
            debug = (seed == 0 and name == debug_strategy)
            metrics = run_single_game(sim, recipe_slugs, strategy_fn, seed, debug=debug)
            results[name].append(metrics)
        
        if (seed + 1) % 10 == 0:
            print(f"Completed {seed + 1}/{num_games} games...")
    
    return results


def print_results(results: dict[str, list[GameMetrics]]) -> None:
    """打印基准测试结果"""
    print("\n" + "=" * 60)
    print("测试结果")
    print("=" * 60)
    
    for name, metrics_list in results.items():
        avg_served = sum(m.orders_served for m in metrics_list) / len(metrics_list)
        avg_score = sum(m.total_score for m in metrics_list) / len(metrics_list)
        avg_timeout = sum(m.orders_timeout for m in metrics_list) / len(metrics_list)
        avg_idle = sum(m.idle_time for m in metrics_list) / len(metrics_list)
        avg_wait_order = sum(m.waiting_for_order_time for m in metrics_list) / len(metrics_list)
        
        print(f"\n策略: {name}")
        print(f"  平均完成订单: {avg_served:.1f}")
        print(f"  平均得分: {avg_score:.1f}")
        print(f"  平均超时: {avg_timeout:.1f}")
        print(f"  平均空闲时间: {avg_idle:.1f}s")
        print(f"  平均等待订单时间: {avg_wait_order:.1f}s")
