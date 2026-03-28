# Cooking Agent 设计文档

## 1. 概述

设计一个高效的自动烹饪 agent，在 90 秒游戏时间内完成尽可能多的订单。

### 核心目标
- 最大化订单完成数量
- 避免订单超时（rush 40s / normal 70s）
- 最大化灶台利用率（4 个灶台并行）
- 最小化组装站空闲时间

### 关键瓶颈
| 资源 | 数量 | 瓶颈影响 |
|------|------|----------|
| 灶台 | 4 | 决定并行烹饪能力 |
| 组装站 | 1 | 主要瓶颈，一次只能处理一份菜品 |
| 库存槽 | 3 | 限制可预存的食材种类 |

---

## 2. Agent 架构

```
CookingAgent
├── 感知层 (Perception)
│   ├── 观察订单队列（4 slots）
│   ├── 观察灶台状态（4 cookers）
│   ├── 观察组装站状态
│   └── 观察库存状态（3 slots）
│
├── 决策层 (Decision)
│   ├── OrderScheduler - 订单调度器
│   │   └── 计算订单优先级，决定处理顺序
│   ├── CookerPlanner - 灶台规划器
│   │   └── 为空闲灶台分配烹饪任务
│   └── StockpileManager - 库存管理器
│       └── 决定库存补货和取用策略
│
└── 执行层 (Execution)
    └── 按优先级执行动作序列
```

---

## 3. 决策策略

### 3.1 订单优先级计算

```python
def calculate_order_priority(order: Order, current_time: float) -> float:
    """
    计算订单优先级得分（越高越优先）
    
    公式: priority = urgency × complexity_factor
    """
    remaining = order.timeout_at - current_time
    
    # 紧急度：剩余时间越少越紧急
    if remaining <= 0:
        return float('inf')  # 已超时，最高优先级（但已无法完成）
    
    urgency = 1.0 / remaining
    
    # Rush 倍率
    rush_multiplier = 2.5 if order.is_rush else 1.0
    
    # 复杂度：双食材订单略微加分（需要更多资源）
    complexity = 1.0 + 0.1 * len(order.recipe.ingredients)
    
    return urgency * rush_multiplier * complexity
```

**优先级排序规则**：
| 优先级 | 条件 | 处理策略 |
|--------|------|----------|
| P0 | Rush 剩余 <15s | 立即处理，必要时占用所有空闲灶台 |
| P1 | Normal 剩余 <25s | 优先分配灶台 |
| P2 | Rush 剩余 >15s | 尽快开始 |
| P3 | Normal 剩余 >25s | 正常处理 |

### 3.2 灶台分配算法

```python
def assign_cookers(orders: list[Order], free_cookers: list[str], 
                   stockpile: dict) -> list[CookAction]:
    """
    为空闲灶台分配烹饪任务
    
    策略：
    1. 按优先级排序订单
    2. 为每个空闲灶台找到最紧急订单需要的食材
    3. 优先使用库存中的食材（跳过烹饪）
    4. 双食材订单同时分配两个灶台
    """
    actions = []
    
    # 按优先级排序
    sorted_orders = sort_by_priority(orders)
    
    for order in sorted_orders:
        for ingredient in order.recipe.ingredients:
            # 如果食材已在组装站，跳过
            if ingredient_in_assembly(ingredient):
                continue
            
            # 如果库存有，直接取用
            if stockpile_has(ingredient):
                actions.append(PullFromStockpile(ingredient))
                continue
            
            # 找到需要的灶台
            cooker = ingredient.cooker_type
            
            # 如果灶台空闲，分配烹饪
            if cooker in free_cookers:
                actions.append(CookIngredient(ingredient, cooker))
                free_cookers.remove(cooker)
    
    return actions
```

### 3.3 库存策略

```python
# 高频食材配置（根据配方分析）
HIGH_FREQUENCY_INGREDIENTS = [
    ("creamfield_rice", "pot", 2.0),      # 出现2次，短时
    ("clearwater_fish", "oven", 3.0),     # 出现2次
    ("vining_marjoram", "grill", 4.0),    # 出现2次
    ("pliant_pasta", "pot", 3.0),         # 出现2次
]

def stockpile_strategy(state: GameState) -> list[Action]:
    """
    库存管理策略
    
    规则：
    1. 空闲灶台优先补货低库存的高频食材
    2. 紧急订单需要的食材优先从库存取用
    3. 长时食材（4-5s）优先预存
    """
    actions = []
    
    for ing_name, cooker, duration in HIGH_FREQUENCY_INGREDIENTS:
        slot = get_stockpile_slot(state, ing_name)
        
        # 库存不足时补货
        if slot is None or slot.count <= 1:
            if cooker_is_free(state, cooker):
                actions.append(CookIngredient(ing_name, cooker))
    
    return actions
```

---

## 4. 完整行动循环

```
每 0.5 秒执行一次决策循环：

1. 感知状态
   ├── 获取当前订单列表
   ├── 获取灶台状态
   ├── 获取组装站状态
   └── 获取库存状态

2. 检查紧急情况
   ├── 是否有订单即将超时（<10s）？
   └── 是否有灶台食材即将过期（>3s 未取走）？

3. 决策（按优先级）
   ├── a) 送餐：组装站完成 → 立即送餐
   ├── b) 组装：灶台完成 → 移到组装站
   ├── c) 调味：食材齐全 → 添加调料
   ├── d) 库存取用：库存有食材 → 取出到组装站
   ├── e) 烹饪：空闲灶台 → 开始烹饪
   └── f) 清理：过期食材 → 丢弃

4. 执行动作
   └── 执行最高优先级的动作

5. 等待下一轮
```

---

## 5. 特殊场景处理

### 5.1 同灶台配方（Simple Seared Scallops）

```python
def handle_same_cooker_recipe(order):
    """
    处理需要同一灶台的双食材配方
    
    Simple Seared Scallops:
    - whiteshore_scallop on grill (2s)
    - vining_marjoram on grill (4s)
    
    策略：先烹饪短时食材，再烹饪长时食材
    """
    # 先烹饪 2s 食材
    cook("whiteshore_scallop", "grill")
    wait(2.0)
    move_to_assembly("grill")
    
    # 再烹饪 4s 食材
    cook("vining_marjoram", "grill")
    wait(4.0)
    move_to_assembly("grill")
```

### 5.2 组装站被占用时的处理

```python
def handle_assembly_busy(ingredient_from_cooker):
    """
    组装站被占用时的临时处理
    
    策略：
    1. 如果是当前订单需要的食材 → 等待
    2. 如果不是 → 存入库存
    3. 如果库存满 → 丢弃（最后手段）
    """
    if ingredient_needed_for_current_order(ingredient_from_cooker):
        # 等待组装站释放
        return WaitAction()
    
    # 存入库存
    if stockpile_has_space(ingredient_from_cooker):
        return MoveToStockpile(ingredient_from_cooker)
    
    # 丢弃
    return MoveToTrash(ingredient_from_cooker)
```

### 5.3 多订单共享食材

```python
def handle_shared_ingredients(orders):
    """
    处理多个订单共享相同食材的情况
    
    例如：Gilded Shore Risotto 和 Woodland Mushroom Risotto 
    都需要 creamfield_rice
    
    策略：
    1. 识别共享食材
    2. 优先烹饪共享食材（一次烹饪满足多个订单）
    3. 保持共享食材库存充足
    """
    shared = find_shared_ingredients(orders)
    
    for ingredient in shared:
        if stockpile_count(ingredient) < 2:
            # 补充共享食材库存
            cook(ingredient)
```

---

## 6. 伪代码实现

```python
class CookingAgent:
    def __init__(self, simulator: GameSimulator):
        self.sim = simulator
        self.target_recipe = None  # 当前正在组装的配方
    
    def run(self):
        """主循环"""
        while not self.sim.is_game_over():
            self.step()
            self.sim.tick(0.5)  # 每0.5秒决策一次
    
    def step(self):
        """单步决策"""
        state = self.sim.state
        
        # 1. 检查送餐（最高优先级）
        if self.can_serve():
            self.serve_order()
            return
        
        # 2. 检查调味
        if self.can_season():
            self.add_condiment()
            return
        
        # 3. 检查移动到组装站
        action = self.check_move_to_assembly()
        if action:
            action.execute()
            return
        
        # 4. 检查从库存取用
        action = self.check_pull_from_stockpile()
        if action:
            action.execute()
            return
        
        # 5. 检查烹饪
        action = self.check_start_cooking()
        if action:
            action.execute()
            return
        
        # 6. 检查清理过期食材
        action = self.check_clear_expired()
        if action:
            action.execute()
    
    def check_start_cooking(self) -> Action | None:
        """为空闲灶台分配烹饪任务"""
        orders = self.get_sorted_orders()
        free_cookers = self.get_free_cookers()
        
        for order in orders:
            for ing in order.recipe.ingredients:
                if self.ingredient_ready(ing):
                    continue  # 已在组装站或库存可取
                
                cooker = ing.cooker_type
                if cooker in free_cookers:
                    return CookIngredient(ing.name, cooker)
        
        # 空闲时补货高频食材
        return self.stockpile_refill(free_cookers)
    
    def get_sorted_orders(self) -> list[Order]:
        """按优先级排序订单"""
        orders = [o for o in self.sim.state.orders if o]
        current_time = self.sim.time
        
        return sorted(orders, key=lambda o: self.priority(o, current_time), reverse=True)
    
    def priority(self, order: Order, t: float) -> float:
        """计算订单优先级"""
        remaining = order.timeout_at - t
        if remaining <= 0:
            return -1  # 已超时，跳过
        
        urgency = 1.0 / remaining
        rush_mult = 2.5 if order.is_rush else 1.0
        
        return urgency * rush_mult
```

---

## 7. 性能优化

### 7.1 预测性烹饪

```python
def predictive_cooking(self):
    """
    根据订单生成规律（4秒间隔）预测即将出现的订单
    
    策略：
    - 在空闲时预先烹饪高频食材
    - 保持库存中 3 种高频食材各 2-3 份
    """
    # 分析历史订单，计算各配方出现频率
    # 优先预存出现频率高的食材
```

### 7.2 并行最大化

```python
def maximize_parallelism(self):
    """
    最大化 4 个灶台的并行利用率
    
    策略：
    - 空闲灶台立即分配任务
    - 双食材订单同时启动两个灶台
    - 短时食材填充长时食材的等待间隙
    """
    free_cookers = self.get_free_cookers()
    
    if len(free_cookers) >= 2:
        # 尝试为双食材订单分配两个灶台
        self.try_assign_dual_cook(free_cookers)
    
    # 剩余空闲灶台补充库存
    for cooker in free_cookers:
        self.stockpile_refill_single(cooker)
```

---

## 8. 预期性能

| 指标 | 预期值 | 说明 |
|------|--------|------|
| 订单完成数 | 12-15 | 基于 90s / 平均 6s 每单 |
| 灶台利用率 | >80% | 4 灶台并行 |
| 组装站利用率 | >70% | 快速周转 |
| 订单超时率 | <5% | 优先处理紧急订单 |

---

## 9. 实现计划

| 阶段 | 内容 | 文件 |
|------|------|------|
| 1 | 基础 Agent 框架 | `hawarma/agent/base_agent.py` |
| 2 | 订单优先级策略 | `hawarma/agent/order_scheduler.py` |
| 3 | 灶台规划器 | `hawarma/agent/cooker_planner.py` |
| 4 | 库存管理器 | `hawarma/agent/stockpile_manager.py` |
| 5 | 测试与调优 | `tests/test_agent.py` |

---

## 10. 总结

高效 Agent 的核心策略：

1. **优先级驱动**：Rush 订单和即将超时的订单优先处理
2. **并行最大化**：4 个灶台尽可能同时工作
3. **库存预存**：高频食材保持充足库存，减少临时烹饪
4. **快速周转**：组装完成后立即送餐，触发新订单
5. **预测烹饪**：空闲时预存食材，应对未来订单

关键成功因素：**最小化等待时间，最大化资源利用率**
