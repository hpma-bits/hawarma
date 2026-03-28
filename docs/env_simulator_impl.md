# env_simulator 实现文档

## 1. 概述

游戏环境模拟器是一个轻量级、确定性的状态机，模拟烹饪游戏规则。它是游戏规则的"真理之源"——如果模拟器拒绝某个操作，说明该操作违反了游戏规则。

### 核心原则
- **纯状态机**：无副作用，无 UI 自动化
- **确定性**：相同操作总是产生相同结果
- **严格验证**：严格执行所有游戏规则
- **可观察**：暴露完整状态供代理感知

## 2. 架构

### 2.1 核心组件

```
GameSimulator
├── 状态
│   ├── orders: list[Order | None]       # 4 个订单槽位
│   ├── cookers: dict[str, CookerState]    # 4 个灶台
│   ├── assembly: AssemblyState            # 1 个组装站
│   ├── stockpile: dict[str, StockpileSlot]  # 3 个库存槽位
│   └── time: float                        # 模拟时钟
├── 配置
│   └── recipes: dict[str, Recipe]         # 所有配方
└── 历史
    └── events: list[Event]                # 事件历史
```

### 2.2 数据结构

#### Order（订单）
```python
@dataclass
class Order:
    order_id: int
    recipe: Recipe
    is_rush: bool               # rush 订单时限更短
    created_at: float           # 订单出现时间
    timeout_at: float           # 订单过期时间
    served_at: Optional[float]  # 订单完成时间
    condiments_applied: dict[str, int]  # 已添加的调料
```

#### CookerState（灶台状态）
```python
@dataclass
class CookerState:
    busy: bool = False
    ingredient_name: Optional[str] = None
    cooker_type: Optional[str] = None
    started_at: Optional[float] = None
    done_at: Optional[float] = None      # 烹饪完成时间
    expired_at: Optional[float] = None   # 食材过期时间（done_at + 5s）
```

#### AssemblyState（组装站状态）
```python
@dataclass
class AssemblyState:
    target_recipe: Optional[Recipe] = None
    ingredients: list[tuple[str, str, float]]  # (食材名, 灶台类型, 添加时间)
    condiments: dict[str, int] = field(default_factory=dict)
```

#### StockpileSlot（库存槽位）
```python
@dataclass
class StockpileSlot:
    ingredient_name: Optional[str] = None
    cooker_type: Optional[str] = None
    count: int = 0  # 最多 5 份
```

### 2.3 事件系统

```python
class EventType(Enum):
    ORDER_APPEARED = auto()     # 新订单出现
    ORDER_TIMEOUT = auto()      # 订单超时
    ORDER_SERVED = auto()       # 订单上菜
    COOKING_STARTED = auto()    # 开始烹饪
    COOKING_COMPLETED = auto()  # 烹饪完成
    INGREDIENT_EXPIRED = auto() # 食材过期
    INGREDIENT_ADDED_TO_ASSEMBLY = auto()
    CONDIMENT_ADDED = auto()
    ASSEMBLY_COMPLETED = auto()
    INGREDIENT_MOVED_TO_STOCKPILE = auto()
    INGREDIENT_MOVED_TO_TRASH = auto()
    SLOTS_ADVANCED = auto()     # 槽位前移
```

## 3. 核心操作

### 3.1 烹饪操作

#### `start_cooking(ingredient, cooker)`
- **前置条件**：灶台存在且空闲
- **效果**：灶台变忙，设置 `done_at` 和 `expired_at`
- **返回**：`ActionResult(success=True/False)`

#### `move_to_assembly(cooker)`
- **前置条件**：灶台忙、烹饪完成、食材与组装站兼容
- **效果**：食材移入组装站，灶台释放
- **返回**：`ActionResult`

### 3.2 订单操作

#### `serve_order(slot_idx)`
- **前置条件**：槽位有订单、组装站完成、不在动画窗口
- **效果**：订单完成、计算得分、槽位前移、激活动画窗口
- **返回**：`ActionResult`

### 3.3 时间管理

#### `tick(dt: float) -> List[Event]`

推进模拟时间并触发自动事件：

1. **生成新订单**（在超时检查之前）
2. **检查订单超时**
3. **检查烹饪完成和食材过期**

## 4. 订单刷新规则

1. **自动刷新**：每隔 4 秒自动生成新订单（第 4、8、12... 秒）
2. **立即刷新**：提交后如果场上没有订单，立即生成新订单
3. **部分刷新**：提交/过期后有剩余订单时，从该时刻开始计时 4 秒
4. **过期重置**：每次订单过期都重置 4 秒计时器
5. **动画延迟**：新订单有 1 秒动画时间

## 5. 浮点精度处理

由于浮点精度问题（如 `7.9 + 0.1 ≠ 8.0`），在比较时间时使用容差：

```python
EPSILON = 1e-9
if current_time >= self._next_order_refresh_time - EPSILON:
    # 生成订单
```

## 6. 常量

| 常量 | 值 | 说明 |
|------|-----|------|
| MAX_SLOTS | 4 | 订单槽位数 |
| MAX_STOCKPILE | 5 | 每个库存槽位最大数量 |
| COOKER_RETENTION | 5.0 | 灶台食材保留时间（秒） |
| ANIMATION_DURATION | 1.5 | 槽位位移动画时间（秒） |
| RUSH_TIMEOUT | 40.0 | Rush 订单超时时间（秒） |
| NORMAL_TIMEOUT | 70.0 | 普通订单超时时间（秒） |
| MAX_CONDIMENTS | 3 | 最大调料数量 |
| GAME_DURATION | 90.0 | 游戏总时长（秒） |
| ORDER_INTERVAL | 4.0 | 订单生成间隔（秒） |

## 7. ActionResult 结构

```python
@dataclass(frozen=True)
class ActionResult:
    success: bool
    events: tuple[Event, ...] = ()
    error_message: Optional[str] = None
    score_earned: int = 0
```

## 8. 文件结构

| 文件 | 说明 |
|------|------|
| `hawarma/env_simulator.py` | 主模拟器类和 ActionResult |
| `hawarma/env_simulator_types.py` | 数据类型定义 |
| `hawarma/env_bridge.py` | 连接真实系统和模拟器的桥接器 |
| `scripts/simulate_game.py` | 调试脚本 |
| `tests/test_env_simulator.py` | 测试套件 |
