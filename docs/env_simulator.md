# env_simulator.py — 游戏环境模拟器

## 定位

游戏规则的**参考实现**，一个轻量级状态机。不依赖 Scheduler/Executor/Airtest，独立维护游戏状态。

作为"真理之源"：如果 env_simulator 拒绝某个操作，说明该操作违反了游戏规则。

## 架构

```
GameSimulator
├── 状态
│   ├── orders: list[Order | None]       # 4 个订单 slot
│   ├── cookers: dict[str, CookerState]    # 灶台状态
│   ├── assembly: AssemblyState            # 组装站食材（无订单归属概念）
│   ├── stockpile: dict[str, StockpileSlot]  # 库存 slot
│   └── time: float                        # 模拟器内部时钟
│
├── 配置
│   ├── setup_cookers(names)               # 初始化灶台
│   └── setup_stockpile(slots)             # 初始化库存
│
├── 订单管理
│   ├── inject_order(slot, recipe)         # 注入订单到指定 slot
│   ├── schedule_order(recipe, appear_at)   # 调度未来出现的订单
│   ├── get_order(slot)                    # 查询 slot 中的订单
│   └── get_order_slot(order_id)           # 反查订单所在 slot
│
├── 操作（每个操作都有前置条件检查）
│   ├── start_cooking(ingredient, cooker)
│   ├── move_to_assembly(cooker)
│   ├── move_to_stockpile(cooker, slot)
│   ├── pull_from_stockpile(slot)
│   ├── add_condiment(condiment)
│   ├── serve_order(slot)                  # 检查动画窗口
│   ├── move_to_trash(from_location)       # 丢弃任意位置的食材
│   └── clear_cooker(cooker)               # 清理过期食材
│
├── 时间
│   └── tick(dt)                           # 推进时间，触发自动事件
│
├── 事件
│   ├── drain_events()                     # 取出并清空事件队列
│   └── events                             # 只读事件列表
│
└── 查询
    ├── snapshot()                         # 状态快照（用于断言）
    ├── get_overdue_cookers()              # 过期灶台列表
    ├── get_stockpile_count(ingredient)    # 某食材总库存
    ├── get_assembly_ingredients()         # 组装站当前食材
    └── is_animation_window()              # 是否在动画窗口期
```

## 操作前置条件

| 操作 | 必须满足 | 失败时返回 |
|------|---------|-----------|
| `start_cooking` | 灶台存在 | `False` |
| `move_to_assembly` | 灶台 busy、有食材、烹饪完成 | `False` |
| `move_to_stockpile` | 灶台 busy、烹饪完成、目标 slot 未满(≤5)、同 cooker+食材 | `False` |
| `pull_from_stockpile` | 库存 > 0 | `False` |
| `add_condiment` | 组装站非空、该调料在 recipe 中且未达上限、总调料数 < 3 | `False` |
| `serve_order` | slot 有订单、组装站食材组合符合 recipe 要求、调料符合要求、不在动画窗口 | `False` |
| `move_to_trash` | 来源位置有食材 | `False` |
| `clear_cooker` | 灶台 busy、已过期 | `False` |

### 关键规则说明

1. **食材独立性**：assembly station 上的食材不绑定任何订单，可被任意需要该食材的订单使用
2. **库存约束**：每个 stockpile slot 只能存由同一 cooker 烹饪的同种食材，上限 5 份
3. **调料机制**：最多 3 份调料，无效调料（非 recipe 要求）swipe 无效果
4. **超时影响**：订单超时仅触发 slot 位移，不影响 assembly station 上的食材

## 事件类型

```python
class EventType(Enum):
    SWIPE = auto()              # 物理滑动操作
    ORDER_APPEARED = auto()     # 新订单出现
    ORDER_TIMEOUT = auto()      # 订单超时
    COOKING_DONE = auto()       # 烹饪完成
    INGREDIENT_EXPIRED = auto() # 灶台食材过期
    ORDER_SERVED = auto()       # 订单上菜
    SLOTS_ADVANCED = auto()     # slot 位移
```

## 使用方式

```python
from hawarma.env_simulator import GameSimulator, Recipe, Ingredient

# 初始化
env = GameSimulator()
env.setup_cookers(['grill', 'oven', 'skillet', 'pot'])
env.setup_stockpile(['stk0', 'stk1', 'stk2'])

# 定义配方
fish = Recipe(
    name='Braised Fish',
    ingredients=[Ingredient('clearwater_fish', 'skillet', 4.0)],
    condiments={'hearthspice': 1, 'acacia_honey': 1},
)

# 注入并执行
env.inject_order(0, fish)
env.tick(0.1)                     # 等待动画
env.start_cooking('clearwater_fish', 'skillet')
env.tick(4.0)                     # 烹饪等待
env.move_to_assembly('skillet')
env.add_condiment('hearthspice')
env.add_condiment('acacia_honey')
env.serve_order(0)

# 检查结果
for e in env.events:
    if e.type == EventType.SWIPE:
        print(f'{e.time:.2f}s  {e.detail["action"]}  {e.detail["start"]} -> {e.detail["end"]}')
```

## 与功能侧的关系

| env_simulator | 功能侧 |
|---|---|
| `time` 模拟器时钟 | `asyncio.get_event_loop().time()` 真实时钟 |
| `tick(dt)` 手动推进 | `asyncio.sleep()` 自然流逝 |
| `start_cooking` 设置 `done_at` | Executor 的 `asyncio.sleep(duration)` |
| `serve_order` 检查动画窗口 | Scheduler 的 `is_ui_stable()` |
| `orders` 管理 slot | `GameState.orders` |
| `assembly` 归属 | `GameState.assembly` |

env_simulator 是功能侧的子集——只实现游戏规则，不实现 UI 自动化。
