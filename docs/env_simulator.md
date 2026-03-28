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
│   ├── assembly: AssemblyState            # 组装站食材
│   ├── stockpile: dict[str, StockpileSlot]  # 库存 slot
│   └── time: float                        # 模拟器内部时钟
│
├── 配置
│   ├── load_recipes(filepath)             # 从 JSON 文件加载配方
│   ├── select_recipes(count, seed)        # 随机选择配方
│   ├── setup_from_recipes(slugs)          # 根据配方自动配置游戏
│   ├── setup_cookers(names)               # 初始化灶台
│   └── setup_stockpile(slots)             # 初始化库存
│
├── 订单管理
│   ├── inject_order(slot, recipe)         # 注入订单到指定 slot
│   └── get_order(slot)                    # 查询 slot 中的订单
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
│   └── events                             # 只读事件列表
│
└── 查询
    ├── get_cooker_state(cooker)           # 灶台状态
    ├── get_stockpile_slot(slot)           # 库存槽位状态
    └── is_in_animation_window()           # 是否在动画窗口期
```

## 操作前置条件

| 操作 | 必须满足 | 失败时返回 |
|------|---------|-----------|
| `start_cooking` | 灶台存在且空闲 | `False` |
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
    ORDER_APPEARED = auto()     # 新订单出现
    ORDER_TIMEOUT = auto()      # 订单超时
    ORDER_SERVED = auto()       # 订单上菜
    COOKING_STARTED = auto()    # 开始烹饪
    COOKING_COMPLETED = auto()  # 烹饪完成
    INGREDIENT_EXPIRED = auto() # 灶台食材过期
    INGREDIENT_ADDED_TO_ASSEMBLY = auto()  # 食材加入组装站
    CONDIMENT_ADDED = auto()               # 添加调料
    ASSEMBLY_COMPLETED = auto()            # 组装完成
    INGREDIENT_MOVED_TO_STOCKPILE = auto() # 食材移入库存
    INGREDIENT_MOVED_TO_TRASH = auto()     # 食材丢弃
    SLOTS_ADVANCED = auto()     # slot 位移
```

## 订单刷新规则

1. **自动刷新**：游戏开始后，每隔 4 秒自动刷新一个新订单（第 4、8、12... 秒）
2. **提交后立即刷新**：如果订单被提交后，场上没有订单，系统会立即刷新一个新订单
3. **提交后部分订单**：如果有 4 个订单，提交 1 个后剩 3 个，从提交时刻开始计时 4 秒后刷新
4. **过期后刷新**：每次订单过期都重置 4 秒计时器，从该时刻开始重新计时
5. **新订单动画**：新订单有 1 秒动画时间，动画结束后才能被"看到"

## 使用方式

```python
from hawarma.env_simulator import GameSimulator

# 初始化
sim = GameSimulator()
sim.load_recipes("data/recipes.json")

# 选菜单并配置
selected = sim.select_recipes(count=4, random_seed=42)
sim.setup_from_recipes(selected)

# 注入订单并执行
recipe = list(sim.recipes.values())[0]
sim.inject_order(0, recipe, is_rush=False)
sim.tick(0.1)  # 等待动画

# 烹饪
sim.start_cooking('clearwater_fish', 'skillet')
sim.tick(4.0)  # 烹饪等待
sim.move_to_assembly('skillet')
sim.add_condiment('hearthspice')
sim.serve_order(0)

# 检查结果
for e in sim.events:
    print(f"{e.timestamp:.2f}s  {e.event_type.name}  {e.details}")
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
