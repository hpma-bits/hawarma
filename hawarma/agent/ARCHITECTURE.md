# hawarma/agent 目录架构

## 📁 目录概述

此目录包含烹饪 Agent 的决策逻辑，负责在每个决策点选择最优动作。

## ⚠️ 重要提示

**一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**

## 📄 文件列表

### `__init__.py`
- **地位**: 包初始化文件
- **功能**: 导出所有 Agent 类和动作类型

### `agent.py`
- **地位**: 统一烹饪 Agent
- **状态**: ✅ 完成（含停滞检测和超时清理）
- **功能**:
  - 基于优先级的贪心策略决策
  - 支持与 GameEnvironment（真实游戏）交互
  - 7级优先级动作选择
  - 调料追踪、订单优先级排序（rush 优先）
  - **停滞检测**：`step_with_diagnostics()` 追踪连续无行动时间，5秒后输出诊断日志
  - **组装站超时清理**：`_check_stale_assembly()` 检测食材齐全但调料缺失超过15秒的情况，自动清空
  - **配方推断**：`_infer_recipe_from_assembly()` 从食材反推目标配方
- **输入**: GameEnvironment 实例、配方列表
- **输出**: 动作对象供执行器执行
- **关键类**: `CookingAgent`, 各种 `Action` 子类

---

## 🎯 Agent 决策机制详解

### 优先级决策模型

Agent 采用 **7级优先级贪心策略**，在每个决策点按优先级从高到低尝试动作：

```
优先级 1: 送餐 (ServeOrderAction)
    ↓ (如果无法送餐)
优先级 2: 清理过期食材 (ClearCookerAction)
    ↓ (如果没有过期食材)
优先级 3: 从灶台移到组装站 (MoveToAssemblyAction)
    ↓ (如果灶台没有完成的食材)
优先级 4: 开始烹饪 (CookAction)
    ↓ (如果所有灶台都在忙)
优先级 5: 添加调料 (AddCondimentAction)
    ↓ (如果无需调料)
优先级 6: 多余食材存入库存 (MoveToStockpileAction)
    ↓ (如果没有多余食材)
优先级 7: 从库存取用到组装站 (PullFromStockpileAction)
    ↓ (如果库存没有需要的食材)
```

### 设计原理

1. **送餐优先**：完成订单是最终目标，一旦组装站有匹配订单的完整菜品立即送餐
2. **清理优先**：过期食材占用灶台资源，必须优先清理，防止阻塞烹饪
3. **移动优先于烹饪**：已完成的食材应尽快移到组装站，释放灶台
4. **烹饪优先于调味**：灶台是异步的，尽早开始烹饪可以让灶台更早工作；调味可以在烹饪期间进行
5. **库存缓冲**：多余的完成食材存入库存，以备后续订单使用
6. **库存取用**：当库存有需要的食材时，直接取用比重新烹饪更快

### 动作类型定义

```python
@dataclass
class CookAction(Action):
    """烹饪动作"""
    ingredient: str      # 食材名称
    cooker: str          # 灶台名称
    duration: float      # 烹饪时长（秒）
    order_id: Optional[int] = None  # 关联订单ID

@dataclass
class MoveToAssemblyAction(Action):
    """移动到组装站"""
    cooker: str
    order_id: Optional[int] = None

@dataclass
class MoveToStockpileAction(Action):
    """移动到库存"""
    cooker: str
    slot: str

@dataclass
class PullFromStockpileAction(Action):
    """从库存取用"""
    slot: str
    ingredient: str

@dataclass
class AddCondimentAction(Action):
    """添加调料"""
    condiment: str

@dataclass
class ServeOrderAction(Action):
    """送餐"""
    slot_idx: int

@dataclass
class ClearCookerAction(Action):
    """清理灶台"""
    cooker: str
```

---

## 🔄 Agent 与环境交互流程

### 单步决策流程

```python
def step(self) -> Optional[Action]:
    """
    单步决策：选择并执行最优动作
    
    Returns:
        执行的动作，如果没有动作可执行则返回 None
    """
    # 1. 送餐（最高优先级）
    if action := self._try_serve():
        return action
    
    # 2. 从灶台移到组装站
    if action := self._try_move_to_assembly():
        return action
    
    # 3. 开始烹饪（让灶台尽早开始工作）
    if action := self._try_start_cooking():
        return action
    
    # 4. 添加调料（可在烹饪期间进行）
    if action := self._try_add_condiment():
        return action
    
    # 5. 从库存取用到组装站
    if action := self._try_pull_from_stockpile():
        return action
    
    # 6. 清理过期食材
    if action := self._try_clear_expired():
        return action
    
    # 7. 多余食材存入库存
    if action := self._try_store_to_stockpile():
        return action
    
    return None
```

### 关键判断逻辑

#### 送餐判断 (`_try_serve`)
```python
def _try_serve(self) -> Optional[ServeOrderAction]:
    # 1. 检查是否在动画窗口（防止冲突）
    if self.env.is_in_animation_window():
        return None
    
    # 2. 检查组装站是否有食材
    assembly = self.env.assembly
    if not assembly.ingredients:
        return None
    
    # 3. 遍历订单，找到匹配的订单
    for slot_idx, order in enumerate(self.env.orders):
        if order is None:
            continue
        
        # 4. 检查配方是否匹配
        recipe = self._recipe_by_slug.get(order.recipe_slug)
        if recipe and self._ingredients_match(assembly.ingredients, recipe):
            return ServeOrderAction(slot_idx=slot_idx)
    
    return None
```

#### 烹饪判断 (`_try_start_cooking`)
```python
def _try_start_cooking(self) -> Optional[CookAction]:
    # 1. 获取空闲灶台
    free_cookers = self._get_free_cookers()
    if not free_cookers:
        return None
    
    # 2. 获取需要烹饪的食材（按优先级）
    to_cook = self._get_ingredients_to_cook()
    
    # 3. 优先烹饪订单需要的食材（按需响应）
    for ing_name, cooker_type in to_cook:
        if cooker_type in free_cookers:
            # 检查是否已在烹饪
            if self._is_cooking(ing_name):
                continue
            # 检查库存是否有（优先使用库存）
            if self._has_in_stockpile(ing_name):
                continue
            # 开始烹饪
            return CookAction(...)
    
    # 4. 不预烹饪 - 按需响应策略更可靠
    return None
```

---

## 📊 状态查询接口

Agent 通过 `self.env` 访问 GameEnvironment 提供的状态接口：

### 环境状态
- `self.env.time` - 当前游戏时间（秒）
- `self.env.orders` - 订单列表（4个槽位）
- `self.env.cookers` - 灶台状态字典
- `self.env.assembly` - 组装站状态
- `self.env.stockpile` - 库存状态字典

### 状态判断方法
- `self.env.is_in_animation_window()` - 是否在动画窗口期
- `self.env.is_game_over()` - 游戏是否结束
- `self.env.is_cooking_done(cooker)` - 灶台烹饪是否完成

### 辅助查询方法
- `self._get_free_cookers()` - 获取空闲灶台列表
- `self._get_needed_ingredients()` - 获取当前订单需要的食材
- `self._is_cooking(ingredient)` - 检查食材是否正在烹饪
- `self._has_in_stockpile(ingredient)` - 检查库存是否有食材
- `self._infer_recipe_from_assembly()` - 根据组装站食材推断匹配的配方

---

## 🔧 配方推断机制

### 问题背景

当 `assembly.target_recipe_slug` 为 `None` 时（可能由状态同步延迟或边缘操作序列导致），`_try_add_condiment()` 和 `_try_serve()` 需要能够根据已有食材推断出目标配方，避免 Agent 决策瘫痪。

### 推断策略

```python
def _infer_recipe_from_assembly(self) -> Optional[str]:
    """根据组装站食材推断匹配的配方"""
    assembly = self.env.assembly
    if not assembly.ingredients:
        return None
    
    assembly_names = [ing[0] if isinstance(ing, tuple) else ing for ing in assembly.ingredients]
    
    for _, order in self._prioritized_orders():
        recipe = self._recipe_by_slug.get(order.recipe_slug)
        if recipe:
            raw = self._get_recipe_attr(recipe, 'raw_ingredients', [])
            if all(ing in raw for ing in assembly_names):
                return order.recipe_slug
    return None
```

**设计原则**：
- 按订单优先级遍历（rush 优先、timeout 近的优先）
- 只要组装站所有食材都属于某个订单的配方，即认为匹配
- 返回第一个匹配的订单配方

### 使用场景

| 方法 | 何时使用推断 |
|------|-------------|
| `_try_add_condiment()` | `target_recipe_slug` 为 None 时，推断后检查食材是否齐全并添加调料 |
| `_try_serve()` | 不依赖推断，直接遍历订单匹配（已有容错） |

### 与环境层推断的关系

环境层（`GameEnvironment`）在 `pull_from_stockpile()` 和 `add_to_assembly()` 中也做推断，这是**预防层**。Agent 层的推断是**恢复层**。两层配合确保即使环境层推断失败，Agent 仍能正常工作。

---

## 🎮 预烹饪策略（已验证无效）

> **经验教训**：预烹饪策略在实际测试中效果不佳，预烹饪的食材可能与订单不匹配，反而降低性能。建议使用按需响应策略。

### ~~高频食材预存配置~~（不推荐使用）

```python
# 以下配置仅供参考，实际测试表明预烹饪会降低性能
DEFAULT_STOCKPILE = [
    ("creamfield_rice", "pot", 2.0),      # 米饭，pot灶台，2秒
    ("clearwater_fish", "oven", 3.0),     # 鱼，oven灶台，3秒
    ("wild_mushroom", "skillet", 2.0),    # 蘑菇，skillet灶台，2秒
]
```

### ~~预烹饪触发条件~~（不推荐使用）

1. 所有订单需要的食材都已在烹饪或库存中
2. 仍有空闲灶台
3. 库存中某食材数量 < `PRECOOK_THRESHOLD`（默认2）

### 测试结果

| 策略 | 完成订单 | 超时率 | 效果 |
|------|----------|--------|------|
| 按需响应（推荐） | 13.4个 | 2.2% | 基准 |
| 预烹饪到assembly | 失败 | 失败 | -30% |
| 预烹饪到stockpile | 13.1个 | 5% | -2% |

**结论**：在不确定的环境中，按需响应比预测更可靠。

---

## 📈 统计信息

Agent 维护以下统计数据：

```python
self.stats = {
    "orders_served": 0,      # 已完成订单数
    "total_score": 0,        # 总得分
    "orders_timeout": 0,     # 超时订单数
    "actions_taken": 0,      # 执行动作数
}
```

通过 `get_stats()` 方法获取包含游戏时间的完整统计：

```python
def get_stats(self) -> dict:
    return {
        "time": self.env.time,
        "orders_served": self.stats["orders_served"],
        "total_score": self.stats["total_score"],
        "orders_timeout": self.stats["orders_timeout"],
        "actions_taken": self.stats["actions_taken"],
    }
```

---

## 🔗 与其他模块的关系

```
RealGameBridge (bridge/bridge.py)
    │
    ├─→ CookingAgent (agent/agent.py) ← 本模块
    │       │
    │       ├─→ GameEnvironment (bridge/environment.py) - 读取状态
    │       └─→ 返回 Action 对象
    │
    └─→ _execute_action() - 执行 Agent 返回的动作
            │
            ├─→ UIRunner - 执行 UI 操作
            └─→ GameEnvironment - 更新状态
```
