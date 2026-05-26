# 甜点站点架构设计

> 本文档记录甜点站点（Dessert Station）的架构设计和实现方案。
> 目标：在不破坏现有 Gastronome 流程的前提下，支持甜点模式的自动化。

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
| 库存支持 | 有（3种烹饪后的食材，每种各5份） | 无（半成品库存后续迭代实现） |
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

### 2.3 CookerState 字段重命名

**文件**：`src/hawarma/core/models.py`

`CookerState.ingredient_name` 在两种模式下语义不同：

| 模式 | 存储内容 | 语义 |
|------|---------|------|
| Gastronome | 食材名（如 `clearwater_fish`） | 单一食材正在烹饪 |
| Dessert | 配方 slug（如 `domeFigueMiel`） | 多食材+调料组成的半成品正在烹饪 |

为消除歧义，重命名字段：

```python
@dataclass
class CookerState:
    """灶台状态"""
    busy: bool = False
    item_name: str | None = None          # 原 ingredient_name，重命名
    cooker_type: str | None = None
    started_at: float | None = None
    done_at: float | None = None
    expired_at: float | None = None
```

**影响范围**（需全局替换 `ingredient_name` → `item_name`）：
- `core/models.py`：CookerState 定义
- `game/game_env.py`：`start_cooking()`、`move_to_assembly()`、`move_to_stockpile()`、`move_mixing_bowl_to_cooker()`、`serve_from_cooker()` 等
- `game/runner.py`：`_exec_cook()`、`_exec_move_to_assembly()`、`_exec_move_to_stockpile()`、`_exec_serve_from_cooker()` 等
- `agent/strategies/*.py`：所有引用 `cooker.ingredient_name` 的地方
- `playground/`：模拟器相关代码

### 2.4 UnifiedState 扩展

**文件**：`src/hawarma/core/state.py`

```python
@dataclass(frozen=True)
class UnifiedState:
    """统一观测状态"""
    # 现有字段
    time: float
    orders: tuple[OrderInfo | None, ...]
    cookers: dict[str, CookerState]
    assembly: AssemblyState
    stockpile: dict[str, StockpileSlot]
    recipes: dict[str, object]
    game_duration: float
    is_in_animation_window: bool
    total_visibility: float = 0.0

    # 新增字段
    mixing_bowl: MixingBowlState = field(default_factory=MixingBowlState)
    station: Station = Station.GASTRONOME

    @property
    def remaining_time(self) -> float:
        return max(0.0, self.game_duration - self.time)
```

**设计决策**：
- `mixing_bowl` 默认空值，gastronome 模式下不影响现有逻辑
- `station` 替代原 `platform`，与 `Recipe.station` 一致
- 使用 `field(default_factory=...)` 确保 frozen dataclass 的可变默认值安全

---

## 3. Action 类型

**文件**：`src/hawarma/core/actions.py`

```python
# ── Dessert 专用 ──

@dataclass
class MoveToMixingBowlAction(Action):
    """食材区 → 搅拌盆"""
    ingredient: str


@dataclass
class AddCondimentToMixingBowlAction(Action):
    """调料区 → 搅拌盆（甜点专用，与 Gastronome 的 AddCondimentAction 分离）"""
    condiment: str


@dataclass
class StirAction(Action):
    """搅拌（从搅拌盆坐标向左水平滑动）"""
    distance: float = 400.0   # 滑动距离（像素）
    duration: float = 1.5     # 滑动持续时间（秒）
    steps: int = 10           # Airtest 插值步数


@dataclass
class MoveMixingBowlToCookerAction(Action):
    """搅拌盆 → 灶台（搅拌完成后送入灶台烹饪）"""
    cooker: str


@dataclass
class ServeFromCookerAction(Action):
    """灶台 → 取餐台（甜点直接从灶台出餐）"""
    cooker: str
    slot_idx: int


@dataclass
class ClearMixingBowlAction(Action):
    """清空搅拌盆"""
    pass
```

**命名约定**：`{Verb}{Object}Action` 模式，与现有 Action 一致。

**Action 流程**：
```
1. MoveToMixingBowlAction(ingredient="X")        — 食材A → 搅拌盆
2. MoveToMixingBowlAction(ingredient="Y")        — 食材B → 搅拌盆
3. AddCondimentToMixingBowlAction(condiment="Z")  — 调味（甜点专用）
4. StirAction(distance=400.0, duration=1.5, steps=10) — 搅拌（单次左滑）
5. MoveMixingBowlToCookerAction(cooker="dessert_oven")  — 搅拌盆 → 灶台
6. ServeFromCookerAction(cooker="dessert_oven", slot_idx=0) — 灶台 → 取餐台
```

---

## 4. Env 接口扩展

**文件**：`src/hawarma/game/env.py`

Env 接口拆分为三层：共享基类 + station 专用子接口。`GameEnv` 实现全部接口，Runner 通过 DI 注入对应 station 的子接口。

```python
class Env(ABC):
    """共享接口 — 两种 station 都需要的方法"""

    @property
    @abstractmethod
    def time(self) -> float: ...
    @property
    @abstractmethod
    def orders(self) -> list[OrderInfo | None]: ...
    @property
    @abstractmethod
    def cookers(self) -> dict[str, CookerState]: ...
    @abstractmethod
    def is_in_animation_window(self) -> bool: ...
    @abstractmethod
    def start_cooking(self, ingredient: str, cooker: str, duration: float) -> bool: ...
    @abstractmethod
    def clear_cooker(self, cooker: str) -> bool: ...
    @abstractmethod
    def get_unified_state(self) -> UnifiedState: ...
    @abstractmethod
    def get_stats(self) -> dict: ...
    @abstractmethod
    def on_order_served(self, score: int = 1) -> None: ...
    @abstractmethod
    def on_order_timeout(self, order_id: int) -> None: ...
    @abstractmethod
    def on_action_taken(self) -> None: ...


class GastronomeEnv(Env):
    """Gastronome 专用接口"""

    @property
    @abstractmethod
    def assembly(self) -> AssemblyState: ...
    @property
    @abstractmethod
    def stockpile(self) -> dict[str, StockpileSlot]: ...
    @abstractmethod
    def move_to_assembly(self, cooker: str) -> bool: ...
    @abstractmethod
    def move_to_stockpile(self, cooker: str, slot: str) -> bool: ...
    @abstractmethod
    def pull_from_stockpile(self, slot: str) -> bool: ...
    @abstractmethod
    def add_condiment(self, condiment: str) -> bool: ...
    @abstractmethod
    def serve_order(self, slot_idx: int) -> bool: ...
    @abstractmethod
    def clear_assembly(self) -> bool: ...


class DessertEnv(Env):
    """Dessert 专用接口"""

    @property
    @abstractmethod
    def mixing_bowl(self) -> MixingBowlState: ...
    @abstractmethod
    def add_to_mixing_bowl(self, ingredient: str, recipe_slug: str | None = None) -> bool: ...
    @abstractmethod
    def add_condiment_to_mixing_bowl(self, condiment: str) -> bool: ...
    @abstractmethod
    def stir_mixing_bowl(self) -> bool: ...
    @abstractmethod
    def move_mixing_bowl_to_cooker(self, cooker: str) -> bool: ...
    @abstractmethod
    def serve_from_cooker(self, cooker: str, slot_idx: int) -> bool: ...
    @abstractmethod
    def clear_mixing_bowl(self) -> bool: ...
```

**拆分理由**：
- 避免"胖接口"：每种 station 只暴露自己需要的方法，Runner 不会误调不属于当前 station 的方法
- DIP 合规：Runner 依赖抽象（GastronomeEnv 或 DessertEnv），不依赖具体实现
- 测试友好：mock GastronomeEnv 时不需要实现 dessert 方法

### 4.1 GameEnv 实现

**文件**：`src/hawarma/game/game_env.py`

`GameEnv` 同时实现 `GastronomeEnv` 和 `DessertEnv`。两种模式共享同一个实例，通过 DI 注入 Runner 时使用对应 station 的类型标注。

```python
class GameEnv(GastronomeEnv, DessertEnv):
    """真实游戏环境 — 同时实现 GastronomeEnv 和 DessertEnv"""

    def __init__(self, ...):
        # 现有初始化
        ...
        # 新增
        self._mixing_bowl = MixingBowlState()

    @property
    def mixing_bowl(self) -> MixingBowlState:
        """搅拌盆状态"""
        return self._mixing_bowl

    def add_to_mixing_bowl(self, ingredient: str, recipe_slug: str | None = None) -> bool:
        """食材 → 搅拌盆（带配方校验）"""
        # 搅拌盆最多 2 种食材
        if len(self._mixing_bowl.ingredients) >= 2:
            logger.warning(f"[t={self.time:.1f}s] Mixing bowl full, cannot add {ingredient}")
            return False

        # 如果搅拌盆为空，设置目标配方
        if self._mixing_bowl.is_empty:
            if recipe_slug:
                self._mixing_bowl.target_recipe_slug = recipe_slug
            else:
                # 推断配方
                inferred = self._infer_dessert_recipe(ingredient)
                if inferred:
                    self._mixing_bowl.target_recipe_slug = inferred

        # 校验食材是否属于目标配方
        if self._mixing_bowl.target_recipe_slug:
            recipe = self._recipes.get(self._mixing_bowl.target_recipe_slug)
            if recipe:
                raw_ings = recipe.raw_ingredients
                if ingredient not in raw_ings:
                    logger.warning(
                        f"[t={self.time:.1f}s] Ingredient {ingredient} not in dessert recipe {self._mixing_bowl.target_recipe_slug}"
                    )
                    return False

        # 检查重复
        if ingredient in self._mixing_bowl.ingredients:
            logger.warning(f"[t={self.time:.1f}s] Ingredient {ingredient} already in mixing bowl")
            return False

        self._mixing_bowl.ingredients.append(ingredient)
        logger.info(f"[t={self.time:.1f}s] Added {ingredient} to mixing bowl")
        return True

    def add_condiment_to_mixing_bowl(self, condiment: str) -> bool:
        """调料 → 搅拌盆（校验目标配方）"""
        if self._mixing_bowl.is_empty:
            logger.warning(f"[t={self.time:.1f}s] Mixing bowl is empty, cannot add condiment")
            return False

        if self._mixing_bowl.target_recipe_slug:
            recipe = self._recipes.get(self._mixing_bowl.target_recipe_slug)
            if recipe is not None:
                recipe_condiments = recipe.condiments
                if isinstance(recipe_condiments, dict):
                    max_count = recipe_condiments.get(condiment, 0)
                    valid = max_count > 0
                else:
                    valid = condiment in recipe_condiments

                if not valid:
                    logger.warning(
                        f"[t={self.time:.1f}s] Condiment {condiment} not in recipe {self._mixing_bowl.target_recipe_slug}"
                    )
                    return False
                current = self._mixing_bowl.condiments.get(condiment, 0)
                if current >= max_count:
                    logger.warning(
                        f"[t={self.time:.1f}s] Condiment {condiment} already at max ({max_count}) for recipe {self._mixing_bowl.target_recipe_slug}"
                    )
                    return False

        current = self._mixing_bowl.condiments.get(condiment, 0)
        self._mixing_bowl.condiments[condiment] = current + 1
        logger.info(f"[t={self.time:.1f}s] Added condiment {condiment} to mixing bowl")
        return True

    def stir_mixing_bowl(self) -> bool:
        """搅拌操作"""
        if self._mixing_bowl.is_empty:
            logger.warning(f"[t={self.time:.1f}s] Mixing bowl is empty, cannot stir")
            return False

        if self._mixing_bowl.is_stirred:
            logger.warning(f"[t={self.time:.1f}s] Mixing bowl already stirred")
            return False

        self._mixing_bowl.is_stirred = True
        logger.info(f"[t={self.time:.1f}s] Stirred mixing bowl")
        return True

    def move_mixing_bowl_to_cooker(self, cooker: str) -> bool:
        """搅拌盆 → 灶台"""
        if not self._mixing_bowl.is_stirred:
            logger.warning(f"[t={self.time:.1f}s] Mixing bowl not stirred, cannot move to cooker")
            return False

        if cooker not in self._cookers:
            logger.error(f"Unknown cooker: {cooker}")
            return False

        cooker_state = self._cookers[cooker]
        if cooker_state.busy:
            logger.warning(f"Cooker {cooker} is busy")
            return False

        # 获取配方的烹饪时长
        recipe = self._recipes.get(self._mixing_bowl.target_recipe_slug)
        if not recipe:
            logger.error(f"Recipe not found: {self._mixing_bowl.target_recipe_slug}")
            return False

        # 甜点配方只有一个 cooker，取第一个
        cookers = recipe.cookers
        durations = recipe.cook_durations
        if not cookers or not durations:
            logger.error(f"Recipe {self._mixing_bowl.target_recipe_slug} has no cookers/durations")
            return False

        # 校验 cooker 类型
        if cookers[0] != cooker:
            logger.warning(f"Recipe requires {cookers[0]}, not {cooker}")
            return False

        duration = durations[0]

        # 开始烹饪
        cooker_state.busy = True
        cooker_state.item_name = self._mixing_bowl.target_recipe_slug
        cooker_state.cooker_type = cooker
        cooker_state.started_at = self.time
        cooker_state.done_at = self.time + duration
        cooker_state.expired_at = self.time + duration + self._cooker_retention

        # 清空搅拌盆
        self._mixing_bowl.reset()

        logger.info(f"[t={self.time:.1f}s] Moved mixing bowl to {cooker} ({duration}s)")
        return True

    def serve_from_cooker(self, cooker: str, slot_idx: int) -> bool:
        """灶台 → 取餐台（甜点专用）"""
        if cooker not in self._cookers:
            return False

        cooker_state = self._cookers[cooker]
        if not cooker_state.busy or cooker_state.done_at is None:
            return False

        if self.time < cooker_state.done_at:
            logger.warning(f"[t={self.time:.1f}s] Cooker {cooker} not done yet")
            return False

        if cooker_state.is_expired(self.time):
            logger.warning(f"[t={self.time:.1f}s] Cooker {cooker} expired")
            return False

        if slot_idx < 0 or slot_idx >= len(self._orders):
            return False

        order = self._orders[slot_idx]
        if order is None:
            return False

        # 校验订单是否匹配
        recipe_slug = cooker_state.item_name
        if order.recipe_slug != recipe_slug:
            logger.warning(
                f"[t={self.time:.1f}s] Order {order.order_id} expects {order.recipe_slug}, not {recipe_slug}"
            )
            return False

        # 送餐
        order.done = True
        cooker_state.reset()
        self.set_animation_window(1.5)

        # 移除订单
        self._orders[slot_idx] = None
        self._shift_orders_left()

        logger.info(
            f"[t={self.time:.1f}s] Served dessert {recipe_slug} from {cooker} slot {slot_idx}"
        )
        return True

    def clear_mixing_bowl(self) -> bool:
        """清空搅拌盆"""
        if self._mixing_bowl.is_empty:
            return False
        discarded = self._mixing_bowl.ingredients.copy()
        self._mixing_bowl.reset()
        logger.info(f"[t={self.time:.1f}s] Cleared mixing bowl (discarded: {discarded})")
        return True

    def _infer_dessert_recipe(self, ingredient: str) -> str | None:
        """根据单个食材推断甜点配方"""
        for order in self._orders:
            if order and not order.done:
                recipe = self._recipes.get(order.recipe_slug)
                if recipe:
                    station = recipe.station
                    if station == Station.DESSERT:
                        raw_ings = recipe.raw_ingredients
                        if ingredient in raw_ings:
                            return order.recipe_slug
        return None

### 4.2 Operator 灶台推断职责

**文件**：`src/hawarma/game/operator.py`

`Operator._build_mappings()` 是灶台名称和坐标的**唯一推断来源**。`config.cookers` 已移除，不再作为灶台列表的配置入口。

#### 构造顺序变更

`Runner.__init__` 调整构造顺序：**Operator 先于 GameEnv 构建**。

```python
# runner.py — 调整后的构造顺序
def __init__(self, env: GastronomeEnv | DessertEnv, operator: Operator,
             scanner: Scanner, verifier: Verifier, strategy: Strategy):
    # 1. Operator 已在 cli.py 创建（从 recipes 推断灶台名称和坐标）
    self.ui = operator
    self.env = env
    # ...
```

#### `_build_mappings()` 的 station 分支

| station | cooker 来源 | 坐标来源 | 映射方式 |
|---------|-----------|---------|---------|
| GASTRONOME | `recipe.cookers_layout` 去重 | `config.screen.cookers_positions` | 槽位分配（1→[1], 2→[1,2], ...） |
| DESSERT | `recipe.cookers` 去重 | `config.stations.dessert.cookers_positions` | 固定映射（字典 key→value） |

当前 Operator 的 `_build_mappings()` 对 gastronome 灶台使用槽位分配（`operator.py:96-114`）。新增 dessert 分支：遍历 `recipe.cookers` 收集 cooker 名称，直接从 `stations.dessert.cookers_positions` 读取固定坐标写入 `self._cooker_positions`。

```python
def _build_mappings(self) -> None:
    if self._station == Station.DESSERT:
        # ── Dessert 分支：固定坐标 ──
        cooker_positions = self.config.stations.dessert.cookers_positions
        for cooker_name, pos in cooker_positions.items():
            self._cooker_positions[cooker_name] = tuple(pos)
        # 食材和调料位置逻辑与 gastronome 相同
    else:
        # ── Gastronome 分支：现有逻辑 ──
        # 通过 cookers_layout 去重确定灶台名称和槽位
        ...
```

#### 甜点 serve 不验证

##### 动画窗口守卫

`Runner._agent_loop`（`runner.py:296`）现有守卫逻辑：

```python
if in_animation and action_type == "ServeOrderAction":
    continue
```

需同步添加 `ServeFromCookerAction` 跳过送餐：

```python
if in_animation and action_type in ("ServeOrderAction", "ServeFromCookerAction"):
    continue
```


Phase 1 中甜点 `serve_from_cooker` 不执行验证。直接执行 `ui.serve_from_cooker()` + `env.serve_from_cooker()` 后记录统计和 ghost 保护。后续若某操作失误率偏高再针对性地添加验证。

### 4.3 Runner 架构：DI + ExecMixin

**文件**：`src/hawarma/game/runner.py`

Runner 使用**构造函数注入**接收所有组件，使用 **ExecMixin** 模式组织 station 专用执行方法。

#### 组装根在 cli.py

```python
# cli.py — 组装根
station = Station(args.station)  # 或 TUI 选择
station_recipes = [r for r in all_recipes if r.station == station]
strategy = get_strategy(args.strategy)

# 创建组件
operator = Operator(config, station_recipes, station)
scanner = Scanner(config, station_recipes)
verifier = Verifier(config)
cooker_names = list(operator.cooker_positions.keys())

# 创建 Env 并按 station 类型标注
if station == Station.GASTRONOME:
    env: GastronomeEnv = GameEnv(cooker_names=cooker_names, stockpile_slots=3, ...)
else:
    env: DessertEnv = GameEnv(cooker_names=cooker_names, stockpile_slots=0, ...)

# 注入 Runner
runner = GastronomeRunner(env, operator, scanner, verifier, strategy) if station == Station.GASTRONOME \
    else DessertRunner(env, operator, scanner, verifier, strategy)
```

#### Runner 类层次

```
Runner(ABC)
  │  共享：_scan_loop, _timeout_loop, _agent_loop, _execute_action 分发
  │  共享 exec：_exec_cook, _exec_clear_cooker
  │
  ├── GastronomeRunner(Runner, GastronomeExecMixin)
  │     exec：_exec_move_to_assembly, _exec_add_condiment,
  │           _exec_serve_order, _exec_move_to_stockpile,
  │           _exec_pull_from_stockpile, _exec_clear_assembly
  │
  └── DessertRunner(Runner, DessertExecMixin)
        exec：_exec_move_to_mixing_bowl, _exec_add_condiment_to_mixing_bowl,
              _exec_stir, _exec_move_mixing_bowl_to_cooker,
              _exec_serve_from_cooker, _exec_clear_mixing_bowl
```

#### ExecMixin 分发机制

`_execute_action` 在 Runner 基类中定义，使用 dispatch table 模式：

```python
class Runner(ABC):
    # 共享 action → exec 方法映射
    _EXEC_MAP: ClassVar[dict[str, str]] = {
        "ClearCookerAction": "_exec_clear_cooker",
        "CookAction": "_exec_cook",
    }

    async def _execute_action(self, action) -> None:
        handler_name = self._EXEC_MAP.get(type(action).__name__)
        if handler_name:
            await getattr(self, handler_name)(action)
        else:
            logger.warning(f"Unhandled action: {type(action).__name__}")

    async def _exec_cook(self, action): ...        # 共享
    async def _exec_clear_cooker(self, action): ...  # 共享


class GastronomeExecMixin:
    _EXEC_MAP: ClassVar[dict[str, str]] = {
        **Runner._EXEC_MAP,
        "MoveToAssemblyAction": "_exec_move_to_assembly",
        "AddCondimentAction": "_exec_add_condiment",
        "ServeOrderAction": "_exec_serve_order",
        # ...
    }
    async def _exec_move_to_assembly(self, action): ...
    async def _exec_add_condiment(self, action): ...
    async def _exec_serve_order(self, action): ...


class DessertExecMixin:
    _EXEC_MAP: ClassVar[dict[str, str]] = {
        **Runner._EXEC_MAP,
        "MoveToMixingBowlAction": "_exec_move_to_mixing_bowl",
        "AddCondimentToMixingBowlAction": "_exec_add_condiment_to_mixing_bowl",
        "StirAction": "_exec_stir",
        "MoveMixingBowlToCookerAction": "_exec_move_mixing_bowl_to_cooker",
        "ServeFromCookerAction": "_exec_serve_from_cooker",
        "ClearMixingBowlAction": "_exec_clear_mixing_bowl",
    }
    async def _exec_move_to_mixing_bowl(self, action): ...
    async def _exec_add_condiment_to_mixing_bowl(self, action): ...
    async def _exec_stir(self, action): ...
    # ...


class GastronomeRunner(GastronomeExecMixin, Runner): ...
class DessertRunner(DessertExecMixin, Runner): ...
```

#### station 从 Env 类型推断

Runner 不再需要显式 `station` 参数。station 信息隐含在 Env 类型中：

```python
class Runner(ABC):
    def __init__(self, env: Env, operator: Operator, scanner: Scanner,
                 verifier: Verifier, strategy: Strategy):
        self.env = env
        self.ui = operator
        self.scanner = scanner
        self.verifier = verifier
        self.strategy = strategy
```

当需要根据 station 分支时（如 `_agent_loop` 的动画守卫），通过 `isinstance` 检查：

```python
if isinstance(self.env, DessertEnv) and action_type == "ServeFromCookerAction":
    continue
```

#### Scanner / Verifier 传入策略

Scanner 和 Verifier 通过 DI 直接传入 Runner（不强制定义抽象接口）。创建逻辑集中在 cli.py。这比 Env/Operator 的注入要求更低——Scanner 和 Verifier 硬件依赖性强，不需要替换实现，但集中在 cli.py 创建便于管理依赖关系。

---

## 5. DessertStrategy 实现

**文件**：`src/hawarma/agent/strategies/dessert.py`

### 5.1 策略概述

DessertStrategy 是甜点专用策略，采用流水线决策逻辑：
- 当当前订单在烹饪时，开始下一个订单的食材收集和搅拌
- 优先处理 rush 订单，然后先进先出
- 管理并发订单（最多 2 个）

### 5.2 决策优先级

```
1. 送餐（灶台→取餐台）
2. 清理过期灶台
3. 移动搅拌盆到灶台（搅拌完成 + 灶台空闲）
4. 搅拌（食材齐全 + 未搅拌）
5. 添加调料（食材齐全 + 未调味完成）
6. 添加食材到搅拌盆
7. 清理搅拌盆（无匹配订单）
```

### 5.3 代码实现

```python
"""
DessertStrategy: 甜点策略

甜点流程：
1. 食材A → 搅拌盆
2. 食材B → 搅拌盆
3. 调味（搅拌盆）
4. 搅拌（搅拌盆内单次左滑 swipe）
5. 搅拌盆 → 灶台烹饪
6. 烹饪完成 → 取餐台（直接从灶台）

决策优先级：
1. 送餐（灶台→取餐台）
2. 清理过期灶台
3. 移动搅拌盆到灶台（搅拌完成 + 灶台空闲）
4. 搅拌（食材齐全 + 未搅拌）
5. 添加调料（食材齐全 + 未调味）
6. 添加食材到搅拌盆
7. 清理搅拌盆（无匹配订单）
"""

from __future__ import annotations

from loguru import logger

from hawarma.core.actions import (
    Action,
    AddCondimentToMixingBowlAction,
    ClearCookerAction,
    ClearMixingBowlAction,
    MoveToMixingBowlAction,
    ServeFromCookerAction,
    StirAction,
    MoveMixingBowlToCookerAction,
)
from hawarma.core.state import UnifiedState
from hawarma.agent.strategy import Strategy
from hawarma.recipe import Station


class DessertStrategy(Strategy):
    """甜点策略：搅拌盆流水线"""

    def __init__(self):
        self._recipe_by_slug: dict[str, object] = {}
        self._recipe_condiments: dict[str, dict[str, int]] = {}
        self._dessert_recipes: dict[str, object] = {}

    def on_game_start(self, recipes: dict[str, object]) -> None:
        self._recipe_by_slug = recipes
        self._recipe_condiments = {}
        self._dessert_recipes = {}

        for slug, recipe in recipes.items():
            station = recipe.station
            if station == Station.DESSERT:
                self._dessert_recipes[slug] = recipe

            condiments = recipe.condiments
            if isinstance(condiments, list):
                self._recipe_condiments[slug] = {c: 1 for c in condiments}
            elif isinstance(condiments, dict):
                self._recipe_condiments[slug] = dict(condiments)
            else:
                self._recipe_condiments[slug] = {}

    def decide(self, state: UnifiedState) -> Action | None:
        """甜点决策流水线"""
        mixing_bowl = state.mixing_bowl

        # 1. 送餐（灶台→取餐台）
        if action := self._try_serve_from_cooker(state):
            return action

        # 2. 清理过期灶台
        if action := self._try_clear_expired(state):
            return action

        # 3. 移动搅拌盆到灶台（搅拌完成 + 灶台空闲）
        if action := self._try_move_mixing_bowl_to_cooker(state):
            return action

        # 4. 搅拌（食材齐全 + 未搅拌）
        if action := self._try_stir(state):
            return action

        # 5. 添加调料（食材齐全 + 未调味完成）
        if action := self._try_add_condiment(state):
            return action

        # 6. 添加食材到搅拌盆
        if action := self._try_add_to_mixing_bowl(state):
            return action

        # 7. 清理搅拌盆（无匹配订单）
        if action := self._try_clear_mixing_bowl(state):
            return action

        return None

    # ====================================================================
    # 送餐（灶台→取餐台）
    # ====================================================================

    def _try_serve_from_cooker(self, state: UnifiedState) -> ServeFromCookerAction | None:
        if state.is_in_animation_window:
            return None

        for cooker_name, cooker in state.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            if state.time < cooker.done_at:
                continue
            if cooker.is_expired(state.time):
                continue

            recipe_slug = cooker.item_name
            # 找匹配的订单
            for slot_idx, order in enumerate(state.orders):
                if order and not order.done and order.recipe_slug == recipe_slug:
                    return ServeFromCookerAction(cooker=cooker_name, slot_idx=slot_idx)

        return None

    # ====================================================================
    # 清理过期灶台
    # ====================================================================

    def _try_clear_expired(self, state: UnifiedState) -> ClearCookerAction | None:
        for cooker_name, cooker in state.cookers.items():
            if cooker.busy and cooker.is_expired(state.time):
                return ClearCookerAction(cooker=cooker_name)
        return None

    # ====================================================================
    # 移动搅拌盆到灶台
    # ====================================================================

    def _try_move_mixing_bowl_to_cooker(self, state: UnifiedState) -> MoveMixingBowlToCookerAction | None:
        mixing_bowl = state.mixing_bowl
        if not mixing_bowl.is_ready_to_cook:
            return None

        recipe_slug = mixing_bowl.target_recipe_slug
        if not recipe_slug:
            return None

        recipe = state.recipes.get(recipe_slug)
        if not recipe:
            return None

        cookers = recipe.cookers
        if not cookers:
            return None

        cooker_type = cookers[0]
        cooker_state = state.cookers.get(cooker_type)
        if cooker_state and not cooker_state.busy:
            return MoveMixingBowlToCookerAction(cooker=cooker_type)

        return None

    # ====================================================================
    # 搅拌
    # ====================================================================

    def _try_stir(self, state: UnifiedState) -> StirAction | None:
        mixing_bowl = state.mixing_bowl
        if mixing_bowl.is_empty:
            return None
        if mixing_bowl.is_stirred:
            return None
        if len(mixing_bowl.ingredients) < 2:
            return None

        # 检查调料是否齐全（搅拌前需要先调味）
        recipe_slug = mixing_bowl.target_recipe_slug
        if recipe_slug:
            condiments_needed = self._recipe_condiments.get(recipe_slug, {})
            if condiments_needed:
                for condiment, count in condiments_needed.items():
                    if mixing_bowl.condiments.get(condiment, 0) < count:
                        return None  # 调料未齐全，先调味

        return StirAction(distance=400.0, duration=1.5, steps=10)

    # ====================================================================
    # 添加调料
    # ====================================================================

    def _try_add_condiment(self, state: UnifiedState) -> AddCondimentToMixingBowlAction | None:
        mixing_bowl = state.mixing_bowl
        if mixing_bowl.is_empty:
            return None
        if mixing_bowl.is_stirred:
            return None

        recipe_slug = mixing_bowl.target_recipe_slug
        if not recipe_slug:
            return None

        condiments_needed = self._recipe_condiments.get(recipe_slug, {})
        if not condiments_needed:
            return None

        for condiment, count in condiments_needed.items():
            current = mixing_bowl.condiments.get(condiment, 0)
            if current < count:
                return AddCondimentToMixingBowlAction(condiment=condiment)

        return None

    # ====================================================================
    # 添加食材到搅拌盆
    # ====================================================================

    def _try_add_to_mixing_bowl(self, state: UnifiedState) -> MoveToMixingBowlAction | None:
        mixing_bowl = state.mixing_bowl
        if len(mixing_bowl.ingredients) >= 2:
            return None

        # 找到最高优先级的甜点订单
        for _, order in self._prioritized_dessert_orders(state):
            recipe = state.recipes.get(order.recipe_slug)
            if not recipe:
                continue

            raw_ings = recipe.raw_ingredients
            for ing in raw_ings:
                if ing not in mixing_bowl.ingredients:
                    return MoveToMixingBowlAction(ingredient=ing)

        return None

    # ====================================================================
    # 清理搅拌盆
    # ====================================================================

    def _try_clear_mixing_bowl(self, state: UnifiedState) -> ClearMixingBowlAction | None:
        mixing_bowl = state.mixing_bowl
        if mixing_bowl.is_empty:
            return None

        # 检查是否有匹配的活跃订单
        recipe_slug = mixing_bowl.target_recipe_slug
        if recipe_slug:
            has_active = any(
                o and not o.done and o.recipe_slug == recipe_slug
                for o in state.orders
            )
            if has_active:
                return None

        # 无匹配订单，清理搅拌盆
        return ClearMixingBowlAction()

    # ====================================================================
    # 辅助方法
    # ====================================================================

    def _prioritized_dessert_orders(self, state: UnifiedState) -> list[tuple[int, object]]:
        """按优先级排序甜点订单"""
        orders_with_idx = []
        for i, order in enumerate(state.orders):
            if order is not None and not order.done:
                recipe = state.recipes.get(order.recipe_slug)
                if recipe:
                    station = recipe.station
                    if station == Station.DESSERT:
                        orders_with_idx.append((i, order))

        def sort_key(item):
            _, order = item
            rush_priority = 0 if order.is_rush else 1
            timeout_remaining = order.timeout_at - state.time
            return (rush_priority, timeout_remaining)

        orders_with_idx.sort(key=sort_key)
        return orders_with_idx
```

---

## 6. 配置结构

**文件**：`configs/config.yaml`

```yaml
# 灶台坐标来自 config.screen.cookers_positions（gastronome）或
# stations.dessert.cookers_positions（dessert）。
# 灶台名称从 recipes 推断，不由配置文件直接指定。

# 新增：站点配置
stations:
  gastronome:
    enabled: true
    cooker_retention: 4.7  # 秒，食材在灶台最多停留时间
    serve_verify_wait: 0.4

  dessert:
    enabled: true
    stir:
      distance: 400        # 滑动距离（像素）
      duration: 1.5        # 滑动持续时间（秒）
      steps: 10            # Airtest 插值步数
    mixing_bowl_position:  # 搅拌盆屏幕坐标
      - 1245
      - 870
    cookers_positions:     # 甜点灶台固定坐标（不动态分配槽位）
      dessert_oven:
        - 715
        - 615
      cooling_plate:
        - 1260
        - 590
    cooker_retention: 5.0  # 甜点灶台食材停留时间

# 现有 game 配置保留
game:
  cooker_retention: 4.7
  # ...
```

**文件**：`src/hawarma/config.py`

```python
class StirConfig(BaseModel):
    """搅拌操作配置（单次左滑）"""
    distance: int = 400        # 滑动距离（像素）
    duration: float = 1.5      # 滑动持续时间（秒）
    steps: int = 10            # Airtest 插值步数


class DessertStationConfig(BaseModel):
    """甜点站点配置"""
    enabled: bool = True
    stir: StirConfig = Field(default_factory=StirConfig)
    mixing_bowl_position: tuple[int, int] = (1245, 870)
    cookers_positions: dict[str, tuple[int, int]] = {
        "dessert_oven": (715, 615),
        "cooling_plate": (1260, 590),
    }
    cooker_retention: float = 5.0


class GastronomeStationConfig(BaseModel):
    """美食站点配置"""
    enabled: bool = True
    cooker_retention: float = 4.7
    serve_verify_wait: float = 0.4


class StationsConfig(BaseModel):
    """站点配置"""
    gastronome: GastronomeStationConfig = Field(default_factory=GastronomeStationConfig)
    dessert: DessertStationConfig = Field(default_factory=DessertStationConfig)


class AppConfig(BaseModel):
    # 现有字段
    ...
    # 注：cookers 字段已移除，灶台名称从 recipes 动态推断
    # 灶台坐标配置：
    #   gastronome: screen.cookers_positions（槽位分配）
    #   dessert:    stations.dessert.cookers_positions（固定映射）
    # 新增
    stations: StationsConfig = Field(default_factory=StationsConfig)
```

---

## 7. 文件组织

### 7.1 新增文件

| 文件 | 用途 |
|------|------|
| `src/hawarma/agent/strategies/dessert.py` | DessertStrategy 实现 |
| `docs/dessert_station.md` | 本文档 |

### 7.2 修改文件

| 文件 | 变更 |
|------|------|
| `src/hawarma/core/models.py` | 添加 `MixingBowlState` 数据类；`CookerState.ingredient_name` 重命名为 `item_name` |
| `src/hawarma/core/state.py` | 添加 `mixing_bowl` 和 `station` 字段 |
| `src/hawarma/core/actions.py` | 添加 6 个甜点 Action 类型（含 `AddCondimentToMixingBowlAction`） |
| `src/hawarma/core/__init__.py` | 导出新 Action |
| `src/hawarma/game/env.py` | 拆分为 `Env`（共享）+ `GastronomeEnv(Env)` + `DessertEnv(Env)` 三个接口 |
| `src/hawarma/game/game_env.py` | 实现 `GastronomeEnv` 和 `DessertEnv` 全部方法 + `MixingBowlState` 初始化 |
| `src/hawarma/game/operator.py` | `_build_mappings()` 按 station 分支；新增 `stir()`、`add_condiment_to_mixing_bowl()`、`move_mixing_bowl_to_cooker()`、`serve_from_cooker()` |
| `src/hawarma/game/runner.py` | 拆分为 `Runner(ABC)` + `GastronomeExecMixin` + `DessertExecMixin` + `GastronomeRunner` + `DessertRunner`；DI 注入；动画守卫 |
| `src/hawarma/game/scanner.py` | 无需改代码。依赖模板图像：`ingredient-{dessert_ingredient_name}.jpg`（由用户后续添加） |
| `src/hawarma/game/verifier.py` | Phase 1 无变更。甜点 serve 不验证，后续迭代按需添加 |
| `src/hawarma/config.py` | 添加 `StationsConfig`、`DessertStationConfig` 等；移除 `cookers` 字段 |
| `src/hawarma/agent/registry.py` | 注册 `dessert` 策略 |
| `src/hawarma/agent/strategies/__init__.py` | 导出 `DessertStrategy` |
| `configs/config.yaml` | 添加 `stations` 配置节；移除 `cookers` 字段 |
| `cli.py` | 增加 `--station` CLI 参数；recipe 按 station 过滤；**组装根**（创建 Operator→GameEnv→Runner，DI 注入） |
| `tui.py` | 增加 station 选择 UI；recipe 按 station 过滤；组装根 |
| `docs/ARCHITECTURE.md` | 更新文档列表 |
| `docs/game_rules.md` | 添加甜点模式规则 |
| `docs/agent_strategy.md` | 添加甜点策略说明 |

### 7.3 新增测试文件

| 文件 | 用途 |
|------|------|
| `tests/test_mixing_bowl.py` | MixingBowlState 单元测试 |
| `tests/test_dessert_strategy.py` | DessertStrategy 单元测试 |
| `tests/test_dessert_env.py` | GameEnv 甜点方法测试 |

---

## 8. 实现步骤

### Phase 0：Station 模式选择机制 + DI 架构

| 步骤 | 任务 | 验证 |
|------|------|------|
| 0.1 | 设计 CLI `--station` 参数（`cli.py`） | `python -m hawarma --station dessert` 可用 |
| 0.2 | TUI 配置面板增加 station dropwdown（`tui.py`） | UI 可切换 station |
| 0.3 | `cli.py` 和 `tui.py` 的 recipe 列表按 station 过滤 | 选择 station 后食谱列表对应 |
| 0.4 | 拆分 Env 接口：`Env`（共享）+ `GastronomeEnv(Env)` + `DessertEnv(Env)` | Import 成功 |
| 0.5 | `GameEnv` 实现 `GastronomeEnv` 和 `DessertEnv` | Import 成功 |
| 0.6 | `Operator._build_mappings()` 根据 station 分支 | 坐标映射正确 |
| 0.7 | 移除 `AppConfig.cookers` 和 `config.yaml` 中的 `cookers` 字段 | 配置加载正常 |
| 0.8 | `cli.py` 作为组装根：创建 Operator→GameEnv→Runner，DI 注入 | Runner 构造正确 |
| 0.9 | 拆分 Runner：`Runner(ABC)` + `GastronomeExecMixin` + `DessertExecMixin` + 子类 | Import 成功 |
| 0.10 | 运行现有测试 | 全部通过 |

### Phase 1：数据层（无破坏性变更）

| 步骤 | 任务 | 验证 |
|------|------|------|
| 1.1 | 在 `core/models.py` 添加 `MixingBowlState` | Import 成功 |
| 1.2 | 在 `core/state.py` 添加 `mixing_bowl` 和 `station` 字段 | Import 成功 |
| 1.3 | 在 `core/actions.py` 添加 6 个甜点 Action（含 `AddCondimentToMixingBowlAction`） | Import 成功 |
| 1.4 | 更新 `core/__init__.py` 导出 | Import 成功 |
| 1.5 | 运行现有测试：`python -m unittest discover tests` | 全部通过 |

### Phase 2：GameEnv 实现

| 步骤 | 任务 | 验证 |
|------|------|------|
| 2.1 | 在 `game/game_env.py` 实现 `DessertEnv` 全部方法 | Import 成功 |
| 2.2 | 更新 `get_unified_state()` 包含 `mixing_bowl` 和 `station` | Import 成功 |
| 2.3 | 运行现有测试 | 全部通过 |

### Phase 3：DessertStrategy

| 步骤 | 任务 | 验证 |
|------|------|------|
| 3.1 | 创建 `agent/strategies/dessert.py` | Import 成功 |
| 3.2 | 在 `agent/registry.py` 注册 | `get_strategy("dessert")` 可用 |
| 3.3 | 更新 `agent/strategies/__init__.py` | Import 成功 |
| 3.4 | 编写 DessertStrategy 单元测试 | 测试通过 |

### Phase 4：Operator & Runner

| 步骤 | 任务 | 验证 |
|------|------|------|
| 4.1 | `Operator._build_mappings()` 根据 station 分支 | 坐标映射正确 |
| 4.2 | 在 `Operator` 添加 `add_condiment_to_mixing_bowl()`、`stir()`、`move_mixing_bowl_to_cooker()`、`serve_from_cooker()` | Import 成功 |
| 4.3 | 拆分 Runner：`Runner(ABC)` + `GastronomeExecMixin` + `DessertExecMixin` + `GastronomeRunner` + `DessertRunner` | Import 成功 |
| 4.4 | `cli.py` 作为组装根，创建组件后 DI 注入 Runner | 运行正确 |
| 4.5 | `Runner._agent_loop` 添加 `ServeFromCookerAction` 到动画窗口守卫 | Import 成功 |
| 4.6 | 运行集成测试 | 全部通过 |

### Phase 5：配置

| 步骤 | 任务 | 验证 |
|------|------|------|
| 5.1 | 在 `config.py` 添加 `StationsConfig` 模型；移除 `cookers` 字段 | Import 成功 |
| 5.2 | 在 `config.yaml` 添加 `stations` 配置节；移除 `cookers` 字段 | 配置加载成功 |
| 5.3 | 运行所有测试 | 全部通过 |

### Phase 6：测试

| 步骤 | 任务 | 验证 |
|------|------|------|
| 6.1 | 编写 `test_mixing_bowl.py` | 测试通过 |
| 6.2 | 编写 `test_dessert_strategy.py` | 测试通过 |
| 6.3 | 编写 `test_dessert_env.py` | 测试通过 |
| 6.4 | 边界测试：搅拌盆满、重复搅拌、送餐错误订单 | 测试通过 |
| 6.5 | 运行完整测试套件：`python -m unittest discover tests` | 全部通过 |

---

## 9. 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 枚举名称 | `Station`（不是 `Platform`） | 已存在于 `recipe.py`，与代码库一致 |
| 状态追踪 | 隐式（`is_stirred` 标志） | 不引入显式状态机，更简单 |
| 搅拌盆 | 独立于组装站 | 不同物理位置 |
| CookerState 字段 | `ingredient_name` → `item_name` | 甜点模式下存 recipe slug，原字段名语义不准确 |
| DessertStrategy | 独立类 | 不同的流水线逻辑，不继承自 DefaultStrategy |
| 配置结构 | `stations` 顶级节 | 清晰分离站点特定设置 |
| 错误处理 | 记录日志 + 返回 False | 不实现重试机制，假设操作成功 |
| Action 命名 | `{Verb}{Object}Action` | 与现有约定一致 |
| 出餐方式 | 直接从灶台 | 甜点跳过组装站，直接从灶台出餐 |
| 调味 Action | 分离为 `AddCondimentToMixingBowlAction` | 甜点调味终点是搅拌盆，不是组装站，两个 Action 不可复用 |
| StirAction 参数 | 携带 `distance/duration/steps` 字段 | 与现有 Action 模式一致（如 CookAction 携带 duration） |
| Station 选择 | CLI `--station` + TUI 下拉框 | 由用户显式指定，不自动推断 |
| 灶台名称来源 | 从 recipes 推断（gastronome: `cookers_layout`，dessert: `cookers`） | `config.cookers` 已移除，名称不来自配置 |
| 灶台坐标映射 | `Operator._build_mappings()` 按 station 分支处理 | Operator 作为坐标推断的唯一权威 |
| 构造顺序 | Runner 先建 Operator，从 Operator 取 cooker_names 再建 GameEnv | GameEnv 不直接依赖 config，依赖 Operator 的推断结果 |
| 甜点 serve 验证 | Phase 1 不做验证 | 后续按实际失误率验证 |
| Recipe 过滤 | 选择 station 后只显示对应 station 的食谱 | 防止误选 |
| 动画窗口守卫 | `ServeFromCookerAction` 与 `ServeOrderAction` 一起跳过 | 防止送餐动画期操作冲突 |
| Env 接口拆分 | `Env`（共享）+ `GastronomeEnv(Env)` + `DessertEnv(Env)` | 避免胖接口，Runner 不会误调不属于当前 station 的方法 |
| Runner DI | 构造函数注入 Env、Operator、Scanner、Verifier | DIP 合规，cli.py 作为组装根 |
| Runner ExecMixin | `GastronomeExecMixin` / `DessertExecMixin` + dispatch table | exec 方法集按 station 分离，共享循环逻辑在基类 |
| station 推断 | 从 Env 类型推断（`isinstance(env, DessertEnv)`），无显式 station 参数 | Runner 不需要额外的 station 参数 |
| Scanner/Verifier | DI 传入但不强制定义抽象接口 | 硬件依赖性强，不需要替换实现，集中创建便于管理 |
| 半成品库存 | 后续迭代实现 | Phase 1 不包含半成品库存相关 Action 和逻辑 |

---

## 10. 甜点流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                    Dessert Pipeline                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  食材区 ──→ 搅拌盆 ──→ 调味 ──→ 搅拌 ──→ 灶台 ──→ 取餐台       │
│    │         │         │        │        │        │             │
│    │         │         │        │        │        │             │
│  MoveTo    AddCondTo  Stir   MoveMix   ServeFrom               │
│  MixingBowl MixingBowl       Bowl    ToCooker  Cooker           │
│                                                                 │
│  状态追踪：                                                      │
│  - MixingBowlState.ingredients  (list[str])                     │
│  - MixingBowlState.condiments   (dict[str, int])                │
│  - MixingBowlState.is_stirred   (bool)                          │
│  - CookerState (复用现有 CookerState)                            │
│                                                                 │
│  决策优先级：                                                    │
│  1. ServeFromCooker    — 灶台完成 → 送餐                        │
│  2. ClearCooker        — 过期清理                               │
│  3. MoveMixingBowlToCooker — 搅拌完成 → 灶台                    │
│  4. Stir               — 食材齐全 + 调料齐全 → 搅拌             │
│  5. AddCondToMixingBowl — 食材齐全 → 调味                       │
│  6. MoveToMixingBowl   — 添加食材                               │
│  7. ClearMixingBowl    — 无匹配订单 → 清理                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 11. 物理位置配置

| 元素 | 坐标 | 说明 |
|------|------|------|
| 搅拌盆 | (1245, 870) | 甜点专用搅拌盆 |
| dessert_oven | (715, 615) | 甜点烤箱（固定坐标，不动态分配） |
| cooling_plate | (1260, 590) | 冷却盘（固定坐标，不动态分配） |

---

## 12. 订单检测

### 12.1 甜点订单特点

- 只需检测第一个食材即可确定菜谱
- 第一个食材唯一确定菜谱（mooncake 和 snowskin mooncake 有特殊变种）
- 如果出现相同第一个食材的菜谱，需要检查第二个食材

### 12.2 检测流程

1. 扫描订单槽位
2. 检测第一个食材图像
3. 匹配菜谱（第一个食材唯一确定）
4. 如果有冲突，检测第二个食材

---

## 13. 并发处理

### 13.1 流水线决策

- 当当前订单在烹饪时，开始下一个订单的食材收集和搅拌
- 一般同时处理 2 个订单
- rush 订单优先处理，然后先进先出

### 13.2 资源管理

- **搅拌盆**：一次只能处理一个订单
- **cooker**：一次只能烹饪一个甜点

### 13.3 状态追踪

- 使用 `MixingBowlState` 追踪搅拌盆状态（食材、调味品、是否搅拌完成）
- 使用 `CookerState` 追踪 cooker 状态（复用现有）

---

## 14. 错误处理

### 14.1 策略

- 操作失败时记录日志
- 不实现重试机制
- 假设所有操作都成功
- 关注游戏逻辑的正确性

### 14.2 边界情况

- 搅拌盆已满：记录日志，返回 False
- cooker 已满：记录日志，返回 False
- 烹饪超时：清空 cooker

---

## 15. 测试策略

### 15.1 单元测试

- 测试 `MixingBowlState` 的所有属性和方法
- 测试 `DessertStrategy` 的决策逻辑
- 测试每个 Action 的创建和执行

### 15.2 集成测试

- 测试完整的甜点流程
- 测试并发订单处理
- 测试资源锁定

### 15.3 边界测试

- 测试搅拌盆满的情况
- 测试重复搅拌
- 测试送餐错误订单
- 测试超时处理

---

## 16. 监控和日志

### 16.1 监控指标

- 订单处理时间
- 资源使用情况
- 成功率

### 16.2 日志记录

- 详细的操作日志
- 错误和异常日志
- 使用现有的日志级别设置

---

## 17. 未来扩展

### 17.1 支持更多甜点类型

- 架构设计支持未来添加新的甜点类型
- 只需在 `recipes.json` 中添加新的甜点菜谱

### 17.2 半成品库存（后续迭代）

- 储存位置：(675, 860)，只能储存一份
- 储存时机：搅拌完成后可以储存
- 取出时机：下一个订单需要相同菜谱时取出
- 需要新增 `AddToDessertStockpileAction` 和 `PullFromDessertStockpileAction`

### 17.3 可配置参数

- 搅拌参数（距离、steps 数、duration）可配置
- 位置参数可配置
- 超时参数可配置

---

## 18. 文档维护

### 18.1 更新文档

- `game_rules.md`：添加甜点模式规则
- `agent_strategy.md`：添加甜点策略说明
- `ARCHITECTURE.md`：更新架构图

### 18.2 文档关系

```
game_rules.md (基础)
    ↑
    ├── agent_strategy.md (策略+基准)
    ├── architecture_redesign.md (架构设计)
    ├── real_game_implementation.md (实现)
    └── dessert_station.md (甜点站点设计)
```
