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
| 库存支持 | 有（3种烹饪后的食材，每种各5份） | 有（半成品库存，仅1份） |
| 物理位置 | 组装站 | 搅拌盆（与组装站不同位置） |

### 1.2 甜点流程

```
食材区 → 搅拌盆 → 调味 → 搅拌 → 灶台烹饪 → 取餐台
  │         │       │      │        │        │
  │         │       │      │        │        │
MoveTo   AddCond  Stir  MoveMix   ServeFrom
MixingBowl        Bowl   ToCooker  Cooker
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

### 2.3 UnifiedState 扩展

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
class StirAction(Action):
    """搅拌（搅拌盆内往复 swipe）"""
    pass  # 坐标/次数/速度等参数从 config 读取


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
1. MoveToMixingBowlAction(ingredient="X")  — 食材A → 搅拌盆
2. MoveToMixingBowlAction(ingredient="Y")  — 食材B → 搅拌盆
3. AddCondimentAction(condiment="Z")       — 调味（共享动作）
4. StirAction()                            — 搅拌
5. MoveMixingBowlToCookerAction(cooker="dessert_oven") — 搅拌盆 → 灶台
6. ServeFromCookerAction(cooker="dessert_oven", slot_idx=0) — 灶台 → 取餐台
```

---

## 4. Env 接口扩展

**文件**：`src/hawarma/game/env.py`

```python
class Env(ABC):
    # ── 现有方法（Gastronome） ──
    # ... (unchanged)

    # ── 新增方法（Dessert） ──
    @abstractmethod
    def add_to_mixing_bowl(self, ingredient: str, recipe_slug: str | None = None) -> bool:
        """食材 → 搅拌盆"""

    @abstractmethod
    def stir_mixing_bowl(self) -> bool:
        """搅拌操作"""

    @abstractmethod
    def move_mixing_bowl_to_cooker(self, cooker: str) -> bool:
        """搅拌盆 → 灶台"""

    @abstractmethod
    def serve_from_cooker(self, cooker: str, slot_idx: int) -> bool:
        """灶台 → 取餐台（甜点专用）"""

    @abstractmethod
    def clear_mixing_bowl(self) -> bool:
        """清空搅拌盆"""
```

### 4.1 GameEnv 实现

**文件**：`src/hawarma/game/game_env.py`

```python
class GameEnv(Env):
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
                raw_ings = getattr(recipe, "raw_ingredients", [])
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
        cookers = getattr(recipe, "cookers", [])
        durations = getattr(recipe, "cook_durations", [])
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
        cooker_state.ingredient_name = self._mixing_bowl.target_recipe_slug
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
        recipe_slug = cooker_state.ingredient_name
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
                    station = getattr(recipe, "station", Station.GASTRONOME)
                    if station == Station.DESSERT:
                        raw_ings = getattr(recipe, "raw_ingredients", [])
                        if ingredient in raw_ings:
                            return order.recipe_slug
        return None
```

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
4. 搅拌（搅拌盆内往复 swipe）
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
    AddCondimentAction,
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
            station = getattr(recipe, "station", Station.GASTRONOME)
            if station == Station.DESSERT:
                self._dessert_recipes[slug] = recipe

            condiments = getattr(recipe, "condiments", [])
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

            recipe_slug = cooker.ingredient_name
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

        cookers = getattr(recipe, "cookers", [])
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

        return StirAction()

    # ====================================================================
    # 添加调料
    # ====================================================================

    def _try_add_condiment(self, state: UnifiedState) -> AddCondimentAction | None:
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
                return AddCondimentAction(condiment=condiment)

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

            raw_ings = getattr(recipe, "raw_ingredients", [])
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
                    station = getattr(recipe, "station", Station.GASTRONOME)
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
# 现有配置保持不变
adb_address: 127.0.0.1:16384
image_directory: static/img
# ...

# 新增：站点配置
stations:
  gastronome:
    enabled: true
    cooker_retention: 4.7  # 秒，食材在灶台最多停留时间
    serve_verify_wait: 0.4

  dessert:
    enabled: true
    stir:
      swipes: 3           # 搅拌往复次数
      duration: 0.3        # 每次 swipe 持续时间
      distance: 200        # swipe 距离（像素）
    mixing_bowl_position:  # 搅拌盆屏幕坐标
      - 1245
      - 870
    stockpile_position:    # 半成品库存屏幕坐标
      - 675
      - 860
    cooker_retention: 5.0  # 甜点灶台食材停留时间

# 现有 game 配置保留
game:
  cooker_retention: 4.7
  # ...
```

**文件**：`src/hawarma/config.py`

```python
class StirConfig(BaseModel):
    """搅拌操作配置"""
    swipes: int = 3
    duration: float = 0.3
    distance: int = 200


class DessertStationConfig(BaseModel):
    """甜点站点配置"""
    enabled: bool = True
    stir: StirConfig = Field(default_factory=StirConfig)
    mixing_bowl_position: tuple[int, int] = (1245, 870)
    stockpile_position: tuple[int, int] = (675, 860)
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
| `src/hawarma/core/models.py` | 添加 `MixingBowlState` 数据类 |
| `src/hawarma/core/state.py` | 添加 `mixing_bowl` 和 `station` 字段 |
| `src/hawarma/core/actions.py` | 添加 5 个甜点 Action 类型 |
| `src/hawarma/core/__init__.py` | 导出新 Action |
| `src/hawarma/game/env.py` | 添加 5 个抽象甜点方法 |
| `src/hawarma/game/game_env.py` | 实现 5 个甜点方法 + `MixingBowlState` 初始化 |
| `src/hawarma/config.py` | 添加 `StationsConfig`、`DessertStationConfig` 等 |
| `src/hawarma/agent/registry.py` | 注册 `dessert` 策略 |
| `src/hawarma/agent/strategies/__init__.py` | 导出 `DessertStrategy` |
| `src/hawarma/game/operator.py` | 添加 `stir()`、`move_mixing_bowl_to_cooker()`、`serve_from_cooker()` |
| `src/hawarma/game/runner.py` | 添加甜点 Action 执行分支 |
| `configs/config.yaml` | 添加 `stations` 配置节 |
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

### Phase 1：数据层（无破坏性变更）

| 步骤 | 任务 | 验证 |
|------|------|------|
| 1.1 | 在 `core/models.py` 添加 `MixingBowlState` | Import 成功 |
| 1.2 | 在 `core/state.py` 添加 `mixing_bowl` 和 `station` 字段 | Import 成功 |
| 1.3 | 在 `core/actions.py` 添加 5 个甜点 Action | Import 成功 |
| 1.4 | 更新 `core/__init__.py` 导出 | Import 成功 |
| 1.5 | 运行现有测试：`python -m unittest discover tests` | 全部通过 |

### Phase 2：Env 接口

| 步骤 | 任务 | 验证 |
|------|------|------|
| 2.1 | 在 `game/env.py` 添加 5 个抽象方法 | Import 成功 |
| 2.2 | 在 `game/game_env.py` 实现 5 个方法 | Import 成功 |
| 2.3 | 更新 `get_unified_state()` 包含 `mixing_bowl` 和 `station` | Import 成功 |
| 2.4 | 运行现有测试 | 全部通过 |

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
| 4.1 | 在 `Operator` 添加 `stir()`、`move_mixing_bowl_to_cooker()`、`serve_from_cooker()` | Import 成功 |
| 4.2 | 在 `Runner._execute_action()` 添加甜点 Action 分支 | Import 成功 |
| 4.3 | 运行集成测试 | 全部通过 |

### Phase 5：配置

| 步骤 | 任务 | 验证 |
|------|------|------|
| 5.1 | 在 `config.py` 添加 `StationsConfig` 模型 | Import 成功 |
| 5.2 | 在 `config.yaml` 添加 `stations` 配置节 | 配置加载成功 |
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
| DessertStrategy | 独立类 | 不同的流水线逻辑，不继承自 DefaultStrategy |
| 配置结构 | `stations` 顶级节 | 清晰分离站点特定设置 |
| 错误处理 | 记录日志 + 返回 False | 不实现重试机制，假设操作成功 |
| Action 命名 | `{Verb}{Object}Action` | 与现有约定一致 |
| 出餐方式 | 直接从灶台 | 甜点跳过组装站，直接从灶台出餐 |

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
│  MoveTo    AddCond   Stir    MoveMix   ServeFrom               │
│  MixingBowl          Bowl    ToCooker  Cooker                   │
│                                                                 │
│  状态追踪：                                                      │
│  - MixingBowlState.ingredients  (list[str])                     │
│  - MixingBowlState.condiments   (dict[str, int])                │
│  - MixingBowlState.is_stirred   (bool)                          │
│  - CookerState (复用现有)                                        │
│                                                                 │
│  决策优先级：                                                    │
│  1. ServeFromCooker    — 灶台完成 → 送餐                        │
│  2. ClearCooker        — 过期清理                               │
│  3. MoveMixingBowlToCooker — 搅拌完成 → 灶台                    │
│  4. Stir               — 食材齐全 + 调料齐全 → 搅拌             │
│  5. AddCondiment       — 食材齐全 → 调味                        │
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
| dessert_oven | (715, 615) | 甜点烤箱 |
| cooling_plate | (1260, 590) | 冷却盘 |
| 半成品库存 | (675, 860) | 半成品临时储存 |

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
- **库存**：一次只能存储一个半成品

### 13.3 状态追踪

- 使用 `MixingBowlState` 追踪搅拌盆状态
- 使用 `CookerState` 追踪 cooker 状态（复用现有）
- 使用 `StockpileSlot` 追踪库存状态（复用现有）

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
- 库存已满：记录日志，返回 False
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

### 17.2 可配置参数

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
