"""
基准策略定义

定义标准的基准策略：
- naive_strategy: 按文档优先级的策略
- parallel_strategy: 多订单并行策略

Usage:
    from scripts.base_strategies import naive_strategy, parallel_strategy
"""

from hawarma.env_simulator import GameSimulator
from scripts.benchmark_utils import get_needed_ingredients, get_stockpile_info


def naive_strategy(sim: GameSimulator) -> list:
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


def parallel_strategy(sim: GameSimulator) -> list:
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


# 标准策略字典
BASE_STRATEGIES = {
    "naive": naive_strategy,
    "parallel": parallel_strategy,
}
