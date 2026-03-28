# env_simulator 调试指南

本文档介绍如何在开发过程中调试和分析 env_simulator。

---

## 1. 启用调试模式

```python
from hawarma.env_simulator import GameSimulator

sim = GameSimulator()
sim.enable_debug(True)  # 启用调试模式
```

调试模式下会打印：
- 烹饪开始/完成
- 食材移动
- 订单生成/超时
- 调料添加
- 槽位变化

---

## 2. 基础调试

### 2.1 查看当前游戏配置

```python
sim = GameSimulator()
sim.load_recipes('data/recipes.json')
selected = sim.select_recipes(count=4, random_seed=42)
config = sim.setup_from_recipes(selected)

print(f"选中的菜谱: {config.selected_recipes}")
print(f"可用灶台: {config.available_cookers}")
print(f"食材区: {config.available_ingredients}")
print(f"调料区: {config.available_condiments}")
```

### 2.2 查看当前状态

```python
# 完整状态
print(sim.state)

# 特定组件
print(sim.state.orders)      # 订单列表
print(sim.state.cookers)     # 灶台状态
print(sim.state.assembly)    # 组装站状态
print(sim.state.stockpile)   # 库存状态

# 便捷查询
sim.get_order(0)                    # 获取槽位0的订单
sim.get_cooker_state('skillet')     # 获取skillet状态
sim.time                             # 当前时间
sim.is_game_over()                   # 游戏是否结束
```

### 2.3 查看事件历史

```python
# 所有事件
for event in sim.events:
    print(f"[{event.event_type.name}] t={event.timestamp:.1f}s - {event.details}")

# 特定类型事件
from hawarma.env_simulator_types import EventType

orders = [e for e in sim.events if e.event_type == EventType.ORDER_APPEARED]
timeouts = [e for e in sim.events if e.event_type == EventType.ORDER_TIMEOUT]
served = [e for e in sim.events if e.event_type == EventType.ORDER_SERVED]
```

---

## 3. 逐步模拟

### 3.1 手动单步调试

```python
sim = GameSimulator()
sim.load_recipes('data/recipes.json')
sim.setup_from_recipes(sim.select_recipes(count=4))

# 逐步推进时间
for t in range(0, 90, 1):  # 每秒一步
    events = sim.tick(1.0)
    print(f"\n=== t={sim.time:.1f}s ===")
    
    for e in events:
        print(f"  {e.event_type.name}: {e.details}")
    
    # 检查订单
    for i, order in enumerate(sim.state.orders):
        if order:
            print(f"  Slot {i}: {order.recipe.name}")
```

### 3.2 自动模拟完整游戏

```python
def run_full_game(seed=42):
    sim = GameSimulator()
    sim.load_recipes('data/recipes.json')
    sim.setup_from_recipes(sim.select_recipes(count=4, random_seed=seed))
    
    total_score = 0
    orders_served = 0
    orders_timeout = 0
    
    while not sim.is_game_over():
        events = sim.tick(0.5)
        
        for e in events:
            if e.event_type.name == 'ORDER_APPEARED':
                print(f"[{sim.time:.1f}s] 新订单: {e.details['recipe']} (rush={e.details['rush']})")
            elif e.event_type.name == 'ORDER_TIMEOUT':
                orders_timeout += 1
                print(f"[{sim.time:.1f}s] 订单超时!")
            elif e.event_type.name == 'ORDER_SERVED':
                orders_served += 1
                total_score += e.details.get('score', 0)
                print(f"[{sim.time:.1f}s] 订单完成! +{e.details['score']}分")
    
    print(f"\n=== 游戏结束 @ {sim.time:.1f}s ===")
    print(f"完成订单: {orders_served}")
    print(f"超时订单: {orders_timeout}")
    print(f"总得分: {total_score}")
    
    return {
        'time': sim.time,
        'served': orders_served,
        'timeout': orders_timeout,
        'score': total_score,
        'events': sim.events
    }

run_full_game(42)
```

### 3.3 断点式调试（特定事件暂停）

```python
def debug_with_breakpoints():
    sim = GameSimulator()
    sim.load_recipes('data/recipes.json')
    sim.setup_from_recipes(sim.select_recipes(count=4))
    
    while not sim.is_game_over():
        events = sim.tick(0.5)
        
        # 在新订单出现时暂停
        new_orders = [e for e in events if e.event_type.name == 'ORDER_APPEARED']
        if new_orders:
            print(f"\n=== 新订单 @ t={sim.time:.1f}s ===")
            for e in new_orders:
                print(f"  {e.details}")
            input("按回车继续...")
        
        # 在订单超时时间前暂停
        for order in sim.state.orders:
            if order and abs(sim.time - order.timeout_at) < 0.6:
                print(f"\n=== 订单即将超时 @ t={sim.time:.1f}s ===")
                input("按回车继续...")

# debug_with_breakpoints()
```

---

## 4. 状态对比

### 4.1 操作前后的状态差异

```python
def show_state_diff(sim, before_state, action_name):
    """显示操作前后的状态变化"""
    print(f"\n--- {action_name} ---")
    print(f"时间: {sim.time:.1f}s")
    
    # 对比订单
    for i in range(4):
        before = before_state.orders[i]
        after = sim.state.orders[i]
        if before != after:
            print(f"  Slot {i}: {before} -> {after}")
    
    # 对比灶台
    for name, cooker in sim.state.cookers.items():
        before_cooker = before_state.cookers.get(name)
        if before_cooker != cooker:
            print(f"  {name}: {before_cooker} -> {cooker}")

# 使用示例
sim = GameSimulator()
sim.load_recipes('data/recipes.json')
sim.setup_from_recipes(sim.select_recipes(count=4))

before = sim.state.copy()
sim.start_cooking('clearwater_fish', 'skillet')
show_state_diff(sim, before, "start_cooking")
```

### 4.2 打印美化的状态

```python
def print_fancy_state(sim):
    """打印美化的游戏状态"""
    print(f"\n{'='*50}")
    print(f"时间: {sim.time:.1f}s / 90s")
    print(f"{'='*50}")
    
    # 订单
    print("\n📋 订单:")
    for i, order in enumerate(sim.state.orders):
        if order:
            status = "🔴 rush" if order.is_rush else "⚪ normal"
            time_left = order.timeout_at - sim.time
            print(f"  [{i}] {order.recipe.name} {status} (剩余{time_left:.1f}s)")
        else:
            print(f"  [{i}] 空")
    
    # 灶台
    print("\n🍳 灶台:")
    for name, cooker in sim.state.cookers.items():
        if cooker.busy:
            print(f"  {name}: 🔥 {cooker.ingredient_name} ({cooker.cooker_type})")
            if cooker.done_at:
                print(f"      完成于 {cooker.done_at:.1f}s, 过期于 {cooker.expired_at:.1f}s")
        else:
            print(f"  {name}: ✅ 空")
    
    # 组装站
    assembly = sim.state.assembly
    print("\n🍽️ 组装站:")
    if assembly.ingredients:
        print(f"  食材: {[ing[0] for ing in assembly.ingredients]}")
        print(f"  调料: {assembly.condiments}")
        print(f"  完成: {assembly.is_complete}")
        if assembly.target_recipe:
            print(f"  目标: {assembly.target_recipe.name}")
    else:
        print("  空")
    
    # 库存
    print("\n📦 库存:")
    for name, slot in sim.state.stockpile.items():
        if slot.count > 0:
            print(f"  {name}: {slot.ingredient_name} x{slot.count}")
        else:
            print(f"  {name}: 空")

# 使用示例
sim = GameSimulator()
sim.load_recipes('data/recipes.json')
sim.setup_from_recipes(sim.select_recipes(count=4))

sim.start_cooking('clearwater_fish', 'skillet')
sim.tick(4.5)
sim.move_to_assembly('skillet')
sim.add_condiment('hearthspice')

print_fancy_state(sim)
```

---

## 5. 常见调试场景

### 5.1 调试订单不出现

```python
def debug_order_generation():
    sim = GameSimulator()
    sim.load_recipes('data/recipes.json')
    sim.setup_from_recipes(sim.select_recipes(count=4))
    
    print("检查订单生成...")
    print(f"时间: {sim.time}")
    print(f"订单槽位: {sim.state.orders}")
    print(f"游戏结束: {sim.is_game_over()}")
    
    for t in range(0, 20, 1):
        events = sim.tick(1.0)
        new_orders = [e for e in events if e.event_type.name == 'ORDER_APPEARED']
        if new_orders:
            print(f"t={sim.time:.1f}s: 订单生成 - {new_orders[0].details}")
        else:
            print(f"t={sim.time:.1f}s: 无新订单")
```

### 5.2 调试烹饪时间

```python
def debug_cooking_time():
    sim = GameSimulator()
    sim.load_recipes('data/recipes.json')
    sim.setup_from_recipes(sim.select_recipes(count=4))
    
    # 查看每个食材的烹饪时间
    print("=== 食材烹饪时间 ===")
    for recipe in sim.recipes.values():
        print(f"\n{recipe.name}:")
        for ing in recipe.ingredients:
            print(f"  {ing.name} on {ing.cooker_type}: {ing.duration}s")
    
    # 测试实际烹饪
    sim.start_cooking('clearwater_fish', 'skillet')
    print(f"\n开始烹饪 clearwater_fish")
    print(f"预计完成时间: {sim.get_cooker_state('skillet').done_at}")
    
    while sim.time < 5:
        sim.tick(0.5)
        cooker = sim.get_cooker_state('skillet')
        print(f"t={sim.time:.1f}s: busy={cooker.busy}, done_at={cooker.done_at}")
```

### 5.3 调试订单提交失败

```python
def debug_serve_order():
    sim = GameSimulator()
    sim.load_recipes('data/recipes.json')
    sim.setup_from_recipes(sim.select_recipes(count=4))
    
    # 制造一个订单
    sim.tick(5.0)
    order = sim.get_order(0)
    print(f"订单: {order.recipe.name}")
    print(f"需要食材: {[ing.name for ing in order.recipe.ingredients]}")
    print(f"需要调料: {order.recipe.condiments}")
    
    # 尝试提交（应该失败，因为组装站是空的）
    result = sim.serve_order(0)
    print(f"\n提交结果: {result.success}")
    print(f"错误信息: {result.error_message}")
    
    # 正确流程
    for ing in order.recipe.ingredients:
        sim.start_cooking(ing.name, ing.cooker_type)
    
    sim.tick(5.0)  # 等待烹饪完成
    
    for ing in order.recipe.ingredients:
        sim.move_to_assembly(ing.cooker_type)
    
    for condiment in order.recipe.condiments:
        for _ in range(order.recipe.condiments[condiment]):
            sim.add_condiment(condiment)
    
    print(f"\n组装站状态:")
    print(f"  食材: {[ing[0] for ing in sim.state.assembly.ingredients]}")
    print(f"  调料: {sim.state.assembly.condiments}")
    print(f"  完成: {sim.state.assembly.is_complete}")
    
    result = sim.serve_order(0)
    print(f"\n提交结果: {result.success}")
    if result.success:
        print(f"得分: {result.score_earned}")
```

---

## 6. 性能测试

```python
import time

def benchmark(n_games=100):
    """基准测试：模拟多局游戏的速度"""
    total_time = 0
    
    for i in range(n_games):
        start = time.time()
        
        sim = GameSimulator()
        sim.load_recipes('data/recipes.json')
        sim.setup_from_recipes(sim.select_recipes(count=4))
        
        while not sim.is_game_over():
            sim.tick(0.5)
        
        total_time += time.time() - start
    
    avg_time = total_time / n_games
    print(f"平均每局游戏耗时: {avg_time*1000:.2f}ms")
    print(f"每秒可模拟局数: {1/avg_time:.1f}")

benchmark(10)
```

---

## 7. 调试技巧总结

| 场景 | 方法 |
|------|------|
| 查看操作是否成功 | `result.success`, `result.error_message` |
| 查看发生了什么 | `sim.events` 遍历 |
| 逐步查看状态变化 | `sim.tick(0.1)` 小步推进 |
| 可视化状态 | `print_fancy_state(sim)` |
| 对比操作前后 | `before_state.copy()` + 比较 |
| 断点调试 | `input()` 暂停等待输入 |
| 性能测试 | `time.time()` 计时 |

---

## 8. 快速调试脚本模板

```python
"""快速调试脚本模板"""
from hawarma.env_simulator import GameSimulator

# 初始化
sim = GameSimulator()
sim.enable_debug(True)
sim.load_recipes('data/recipes.json')

# 选菜单（固定种子方便复现）
sim.setup_from_recipes(sim.select_recipes(count=4, random_seed=42))

# === 在这里添加你的调试代码 ===
# 例如：
sim.start_cooking('clearwater_fish', 'skillet')
sim.tick(4.5)
print(sim.state)

# ===========================================
print(f"\n事件数: {len(sim.events)}")
```

复制以上模板，修改调试代码即可快速测试。