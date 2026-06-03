# 甜点站点架构设计

> 本文档描述甜点站点（Dessert Station）的当前架构，基于"数据契约而非行为 ABC"的设计原则。
>
> **重要：本文档不描述 `GastronomeEnv` / `DessertEnv` ABC 接口拆分**——该设计于 5/25 commit `ed96cd4` "abolish false ABC" 后被显式废除。Runner 直接持有 GameEnv，station 信息由 Operator/CLI 局部持有，strategy 通过返回的 Action 类型隐含 station。

---

## 1. 概述

### 1.1 甜点模式与 Gastronome 模式的区别

| 维度 | Gastronome | Dessert |
|------|-----------|---------|
| 中间容器 | 组装站（Assembly Station） | 搅拌盆（Mixing Bowl） |
| 烹饪时机 | 食材先烹饪再组装 | 食材先组装、搅拌再烹饪 |
| 特殊操作 | 无 | 搅拌（特殊 swipe） |
| 灶台→取餐台 | 不直接，必须经过组装站 | 直接（烹饪完从灶台 serve） |
| 食材数量 | 1 或 2 | 始终 2 |
| 库存支持 | 有（3 种烹饪后的食材，每种各 5 份） | 无（半成品库存后续迭代实现） |
| 物理位置 | 组装站 | 搅拌盆（与组装站不同位置） |

### 1.2 甜点流程

```
食材区 → 搅拌盆 → 调味 → 搅拌 → 灶台烹饪 → 取餐台
  │         │       │      │        │        │
  │         │       │      │        │        │
MoveTo   AddCondTo Stir  MoveMix   ServeFrom
MixingBowl MixBowl       Bowl   ToCooker  Cooker
```

详细步骤：
1. 食材 A → 搅拌盆
2. 食材 B → 搅拌盆
3. 调味品 → 搅拌盆（依次添加）
4. 搅拌（从搅拌盆坐标按下，向左滑动 400px，持续 1.5s）
5. 搅拌盆 → 灶台（直接滑动到 cooker）
6. 烹饪完成 → 取餐台（直接从灶台出餐）

### 1.3 关键约束

- **不混合模式**：甜点模式和 Gastronome 模式不会出现在同一局游戏中
- **双食材**：所有甜点都是双食材
- **订单检测**：只需检测第一个食材即可确定菜谱（第一个食材唯一确定）
- **超时机制**：甜点有超时机制，normal 70s+，rush 40s+
- **烹饪后出餐**：烹饪完成后只有 5 秒时间去 serve，超过 5 秒后就要清空 cooker
- **无半成品库存**：半成品库存功能在后续迭代中实现，Phase 1 不包含

---

## 2. 数据结构

### 2.1 Station 枚举

**文件**：`src/hawarma/recipe.py`

```python
class Station(Enum):
    """制作台类型"""
    GASTRONOME = "gastronome"
    DESSERT = "dessert"
```

`Station` 是 `Recipe.station` 字段的类型，标识配方所属站点。**与 `UnifiedState` 无任何关系**——`UnifiedState` 不包含 station 字段（已删除，详见 4.2 节）。

### 2.2 MixingBowlState

**文件**：`src/hawarma/core/models.py`

```python
@dataclass
class MixingBowlState:
    """搅拌盆状态（甜点专用）"""
    ingredients: list[str] = field(default_factory=list)
    condiments: dict[str, int] = field(default_factory=dict)
    target_recipe_slug: str | None = None
    is_stirred: bool = False

    @property
    def is_empty(self) -> bool:
        return len(self.ingredients) == 0

    @property
    def is_free(self) -> bool:
        """搅拌盆是否空闲（与 AssemblyState.is_free 语义一致）"""
        return self.is_empty and self.target_recipe_slug is None

    @property
    def is_ready_to_cook(self) -> bool:
        """食材齐全 + 已搅拌"""
        return len(self.ingredients) >= 2 and self.is_stirred

    def reset(self) -> None:
        """重置搅拌盆状态"""
        self.ingredients.clear()
        self.condiments.clear()
        self.target_recipe_slug = None
        self.is_stirred = False
```

**设计决策**：
- `ingredients: list[str]` — 甜点始终 2 种食材，用 list 保持顺序
- `is_stirred: bool` — 隐式状态追踪，标记是否已完成搅拌操作
- `target_recipe_slug` — 与 `AssemblyState` 一致，用于配方校验
- `is_free` property — 与 `AssemblyState.is_free` 语义一致

### 2.3 CookerState.item_name 字段重命名

**文件**：`src/hawarma/core/models.py`

`CookerState.item_name` 在两种模式下语义不同：

| 模式 | 存储内容 | 语义 |
|------|---------|------|
| Gastronome | 食材名（如 `clearwater_fish`） | 单一食材正在烹饪 |
| Dessert | 配方 slug（如 `domeFigueMiel`） | 多食材+调料组成的半成品正在烹饪 |

为消除歧义，5/25 commit `e942ce8` 将原 `ingredient_name` 字段重命名为 `item_name`：
- Gastronome 路径：调用方传 ingredient name
- Dessert 路径：GameEnv 内部推断 recipe slug 后再调用 start_cooking

---

## 3. Action 类型

**文件**：`src/hawarma/core/actions.py`

Strategy 产出 Action，Env 消费 Action。Action 是 Strategy 和 Env 之间的**数据契约**（不是行为 ABC）。

### 3.1 共享 Action

| Action | 字段 | 说明 |
|--------|------|------|
| `ClearCookerAction` | `cooker: str` | 清理灶台（两种模式都用） |

### 3.2 Gastronome 专用 Action

| Action | 字段 | 流向 |
|--------|------|------|
| `AddCondimentAction` | `condiment: str` | 调料区 → 组装站 |
| `ClearAssemblyAction` | — | 清空组装站 |
| `CookAction` | `ingredient, cooker, duration, order_id?` | 食材区 → 灶台烹饪 |
| `MoveToAssemblyAction` | `cooker, order_id?` | 灶台 → 组装站 |
| `MoveToStockpileAction` | `cooker, slot` | 灶台 → 库存 |
| `PullFromStockpileAction` | `slot, ingredient` | 库存 → 组装站 |
| `ServeOrderAction` | `slot_idx: int` | 组装站 → 取餐台 |

### 3.3 Dessert 专用 Action

| Action | 字段 | 流向 |
|--------|------|------|
| `MoveToMixingBowlAction` | `ingredient: str` | 食材区 → 搅拌盆 |
| `AddCondimentToMixingBowlAction` | `condiment: str` | 调料区 → 搅拌盆 |
| `StirAction` | `distance, duration, steps` | 搅拌（单次左滑 swipe） |
| `MoveMixingBowlToCookerAction` | `cooker: str` | 搅拌盆 → 灶台 |
| `ServeFromCookerAction` | `cooker, slot_idx` | 灶台 → 取餐台 |
| `ClearMixingBowlAction` | — | 清空搅拌盆 |

### 3.4 命名约定

`{Verb}{Object}Action` 模式。**注意**：
- `AddCondimentAction`（Gastronome，→组装站）和 `AddCondimentToMixingBowlAction`（Dessert，→搅拌盆）**不可复用**——终点不同。
- 5/25 commit `e942ce8` 同步统一命名。

### 3.5 Dessert Action 流程

```python
1. MoveToMixingBowlAction(ingredient="X")            # 食材A → 搅拌盆
2. MoveToMixingBowlAction(ingredient="Y")            # 食材B → 搅拌盆
3. AddCondimentToMixingBowlAction(condiment="Z")     # 调味（甜点专用）
4. StirAction(distance=400.0, duration=1.5, steps=10) # 搅拌
5. MoveMixingBowlToCookerAction(cooker="dessert_oven") # 搅拌盆 → 灶台
6. ServeFromCookerAction(cooker="dessert_oven", slot_idx=0) # 灶台 → 取餐台
```

---

## 4. 数据契约（Data Contract）

### 4.1 链路：`屏幕像素 → Action`

```
┌──────────────────────────────────────────────────────────────┐
│ Phase 1: 视觉感知（game/scanner.py）                            │
│ G.DEVICE.snapshot() → Scanner._detect_order() → DetectedOrder│
│ （只含 slot_idx, recipe_slug, is_rush, confidence）            │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Phase 2: 状态同步（game/runner.py）                            │
│ _sync_orders_from_scan() 增量合并 DetectedOrder → env._orders│
│ （补全 order_id, created_at, timeout_at）                      │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Phase 3: 状态快照（game/game_env.py: get_unified_state）      │
│ env._orders → tuple[Order | None, ...]                       │
│ env._cookers → dict[str, CookerState]                        │
│ env._assembly → AssemblyState                                 │
│ env._stockpile → dict[str, StockpileSlot]                    │
│ env._mixing_bowl → MixingBowlState (Dessert 专用)             │
│ env.is_in_animation_window() → bool                           │
│ → UnifiedState (frozen=True)                                  │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Phase 4: 决策（agent/strategies/*.py）                        │
│ strategy.decide(state) → Action | None                       │
│ Gastronome: 10 级 GreedyCascade 瀑布                          │
│ Dessert: 7 级流水线决策                                       │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Phase 5: 执行（game/runner.py: _action_handlers）             │
│ Runner 按 action 类名查 _action_handlers 字典分发              │
│ → Operator.<method>() → Airtest swipe 屏幕                   │
│ → env.<method>() → 内部状态更新                                │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 UnifiedState 字段

**文件**：`src/hawarma/core/state.py`

```python
@dataclass(frozen=True)
class UnifiedState:
    """Strategy 唯一输入。frozen=True 防止策略意外修改。"""

    time: float                              # 当前游戏时间（秒）
    orders: tuple[Order | None, ...]          # 4 个订单槽位
    cookers: dict[str, CookerState]           # 灶台名称 → 状态
    assembly: AssemblyState                   # 组装站（gastronome 用）
    stockpile: dict[str, StockpileSlot]       # 库存槽位
    recipes: dict[str, Recipe]                # 配方 slug → Recipe
    game_duration: float                      # 本局总时长
    is_in_animation_window: bool              # 动画窗口标志
    total_visibility: float = 0.0             # 已完成订单的 visibility
    mixing_bowl: MixingBowlState              # 搅拌盆（dessert 用）
```

**注意**：`UnifiedState` **不包含** `station` 字段。该字段于 2026-06-03 commit 中删除（曾为预留设计但从未被 strategy 读取）。station 信息由 CLI/Operator/TUI 各自用局部变量持有，strategy 通过返回的 Action 类型隐含 station（CookAction 隐含 gastronome，ServeFromCookerAction 隐含 dessert）。

### 4.3 GameEnv 接口

**文件**：`src/hawarma/game/game_env.py`

**单一 `GameEnv` 类**（不再拆分 GastronomeEnv/DessertEnv ABC），同时持有 assembly 和 mixing_bowl 状态。两种 station 模式下，Runner 通过 action handler 字典分发到对应的 `_exec_*` 方法。

```python
class GameEnv:
    """真实环境状态追踪（gastronome + dessert 共用）"""

    def __init__(self, ...):
        self._orders: list[Order | None] = [None] * 4
        self._cookers: dict[str, CookerState] = {}
        self._assembly: AssemblyState = AssemblyState()
        self._stockpile: dict[str, StockpileSlot] = {}
        self._mixing_bowl: MixingBowlState = MixingBowlState()
        self._animation_until: float = 0.0
        # ... 其他内部状态

    def get_unified_state(self) -> UnifiedState:
        """构造 UnifiedState 快照。两条 station 路径都走这里。"""
        ...

    # Gastronome 方法
    def start_cooking(self, ingredient: str, cooker: str, duration: float) -> bool: ...
    def move_to_assembly(self, cooker: str) -> bool: ...
    def serve_order(self, slot_idx: int) -> bool: ...
    # ... 其他 7 个方法

    # Dessert 方法
    def add_to_mixing_bowl(self, ingredient: str, ...) -> bool: ...
    def add_condiment_to_mixing_bowl(self, condiment: str) -> bool: ...
    def stir_mixing_bowl(self) -> bool: ...
    def move_mixing_bowl_to_cooker(self, cooker: str) -> bool: ...
    def serve_from_cooker(self, cooker: str, slot_idx: int) -> bool: ...
    def clear_mixing_bowl(self) -> bool: ...
```

### 4.4 设计决策：单一 GameEnv vs ABC 拆分

**早期设计**（5/10 commit `d68400d`）曾拆分 `Env` + `GastronomeEnv(Env)` + `DessertEnv(Env)` 三个 ABC，GameEnv 多继承两者。**5/25 commit `ed96cd4` 显式废除**：

> "DDD rationale: Real and Sim envs are different bounded contexts. Their contract is data (UnifiedState + Action), not behavior (ABC)."

**理由**：
- "胖接口"问题：单一 GameEnv 暴露所有方法，但 Runner 通过 action handler 字典分发，只调用当前 station 需要的方法——"胖"是表面的
- DIP 实际收益低：测试时 mock 整个 GameEnv 比重写混合多接口 ABC 更简单
- 数据契约更稳定：`UnifiedState` + `Action` 是结构化数据，不依赖行为继承；ABC 拆分会让重构牵动更多文件

**当前架构优势**：
- `GameEnv` 单一类 → 易理解
- `_action_handlers` 字典 → station 行为分发显式可见
- `UnifiedState` 数据契约 → strategy 完全纯净（无 env 依赖）

---

## 5. DessertStrategy 实现

**文件**：`src/hawarma/agent/strategies/dessert.py`

### 5.1 策略概述

DessertStrategy 是甜点专用策略，**不继承自 `GastronomeStrategy`**——直接继承 `Strategy` ABC，采用独立的流水线决策逻辑：

- 当当前订单在烹饪时，开始下一个订单的食材收集和搅拌
- 优先处理 rush 订单，然后先进先出
- 管理并发订单（最多 2 个）

### 5.2 决策优先级

```
1. 送餐（灶台→取餐台）              ServeFromCookerAction
2. 清理过期灶台                     ClearCookerAction
3. 移动搅拌盆到灶台（搅拌完成 + 灶台空闲）  MoveMixingBowlToCookerAction
4. 搅拌（食材齐全 + 未搅拌）         StirAction
5. 添加调料（食材齐全 + 未调味完成）  AddCondimentToMixingBowlAction
6. 添加食材到搅拌盆                 MoveToMixingBowlAction
7. 清理搅拌盆（无匹配订单）          ClearMixingBowlAction
```

### 5.3 关键设计差异（vs Gastronome Cascade）

| 维度 | Gastronome | Dessert |
|------|-----------|---------|
| 决策框架 | 10 级 GreedyCascade 瀑布 | 7 级流水线 |
| 订单排序 | CP + visibility 阈值 + 单食材 bonus | FIFO + rush 优先 |
| 中间容器 | Assembly（共享，2 个食材组合） | MixingBowl（专用，搅拌后送入 cooker） |
| 出餐路径 | Assembly → 订单槽 | Cooker → 订单槽（跳过中间容器） |
| 库存 | Stockpile（3 槽位） | 无 |
| 烹饪并发 | 多个 cooker 并行 + 库存缓冲 | 最多 2 个并发订单 |

---

## 6. 配置结构

**文件**：`configs/config.yaml`（运行时自动生成于首次运行，详见 `config.py:load_config`）

```yaml
# 灶台坐标：
#   gastronome: screen.cookers_positions（槽位分配）
#   dessert:    stations.dessert.cookers_positions（固定映射）

stations:
  dessert:
    enabled: true
    stir:
      distance: 400
      duration: 1.5
      steps: 10
    mixing_bowl_position:
      - 1245
      - 870
    cookers_positions:
      dessert_oven: [715, 615]
      cooling_plate: [1260, 590]
    cooker_retention: 5.0

game:
  cooker_retention: 5.0  # 顶层字段（gastronome 实际使用）
  # ... 其他 game 配置
```

**注**：旧的 `stations.gastronome` 子节（`enabled`, `cooker_retention`, `serve_verify_wait`）于 2026-06-03 commit 中删除——这些字段自引入后从未被任何代码消费。gastronome 实际使用 `game.cooker_retention`（顶层）和 `screen.cookers_positions`（坐标）。

**文件**：`src/hawarma/config.py`

```python
class StirConfig(BaseModel):
    """搅拌操作配置（单次左滑）"""
    distance: int = 400
    duration: float = 1.5
    steps: int = 10


class DessertStationConfig(BaseModel):
    """甜点站点配置（仅 dessert）"""
    enabled: bool = True
    stir: StirConfig = Field(default_factory=StirConfig)
    mixing_bowl_position: tuple[int, int] = (1245, 870)
    cookers_positions: dict[str, tuple[int, int]] = {
        "dessert_oven": (715, 615),
        "cooling_plate": (1260, 590),
    }
    cooker_retention: float = 5.0


class StationsConfig(BaseModel):
    """站点配置（目前仅 dessert）"""
    dessert: DessertStationConfig = Field(default_factory=DessertStationConfig)
```

---

## 7. 文件组织

### 7.1 核心文件

| 文件 | 用途 |
|------|------|
| `src/hawarma/recipe.py` | `Station` 枚举 + `Recipe` 模型 |
| `src/hawarma/core/models.py` | `AssemblyState`, `MixingBowlState`, `CookerState`, `StockpileSlot`, `Order` |
| `src/hawarma/core/state.py` | `UnifiedState` 数据契约 |
| `src/hawarma/core/actions.py` | 14 个 Action 类（3 共享/7 gastronome/6 dessert）|
| `src/hawarma/game/game_env.py` | `GameEnv` 单一类（gastronome + dessert 状态） |
| `src/hawarma/game/runner.py` | Runner + `_action_handlers` 字典分发 |
| `src/hawarma/game/operator.py` | UI 操作层（按 `_build_mappings` 分 station 坐标） |
| `src/hawarma/game/scanner.py` | 屏幕 → `DetectedOrder`（station 无关） |
| `src/hawarma/game/verifier.py` | 送餐后验证组装站是否清空（仅 gastronome 用） |
| `src/hawarma/agent/strategies/dessert.py` | `DessertStrategy` 独立实现 |
| `src/hawarma/agent/strategies/gastronome.py` | `GastronomeStrategy`（用户级 `gastronome`，合并 6 个历史变体的最优特性） |
| `src/hawarma/agent/registry.py` | 策略注册表（`"gastronome"`, `"dessert"`） |
| `src/hawarma/config.py` | Pydantic 配置模型（自动生成 config.yaml） |

### 7.2 测试文件

| 文件 | 用途 |
|------|------|
| `tests/test_dessert_strategy.py` | DessertStrategy 单元测试（19 个 case） |
| `tests/test_rush_tiebreaker.py` | GastronomeStrategy 优先级 tiebreaker 测试（4 个 case） |
| `tests/test_recipe_detection.py` | Recipe 扫描匹配测试 |

---

## 8. 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 枚举名称 | `Station`（不是 `Platform`） | 已存在于 `recipe.py`，与代码库一致 |
| Env 设计 | 单一 `GameEnv` + Action 字典分发（**不**用 ABC 拆分） | 数据契约比行为 ABC 更稳定；5/25 commit `ed96cd4` 显式废除 ABC 拆分 |
| 状态追踪 | 隐式（`is_stirred` 标志） | 不引入显式状态机，更简单 |
| 搅拌盆 | 独立于组装站 | 不同物理位置 |
| CookerState 字段 | `ingredient_name` → `item_name` | 甜点模式下存 recipe slug，原字段名语义不准确 |
| DessertStrategy | 独立类（不继承 GastronomeStrategy） | 不同的流水线逻辑 |
| Action 命名 | `{Verb}{Object}Action` | 与现有约定一致 |
| 出餐方式 | 直接从灶台 | 甜点跳过组装站，直接从灶台出餐 |
| 调味 Action | 分离为 `AddCondimentToMixingBowlAction` | 甜点调味终点是搅拌盆，不是组装站，两个 Action 不可复用 |
| station 信息流 | CLI/Operator/TUI 局部持有，Strategy 通过 Action 隐含 | 避免 `UnifiedState.station` 这种死字段；strategy 保持纯净 |
| Verifier | 仅 gastronome 用 | dessert 出餐不做组装站验证 |

---

## 9. 物理位置配置

**文件**：`configs/config.yaml`

```yaml
screen:
  resolution: [1920, 1080]
  # gastronome 灶台坐标（slot-based）
  cookers_positions:
    - [595, 585]
    - [850, 585]
    - [1120, 585]
    - [1370, 585]
  # dessert 灶台坐标（named, fixed）
stations:
  dessert:
    cookers_positions:
      dessert_oven: [715, 615]
      cooling_plate: [1260, 590]
    mixing_bowl_position: [1245, 870]
```

Operator 在 `_build_mappings()` 时根据 station 选择坐标源（`screen.cookers_positions` vs `stations.dessert.cookers_positions`）。

---

## 10. 订单检测

**文件**：`src/hawarma/game/scanner.py`

### 10.1 共同逻辑

- 4 个订单槽位，每槽位截取 `screen.orders_regions[slot]`
- 第一个食材模板匹配（`screen.ingredients_regions[slot]`）
- `_detect_rush` 检测红色像素（`screen.rush_red_threshold = 180`）

### 10.2 甜点特有：首食材唯一

甜点首食材唯一确定菜谱（不同甜点的第一个食材不重叠），所以不需要像 gastronome 那样做 `cooker 图标消歧`。

### 10.3 输出

```python
@dataclass
class DetectedOrder:
    slot_idx: int
    recipe_slug: str
    is_rush: bool
    confidence: float
```

`DetectedOrder` **不包含** `order_id`, `created_at`, `timeout_at`——这些由 Runner 合并到 env 现有 `_orders` 时补全（按 `recipe_slug + is_rush` 匹配复用现有 Order）。

---

## 11. 并发处理

- 最多同时跟踪 2 个订单（4 个槽位，最多 2 个在 pipeline 中）
- 同一搅拌盆一次只能处理一个订单（搅拌盆 reset 才接受下一单）
- 同一灶台同时只能烹饪一个半成品（与 gastronome 共享逻辑）

---

## 12. 错误处理

- 食材区点击失败 → log + skip
- 搅拌 swipe 失败 → log + 重试 1 次
- 烹饪超时 → `ClearMixingBowlAction` 清空
- 订单 timeout → Runner 主动 `_shift_orders_left` 移除

**不实现**：复杂重试机制、跨任务回滚。假设每次操作成功，失败仅记录。

---

## 13. 测试策略

- `tests/test_dessert_strategy.py` — 19 个 case 覆盖决策优先级
- `tests/test_rush_tiebreaker.py` — 7 个 case 覆盖 gastronome 优先级
- 集成测试在 playground 模拟器中跑

运行：
```bash
.venv\Scripts\python -m unittest discover tests
.venv\Scripts\python -m playground run --seed 42  # 模拟器单局
.venv\Scripts\python -m playground bench --games 50  # 基准测试
```

---

## 14. 监控和日志

- 每个 Action 触发时 loguru 记录（DEBUG 级别）
- GameEnv 状态变更记录（INFO 级别）
- 错误和异常记录（ERROR 级别）
- 订单检测结果记录（DEBUG 级别）

日志目录：`logs/`（runtime 配置的 `log_directory`）

---

## 15. 未来扩展

| 计划 | 状态 | 备注 |
|------|------|------|
| 甜点半成品库存 | 未实现 | 5/10 commit 预留 |
| 甜点送餐验证 | 未实现 | 当前仅 gastronome 用 Verifier |
| 多 station 美食模式 | 未计划 | `stations.gastronome` 死字段已删除 |
| station 切换热更新 | 未计划 | 当前每局游戏固定 station |

---

## 16. 文档维护

- 本文档反映 2026-06-03 `chore/remove-gastronome-redundancies` 清理后的状态
- ABC 设计讨论：见 git commit `ed96cd4` 5/25 "abolish false ABC"
- 术语统一：见 git commit `e942ce8` 5/25 "unify naming across core models and simulator"
- "gastronome" 术语边界：见 `docs/gastronome_strategy_report.md`
