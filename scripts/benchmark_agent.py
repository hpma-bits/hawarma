"""
Agent 性能基准测试

用于分析当前策略的瓶颈，收集关键指标：
- 平均订单完成数
- 灶台利用率
- 等待时间分布
- 预烹饪时间浪费

Usage:
    python scripts/benchmark_agent.py
    python scripts/benchmark_agent.py --seeds 100
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import random
from dataclasses import dataclass, field
from hawarma.env_simulator import GameSimulator, ActionResult
from hawarma.env_simulator_types import Recipe, Order


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
    wasted_precook_time: float = 0.0  # 预烹饪但未被使用的时间
    
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


def naive_agent_step(sim: GameSimulator) -> list:
    """
    按文档定义的优先级策略
    
    优先级顺序：
    1. 送餐
    2. 移动完成食材
    3. 开始烹饪
    4. 添加调料
    5. 从库存取用
    6. 清理过期食材
    """
    actions = []
    assembly = sim._state.assembly
    assembly_ings = [ing[0] for ing in assembly.ingredients]
    
    # 检查动画窗口
    if sim.is_in_animation_window():
        return []
    
    # 1. 送餐
    for i, order in enumerate(sim._state.orders):
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
                    actions.append(('serve', i))
                    return actions
    
    # 2. 移动完成食材到组装站
    for cooker_name, cooker in sim._state.cookers.items():
        if cooker.busy and cooker.done_at and sim.time >= cooker.done_at:
            if sim.time < cooker.expired_at:
                actions.append(('move_to_assembly', cooker_name))
                return actions
    
    # 3. 开始烹饪
    needed = get_needed_ingredients(sim)
    for ing_name in needed:
        already_cooking = any(
            c.busy and c.ingredient_name == ing_name 
            for c in sim._state.cookers.values()
        )
        if ing_name in assembly_ings:
            already_cooking = True
        
        if not already_cooking:
            for order in sim._state.orders:
                if order and not order.is_completed:
                    for ing in order.recipe.ingredients:
                        if ing.name == ing_name:
                            cooker_state = sim._state.cookers.get(ing.cooker_type)
                            if cooker_state and not cooker_state.busy:
                                actions.append(('cook', ing_name, ing.cooker_type))
                                return actions
    
    # 4. 添加调料（食材齐全时）
    for order in sim._state.orders:
        if order and not order.is_completed:
            recipe = order.recipe
            recipe_ings = [ing.name for ing in recipe.ingredients]
            if sorted(assembly_ings) == sorted(recipe_ings):
                for cond, needed in recipe.condiments.items():
                    current = assembly.condiments.get(cond, 0)
                    if current < needed:
                        actions.append(('add_condiment', cond))
                        return actions
    
    # 5. 从库存取用
    for slot_name, slot in sim._state.stockpile.items():
        if slot.count > 0 and slot.ingredient_name in needed:
            if assembly.can_add_ingredient(slot.ingredient_name, slot.cooker_type):
                actions.append(('pull_from_stockpile', slot_name))
                return actions
    
    # 6. 清理过期食材
    for cooker_name, cooker in sim._state.cookers.items():
        if cooker.busy and cooker.expired_at and sim.time >= cooker.expired_at:
            actions.append(('clear', cooker_name))
            return actions
    
    return actions


def parallel_agent_step(sim: GameSimulator) -> list:
    """
    多订单并行策略 - 利用所有订单需要的食材保证cooker忙碌
    
    核心思想：
    1. 收集所有订单需要的食材
    2. 为空闲灶台分配烹饪任务（即使不是当前订单需要的）
    3. 完成后存入stockpile，供后续订单使用
    """
    actions = []
    assembly = sim._state.assembly
    assembly_ings = [ing[0] for ing in assembly.ingredients]
    
    # 检查动画窗口
    if sim.is_in_animation_window():
        return []
    
    # 1. 送餐
    for i, order in enumerate(sim._state.orders):
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
                    actions.append(('serve', i))
                    return actions
    
    # 2. 移动完成食材到组装站（如果是当前订单需要的）
    for cooker_name, cooker in sim._state.cookers.items():
        if cooker.busy and cooker.done_at and sim.time >= cooker.done_at:
            if sim.time < cooker.expired_at:
                ingredient_name = cooker.ingredient_name
                # 如果是当前订单需要且assembly兼容，移动到assembly
                for order in sim._state.orders:
                    if order and not order.is_completed:
                        recipe_ings = [ing.name for ing in order.recipe.ingredients]
                        if ingredient_name in recipe_ings:
                            if assembly.can_add_ingredient(ingredient_name, cooker.cooker_type):
                                actions.append(('move_to_assembly', cooker_name))
                                return actions
    
    # 3. 开始烹饪（优先当前订单，其次其他订单）
    needed_current = []  # 当前订单需要的食材
    needed_all = []  # 所有订单需要的食材
    
    # 收集当前订单需要的食材
    for order in sim._state.orders:
        if order and not order.is_completed:
            for ing in order.recipe.ingredients:
                if ing.name not in [n for n, _, _ in needed_current]:
                    needed_current.append((ing.name, ing.cooker_type, ing.duration))
            break  # 只取第一个订单
    
    # 收集所有订单需要的食材
    seen = set()
    for order in sim._state.orders:
        if order and not order.is_completed:
            for ing in order.recipe.ingredients:
                if ing.name not in seen:
                    seen.add(ing.name)
                    needed_all.append((ing.name, ing.cooker_type, ing.duration))
    
    # 检查哪些食材已在stockpile中
    stockpile_counts = {}
    for slot in sim._state.stockpile.values():
        if slot.count > 0 and slot.ingredient_name:
            stockpile_counts[slot.ingredient_name] = stockpile_counts.get(slot.ingredient_name, 0) + slot.count
    
    # 优先烹饪当前订单需要的食材
    free_cookers = {name for name, cooker in sim._state.cookers.items() if not cooker.busy}
    
    for ing_name, cooker_type, duration in needed_current:
        if cooker_type not in free_cookers:
            continue
        if any(c.busy and c.ingredient_name == ing_name for c in sim._state.cookers.values()):
            continue
        if ing_name in assembly_ings:
            continue
        if stockpile_counts.get(ing_name, 0) > 0:
            continue
        actions.append(('cook', ing_name, cooker_type))
        return actions
    
    # 然后烹饪其他订单需要的食材（如果stockpile中没有）
    for ing_name, cooker_type, duration in needed_all:
        if cooker_type not in free_cookers:
            continue
        if any(c.busy and c.ingredient_name == ing_name for c in sim._state.cookers.values()):
            continue
        if ing_name in assembly_ings:
            continue
        if stockpile_counts.get(ing_name, 0) > 0:
            continue
        actions.append(('cook', ing_name, cooker_type))
        return actions
    
    # 4. 添加调料（食材齐全时）
    for order in sim._state.orders:
        if order and not order.is_completed:
            recipe = order.recipe
            recipe_ings = [ing.name for ing in recipe.ingredients]
            if sorted(assembly_ings) == sorted(recipe_ings):
                for cond, needed in recipe.condiments.items():
                    current = assembly.condiments.get(cond, 0)
                    if current < needed:
                        actions.append(('add_condiment', cond))
                        return actions
    
    # 5. 将完成的食材存入stockpile（如果不是当前订单需要的）
    for cooker_name, cooker in sim._state.cookers.items():
        if cooker.busy and cooker.done_at and sim.time >= cooker.done_at:
            if sim.time < cooker.expired_at:
                # 找到空闲的stockpile槽位
                for slot_name, slot in sim._state.stockpile.items():
                    if slot.can_add(cooker.ingredient_name, cooker.cooker_type):
                        actions.append(('move_to_stockpile', cooker_name, slot_name))
                        return actions
    
    # 6. 从库存取用
    for order in sim._state.orders:
        if order and not order.is_completed:
            for ing in order.recipe.ingredients:
                for slot_name, slot in sim._state.stockpile.items():
                    if slot.ingredient_name == ing.name and slot.count > 0:
                        if assembly.can_add_ingredient(ing.name, ing.cooker_type):
                            actions.append(('pull_from_stockpile', slot_name))
                            return actions
    
    # 7. 清理过期食材
    for cooker_name, cooker in sim._state.cookers.items():
        if cooker.busy and cooker.expired_at and sim.time >= cooker.expired_at:
            actions.append(('clear', cooker_name))
            return actions
    
    return actions


def precook_agent_step(sim: GameSimulator, precook_queue: list[tuple[str, str]]) -> list:
    """
    预烹饪策略：在等待订单时预先烹饪高频食材
    
    Args:
        precook_queue: 预烹饪队列 [(ingredient, cooker), ...]
    """
    actions = []
    assembly = sim._state.assembly
    assembly_ings = [ing[0] for ing in assembly.ingredients]
    
    # 1. 尝试送餐
    for i, order in enumerate(sim._state.orders):
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
                    actions.append(('serve', i))
                    return actions
    
    # 2. 添加调料（只有食材齐全时）
    for order in sim._state.orders:
        if order and not order.is_completed:
            recipe = order.recipe
            recipe_ings = [ing.name for ing in recipe.ingredients]
            if sorted(assembly_ings) == sorted(recipe_ings):
                for cond, needed in recipe.condiments.items():
                    current = assembly.condiments.get(cond, 0)
                    if current < needed:
                        actions.append(('add_condiment', cond))
                        return actions
    
    # 3. 移动完成食材到组装站
    for cooker_name, cooker in sim._state.cookers.items():
        if cooker.busy and cooker.done_at and sim.time >= cooker.done_at:
            if sim.time < cooker.expired_at:
                actions.append(('move_to_assembly', cooker_name))
                return actions
    
    # 4. 按需烹饪
    needed = get_needed_ingredients(sim)
    for ing_name in needed:
        already_cooking = any(
            c.busy and c.ingredient_name == ing_name 
            for c in sim._state.cookers.values()
        )
        
        if ing_name in assembly_ings:
            already_cooking = True
        
        if not already_cooking:
            for order in sim._state.orders:
                if order and not order.is_completed:
                    for ing in order.recipe.ingredients:
                        if ing.name == ing_name:
                            cooker_state = sim._state.cookers.get(ing.cooker_type)
                            if cooker_state and not cooker_state.busy:
                                actions.append(('cook', ing_name, ing.cooker_type))
                                return actions
    
    # 5. 预烹饪（如果没有待处理订单或灶台空闲）
    has_pending_order = any(o is not None for o in sim._state.orders)
    if not has_pending_order or count_active_cookers(sim) < 2:
        for ing_name, cooker_type in precook_queue:
            # 检查是否已在烹饪
            already_cooking = any(
                c.busy and c.ingredient_name == ing_name 
                for c in sim._state.cookers.values()
            )
            cooker_state = sim._state.cookers.get(cooker_type)
            if not already_cooking and cooker_state and not cooker_state.busy:
                actions.append(('cook', ing_name, cooker_type))
                return actions
    
    # 6. 清理过期食材
    for cooker_name, cooker in sim._state.cookers.items():
        if cooker.busy and cooker.expired_at and sim.time >= cooker.expired_at:
            actions.append(('clear', cooker_name))
            return actions
    
    return actions


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


def analyze_precook_candidates(sim: GameSimulator, recipe_slugs: list[str]) -> list[tuple[str, str]]:
    """
    分析最佳预烹饪食材
    
    选择标准：
    1. 被当前选择的多个菜谱共享的食材
    2. 烹饪时间短的食材（能在4秒内完成）
    """
    # 统计食材在当前菜谱中的出现频率
    ing_frequency = {}
    ing_info = {}  # (cooker, duration)
    
    for slug in recipe_slugs:
        recipe = sim.recipes.get(slug)
        if recipe:
            for ing in recipe.ingredients:
                ing_frequency[ing.name] = ing_frequency.get(ing.name, 0) + 1
                ing_info[ing.name] = (ing.cooker_type, ing.duration)
    
    print(f"  食材频率分析:")
    for ing_name, freq in sorted(ing_frequency.items(), key=lambda x: -x[1]):
        cooker, duration = ing_info[ing_name]
        print(f"    {ing_name}: {freq}个菜谱, {cooker}, {duration}s")
    
    # 优先选择被多个菜谱共享且能在4秒内完成的食材
    candidates = []
    for ing_name, freq in ing_frequency.items():
        cooker, duration = ing_info[ing_name]
        # 优先选择共享食材，其次选择短时间食材
        if freq >= 2 and duration <= 4.0:
            candidates.append((ing_name, cooker, freq, duration, 1))  # 高优先级
        elif freq >= 2:
            candidates.append((ing_name, cooker, freq, duration, 2))  # 中优先级
        elif duration <= 3.0:
            candidates.append((ing_name, cooker, freq, duration, 3))  # 低优先级
    
    # 按优先级和频率排序
    candidates.sort(key=lambda x: (x[4], -x[2], x[3]))
    
    print(f"  预烹饪候选: {[(c[0], c[1]) for c in candidates[:4]]}")
    return [(c[0], c[1]) for c in candidates[:4]]


def smart_precook_agent_step(sim: GameSimulator, precook_queue: list[tuple[str, str]], recipe_slugs: list[str]) -> list:
    """
    智能策略 - 烹饪优先 + 预烹饪到库存
    
    核心思想：
    1. 送餐最优先
    2. 烹饪优先于调味（灶台是稀缺资源）
    3. 前4秒预烹饪高频食材到库存（避免占用assembly）
    """
    actions = []
    assembly = sim._state.assembly
    assembly_ings = [ing[0] for ing in assembly.ingredients]
    
    # 检查动画窗口
    if sim.is_in_animation_window():
        return []
    
    # 1. 尝试送餐（最高优先级）
    for i, order in enumerate(sim._state.orders):
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
                    actions.append(('serve', i))
                    return actions
    
    # 2. 移动完成食材到组装站（检查兼容性）
    for cooker_name, cooker in sim._state.cookers.items():
        if cooker.busy and cooker.done_at and sim.time >= cooker.done_at:
            if sim.time < cooker.expired_at:
                ingredient_name = cooker.ingredient_name
                
                # 获取当前订单的recipe
                current_order_recipe = None
                for order in sim._state.orders:
                    if order and not order.is_completed:
                        current_order_recipe = order.recipe
                        break
                
                if not current_order_recipe:
                    continue
                
                # 检查食材是否在当前订单的recipe中
                recipe_ingredients = [ing.name for ing in current_order_recipe.ingredients]
                if ingredient_name not in recipe_ingredients:
                    continue  # 食材不属于当前订单，跳过
                
                # 检查食材是否已在assembly中
                if ingredient_name in assembly_ings:
                    continue  # 食材已在assembly中
                
                # 检查assembly是否为空或target_recipe匹配
                if assembly.target_recipe and assembly.target_recipe != current_order_recipe:
                    continue  # target_recipe不匹配
                
                actions.append(('move_to_assembly', cooker_name))
                return actions
    
    # 3. 开始烹饪（关键优化：烹饪优先于调味！）
    needed = get_needed_ingredients(sim)
    for ing_name in needed:
        already_cooking = any(
            c.busy and c.ingredient_name == ing_name 
            for c in sim._state.cookers.values()
        )
        if ing_name in assembly_ings:
            already_cooking = True
        
        if not already_cooking:
            for order in sim._state.orders:
                if order and not order.is_completed:
                    for ing in order.recipe.ingredients:
                        if ing.name == ing_name:
                            cooker_state = sim._state.cookers.get(ing.cooker_type)
                            if cooker_state and not cooker_state.busy:
                                actions.append(('cook', ing_name, ing.cooker_type))
                                return actions
    
    # 4. 添加调料（只有食材齐全时）
    for order in sim._state.orders:
        if order and not order.is_completed:
            recipe = order.recipe
            recipe_ings = [ing.name for ing in recipe.ingredients]
            if sorted(assembly_ings) == sorted(recipe_ings):
                for cond, needed in recipe.condiments.items():
                    current = assembly.condiments.get(cond, 0)
                    if current < needed:
                        actions.append(('add_condiment', cond))
                        return actions
    
    # 5. 清理过期食材
    for cooker_name, cooker in sim._state.cookers.items():
        if cooker.busy and cooker.expired_at and sim.time >= cooker.expired_at:
            actions.append(('clear', cooker_name))
            return actions
    
    return actions


def stockpile_agent_step(sim: GameSimulator, precook_queue: list[tuple[str, str]]) -> list:
    """
    库存优化策略 - 利用stockpile提高灶台利用率
    
    核心思想：
    1. 前4秒预烹饪高频食材到stockpile
    2. 订单出现时，优先从stockpile取出食材
    3. 烹饪完成后，如果不是急需的食材，存入stockpile
    """
    actions = []
    assembly = sim._state.assembly
    assembly_ings = [ing[0] for ing in assembly.ingredients]
    
    # 检查动画窗口
    if sim.is_in_animation_window():
        return []
    
    # 1. 尝试送餐（最高优先级）
    for i, order in enumerate(sim._state.orders):
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
                    actions.append(('serve', i))
                    return actions
    
    # 2. 添加调料（食材齐全时）
    for order in sim._state.orders:
        if order and not order.is_completed:
            recipe = order.recipe
            recipe_ings = [ing.name for ing in recipe.ingredients]
            if sorted(assembly_ings) == sorted(recipe_ings):
                for cond, needed in recipe.condiments.items():
                    current = assembly.condiments.get(cond, 0)
                    if current < needed:
                        actions.append(('add_condiment', cond))
                        return actions
    
    # 3. 从stockpile取出需要的食材
    stockpile_info = get_stockpile_info(sim)
    needed = get_needed_ingredients(sim)
    
    for ing_name in needed:
        if ing_name in assembly_ings:
            continue  # 已在assembly中
        
        # 查找stockpile中是否有这个食材
        for slot_name, (slot_ing, slot_cooker, count) in stockpile_info.items():
            if slot_ing == ing_name and count > 0:
                # 检查assembly是否兼容
                if assembly.can_add_ingredient(ing_name, slot_cooker):
                    actions.append(('pull_from_stockpile', slot_name))
                    return actions
    
    # 4. 移动完成食材
    has_order = any(o is not None for o in sim._state.orders)
    
    for cooker_name, cooker in sim._state.cookers.items():
        if cooker.busy and cooker.done_at and sim.time >= cooker.done_at:
            if sim.time < cooker.expired_at:
                ingredient_name = cooker.ingredient_name
                
                # 如果有订单且食材是订单需要的，移动到assembly
                if has_order:
                    for order in sim._state.orders:
                        if order and not order.is_completed:
                            recipe_ings = [ing.name for ing in order.recipe.ingredients]
                            if ingredient_name in recipe_ings:
                                if assembly.can_add_ingredient(ingredient_name, cooker.cooker_type):
                                    actions.append(('move_to_assembly', cooker_name))
                                    return actions
                
                # 否则，如果有空闲stockpile槽位，移动到stockpile
                for slot_name, slot in sim._state.stockpile.items():
                    if slot.can_add(ingredient_name, cooker.cooker_type):
                        actions.append(('move_to_stockpile', cooker_name, slot_name))
                        return actions
                
                # 如果都不能存，移动到assembly（如果兼容）
                if assembly.can_add_ingredient(ingredient_name, cooker.cooker_type):
                    actions.append(('move_to_assembly', cooker_name))
                    return actions
    
    # 5. 开始烹饪
    for ing_name in needed:
        already_cooking = any(
            c.busy and c.ingredient_name == ing_name 
            for c in sim._state.cookers.values()
        )
        if ing_name in assembly_ings:
            already_cooking = True
        
        # 检查stockpile中是否已有
        stockpile_has = any(
            slot_ing == ing_name 
            for slot_ing, _, _ in stockpile_info.values()
        )
        if stockpile_has:
            already_cooking = True
        
        if not already_cooking:
            for order in sim._state.orders:
                if order and not order.is_completed:
                    for ing in order.recipe.ingredients:
                        if ing.name == ing_name:
                            cooker_state = sim._state.cookers.get(ing.cooker_type)
                            if cooker_state and not cooker_state.busy:
                                actions.append(('cook', ing_name, ing.cooker_type))
                                return actions
    
    # 6. 预烹饪（前4秒或没有订单时）
    if sim.time < 4.0 or not has_order:
        for ing_name, cooker_type in precook_queue:
            already_cooking = any(
                c.busy and c.ingredient_name == ing_name 
                for c in sim._state.cookers.values()
            )
            stockpile_has = any(
                slot_ing == ing_name 
                for slot_ing, _, _ in stockpile_info.values()
            )
            cooker_state = sim._state.cookers.get(cooker_type)
            
            if not already_cooking and not stockpile_has and cooker_state and not cooker_state.busy:
                actions.append(('cook', ing_name, cooker_type))
                return actions
    
    # 7. 清理过期食材
    for cooker_name, cooker in sim._state.cookers.items():
        if cooker.busy and cooker.expired_at and sim.time >= cooker.expired_at:
            actions.append(('clear', cooker_name))
            return actions
    
    return actions


def run_single_game(
    sim: GameSimulator,
    recipe_slugs: list[str],
    strategy: str = "naive",
    seed: int = 42,
    debug: bool = False
) -> GameMetrics:
    """运行单局游戏并收集指标"""
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
    
    # 分析预烹饪候选
    precook_queue = analyze_precook_candidates(sim, recipe_slugs)
    
    if debug:
        print(f"Recipe slugs: {recipe_slugs}")
        print(f"Precook queue: {precook_queue}")
    
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
            # 选择策略
            if strategy == "naive":
                actions = naive_agent_step(sim)
            elif strategy == "parallel":
                actions = parallel_agent_step(sim)
            elif strategy == "smart_precook":
                actions = smart_precook_agent_step(sim, precook_queue, recipe_slugs)
            elif strategy == "stockpile":
                actions = stockpile_agent_step(sim, precook_queue)
            else:
                actions = precook_agent_step(sim, precook_queue)
            
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
    num_games: int = 50,
    recipes_file: str = "data/recipes.json"
):
    """运行基准测试"""
    print("=" * 60)
    print("Agent 性能基准测试")
    print("=" * 60)
    
    sim = GameSimulator()
    sim.load_recipes(recipes_file)
    
    strategies = ["naive", "parallel"]
    results = {s: [] for s in strategies}
    
    for seed in range(num_games):
        random.seed(seed)
        recipe_slugs = sim.select_recipes(count=4, random_seed=seed)
        
        for strategy in strategies:
            debug = (seed == 0 and strategy == "stockpile")  # 只对第一局stockpile策略启用调试
            metrics = run_single_game(sim, recipe_slugs, strategy, seed, debug=debug)
            results[strategy].append(metrics)
        
        if (seed + 1) % 10 == 0:
            print(f"Completed {seed + 1}/{num_games} games...")
    
    # 输出结果
    print("\n" + "=" * 60)
    print("测试结果")
    print("=" * 60)
    
    for strategy in strategies:
        metrics_list = results[strategy]
        avg_served = sum(m.orders_served for m in metrics_list) / len(metrics_list)
        avg_score = sum(m.total_score for m in metrics_list) / len(metrics_list)
        avg_timeout = sum(m.orders_timeout for m in metrics_list) / len(metrics_list)
        avg_idle = sum(m.idle_time for m in metrics_list) / len(metrics_list)
        avg_wait_order = sum(m.waiting_for_order_time for m in metrics_list) / len(metrics_list)
        
        print(f"\n策略: {strategy}")
        print(f"  平均完成订单: {avg_served:.1f}")
        print(f"  平均得分: {avg_score:.1f}")
        print(f"  平均超时: {avg_timeout:.1f}")
        print(f"  平均空闲时间: {avg_idle:.1f}s")
        print(f"  平均等待订单时间: {avg_wait_order:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agent benchmark")
    parser.add_argument("--seeds", type=int, default=50, help="Number of games")
    parser.add_argument("--recipes", type=str, default="data/recipes.json")
    
    args = parser.parse_args()
    run_benchmark(num_games=args.seeds, recipes_file=args.recipes)
