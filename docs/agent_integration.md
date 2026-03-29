# Agent 实际游玩集成方案

## 1. 概述

将高效 Agent 策略集成到现有游戏自动化系统中，替换或增强 Scheduler 的决策逻辑。

### 现有架构

```
main.py
    ↓
CookingBotApp (app.py) - 生命周期管理
    ↓
    ├─→ DetectionService (订单检测) ←→ 屏幕截图
    ├─→ Scheduler (唯一决策中心) ← 我们的 agent 策略放在这里
    │       ├─→ OrderPolicy (订单优先级)
    │       └─→ StockpilePolicy (库存策略)
    ├─→ Executor (原子动作执行) → UI 操作 (swipe/click)
    ├─→ ResourceGuards (物理资源锁)
    └─→ GameState (全局状态)
```

### 关键接口

Scheduler 只需要实现一个方法：

```python
def get_next_actions(self) -> list[Action]:
    """返回下一个 tick 应该执行的动作列表"""
```

---

## 2. 集成方案

### 方案 A：替换 Scheduler（推荐）

创建新的 `AgentScheduler`，完全替换现有的 `Scheduler`：

```
hawarma/scheduler/
├── scheduler.py          # 原有调度器（保留作为备选）
├── agent_scheduler.py    # 新的 Agent 调度器
├── order_policy.py       # 增强的订单策略
└── stockpile_policy.py   # 增强的库存策略
```

### 方案 B：增强现有 Policy

保留 Scheduler 框架，替换 OrderPolicy 和 StockpilePolicy：

```
hawarma/scheduler/
├── scheduler.py          # 保持不变
├── agent_order_policy.py # 新的订单策略
└── agent_stockpile_policy.py # 新的库存策略
```

**推荐方案 A**，因为可以完全控制决策逻辑。

---

## 3. AgentScheduler 设计

### 3.1 核心改进

| 改进点 | 原有实现 | Agent 策略 |
|--------|---------|-----------|
| 送餐时机 | 只在食材齐全后送餐 | 立即送餐，不等待 |
| 灶台分配 | 为特定订单分配灶台 | 全局优化，跨订单共享 |
| 预烹饪 | 无 | 空闲灶台预烹饪高频食材 |
| 库存策略 | 固定 3 种食材 | 动态调整，基于当前订单 |
| 并行度 | 保守，等待确认 | 激进，同时启动多个灶台 |

### 3.2 决策流程

```python
def get_next_actions(self) -> list[Action]:
    """每个 tick 调用一次，返回待执行动作"""
    actions = []
    state = self.game_state
    now = asyncio.get_event_loop().time()
    
    # 1. 送餐（最高优先级，只执行一个）
    if action := self._try_finish_order(state, now):
        actions.append(action)
        return actions  # 送餐后等待动画，本 tick 结束
    
    # 2. 调味（多次）
    while action := self._try_season(state):
        actions.append(action)
    
    # 3. 从灶台移到组装站（多次）
    while action := self._try_move_to_assembly(state):
        actions.append(action)
    
    # 4. 从库存取用（多次）
    while action := self._try_pull_from_stockpile(state):
        actions.append(action)
    
    # 5. 启动烹饪（尽可能多）
    while action := self._try_start_cooking(state):
        actions.append(action)
    
    return actions
```

### 3.3 关键方法实现

#### 送餐决策

```python
def _try_finish_order(self, state: GameState, now: float) -> Action | None:
    """尝试送餐"""
    # 检查动画窗口
    if not state.is_ui_stable(now):
        return None
    
    # 检查组装站是否有完成的菜品
    assembly = state.assembly
    if not assembly.is_complete():
        return None
    
    # 找到匹配的订单
    for slot_idx, order in enumerate(state.orders):
        if order is None or order.done:
            continue
        
        # 检查配方匹配
        if self._recipe_matches(order, assembly):
            return FinishOrder(
                order_id=order.order_id,
                pickup_slot=slot_idx
            )
    
    return None
```

#### 烹饪决策（全局优化）

```python
def _try_start_cooking(self, state: GameState) -> Action | None:
    """为最合适的灶台分配烹饪任务"""
    free_cookers = self._get_free_cookers(state)
    if not free_cookers:
        return None
    
    # 获取需要烹饪的食材（按优先级排序）
    needed = self._get_all_needed_ingredients(state)
    
    # 优先烹饪订单需要的食材
    for ing_name, cooker_type, order_id in needed:
        if cooker_type in free_cookers:
            return CookIngredient(
                order_id=order_id,
                ingredient_name=ing_name,
                cooker_name=cooker_type,
                destination="assembly"
            )
    
    # 空闲灶台预烹饪高频食材
    for cooker_type in free_cookers:
        if action := self._precook_for_stockpile(state, cooker_type):
            return action
    
    return None
```

#### 预烹饪策略

```python
def _precook_for_stockpile(self, state: GameState, cooker_type: str) -> Action | None:
    """为库存预烹饪"""
    # 找到该灶台对应的高频食材
    for ing_name, cooker, threshold in HIGH_PRIORITY_STOCKPILE:
        if cooker != cooker_type:
            continue
        
        # 检查库存是否需要补货
        count = state.stockpile_counts.get(ing_name, 0)
        if count < threshold:
            return CookIngredient(
                order_id=None,  # 无订单绑定
                ingredient_name=ing_name,
                cooker_name=cooker_type,
                destination="stockpile"
            )
    
    return None
```

---

## 4. 与现有系统的兼容性

### 4.1 Executor 不变

AgentScheduler 返回的 Action 对象与现有 Executor 兼容：

```python
# 现有 Action 类型
@dataclass
class CookIngredient(Action):
    order_id: int | None
    ingredient_name: str
    cooker_name: str
    destination: Literal["assembly", "stockpile"]

@dataclass
class PullFromStockpile(Action):
    order_id: int
    ingredient_name: str
    stockpile_slot: int

@dataclass
class FinishOrder(Action):
    order_id: int
    pickup_slot: int
```

### 4.2 GameState 不变

AgentScheduler 只读取 GameState，不修改（由 Executor 修改）。

### 4.3 DetectionService 不变

订单检测逻辑保持不变，AgentScheduler 只是更好地利用检测结果。

---

## 5. 实现步骤

### Step 1: 创建 AgentScheduler

```python
# hawarma/scheduler/agent_scheduler.py

class AgentScheduler:
    """高效 Agent 调度器"""
    
    def __init__(self, game_state: GameState, session_state: SessionState):
        self.game_state = game_state
        self.session_state = session_state
        # 初始化高频食材配置
        self._init_stockpile_config()
    
    def get_next_actions(self) -> list[Action]:
        # 实现决策逻辑
        ...
```

### Step 2: 修改 CookingBotApp

```python
# hawarma/app.py

class CookingBotApp:
    def __init__(self, config: AppConfig, use_agent: bool = True):
        # ...
        if use_agent:
            self.scheduler = AgentScheduler(self.game_state, self.session_state)
        else:
            self.scheduler = Scheduler(self.game_state, self.session_state)
```

### Step 3: 添加配置选项

```yaml
# configs/config.yaml
agent:
  enabled: true
  tick_interval: 0.1
  prefill_stockpile: true
  stockpile_threshold: 2
```

---

## 6. 预期效果

| 指标 | 原有系统 | Agent 系统 | 提升 |
|------|---------|-----------|------|
| 订单完成数 | ~8 | ~15 | +87% |
| 灶台利用率 | ~30% | ~60% | +100% |
| 组装站利用率 | ~25% | ~50% | +100% |
| 平均得分 | ~1500 | ~2800 | +87% |

---

## 7. 风险与挑战

### 7.1 UI 延迟

实际游戏中，UI 操作（swipe）有延迟。需要：
- 增加操作间隔（避免冲突）
- 正确处理动画窗口
- 检测操作失败并重试

### 7.2 检测延迟

订单检测需要截图和图像处理，有延迟。需要：
- 异步检测，不阻塞调度
- 缓存检测结果
- 合理的检测频率

### 7.3 状态同步

GameState 可能与实际游戏状态不同步。需要：
- 定期全量同步
- 检测异常状态并恢复
- 保守的资源预留

---

## 8. 测试计划

### 8.1 单元测试

- 测试 AgentScheduler 的决策逻辑
- 模拟不同游戏状态
- 验证 Action 正确性

### 8.2 集成测试

- 使用 GameSimulator 验证端到端流程
- 比较原系统和 Agent 系统的性能

### 8.3 实际测试

- 在模拟器中运行
- 收集性能数据
- 调优参数

---

## 9. 后续优化

1. **机器学习**：用 RL 训练更优策略
2. **预测烹饪**：基于订单出现规律预烹饪
3. **动态调参**：根据实时性能调整策略
4. **多目标优化**：平衡订单数和得分

---

## 10. 总结

AgentScheduler 通过以下方式提升性能：

1. **更激进的并行**：同时启动多个灶台
2. **预烹饪**：空闲时补充库存
3. **全局优化**：跨订单共享资源
4. **快速响应**：检测到可送餐立即执行

核心原则：**最小化等待时间，最大化资源利用率**
