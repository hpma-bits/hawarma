# 架构重构设计文档

> 本文档记录 bridge / agent / strategy / playground 的架构讨论和重构方案。
> 目标：清晰的职责边界、最大化代码复用、易读命名、预留甜点平台扩展。

---

## 1. 问题诊断

### 1.1 当前架构的 5 个核心问题

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| 1 | **UnifiedState 拼装重复** | `agent.py` 和 `playground/game_env_impl.py` 各拼一份 | 维护成本翻倍，行为可能不一致 |
| 2 | **Agent Shell 职责过重** | 持有配方数据、停滞诊断、状态拼装、统计 | 与 Strategy 职责边界模糊 |
| 3 | **配方数据格式不统一** | Recipe / RecipeAdapter / dict 三种格式混用 | Strategy 充满 `hasattr` 检查 |
| 4 | **Actions 定义位置错误** | 放在 `agent.py`，但被 strategy/bridge/playground 全局引用 | agent 模块反向依赖其他所有模块 |
| 5 | **Playground Agent 与真实 Agent 职责不一致** | playground Agent 纯透传，真实 Agent 有停滞诊断 | 基准测试无法暴露停滞问题 |

### 1.2 重复代码清单

| 功能 | 真实游戏 | Playground | 重复？ |
|------|---------|------------|--------|
| UnifiedState 拼装 | `CookingAgent._build_unified_state()` | `SimEnv.get_unified_state()` | ✅ |
| 配方数据持有 | `CookingAgent._recipe_by_slug` | `Strategy.on_game_start(recipes)` | ✅ |
| 统计追踪 | `CookingAgent.stats` | `EpisodeResult` (runner) | 部分 |
| Action 执行 | `Runner._execute_action()` | `SimEnv._execute_action()` | 语义相同，实现不同 |

---

## 2. 目标架构

### 2.1 核心原则

1. **Env 是状态的唯一所有者**：`get_unified_state()` 由 env 实现，Agent 不拼装状态
2. **Strategy 是纯决策函数**：`decide(state) -> Action`，不持有环境引用
3. **Actions 是全局操作契约**：独立模块定义，env/strategy/bridge 共同依赖
4. **统一 Recipe 数据格式**：独立数据层定义，消除 `hasattr` 检查
5. **Playground 和 App 是同一个接口的两种实现**：共享 strategy + actions + state，差异仅在 env

### 2.2 目标层次图

```
┌─────────────────────────────────────────────────────────────────┐
│                    数据层 (hawarma/core/)                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Recipe (标准配方格式，含 platform 字段)                   │   │
│  │ Actions (CookAction, ServeOrderAction, ...)              │   │
│  │ UnifiedState (env → strategy 的数据契约)                 │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
           ↑                        ↑                        ↑
┌──────────┴──────────┐  ┌─────────┴─────────┐  ┌──────────┴──────────┐
│     Strategy 层     │  │      Env 层       │  │    Bridge/Runner    │
│  (纯决策，可复用)    │  │ (状态管理 + 统计)  │  │ (编排 + 动作执行)   │
│                     │  │                   │  │                     │
│  DefaultStrategy    │  │ GameEnv   │  │ Runner      │
│  CPMStrategy        │  │ SimEnv       │  │ run_episode()       │
│  ...                │  │ (模拟器版)        │  │ (playground 版)     │
└─────────────────────┘  └───────────────────┘  └─────────────────────┘
```

### 2.3 职责边界

| 层 | 职责 | 不做什么 |
|----|------|---------|
| **数据层** | 定义 Recipe、Action、UnifiedState | 不含逻辑 |
| **Strategy** | 纯决策：`decide(state) -> Action` | 不碰 env、不拼装状态、不追踪统计 |
| **Env** | 状态管理 + `get_unified_state()` + 内部统计 | 不做决策、不执行 UI |
| **Bridge/Runner** | 编排循环 + 执行 Action（调用 env 方法或 ui.swipe） | 不做决策、不持有配方数据 |

---

## 3. 框架复用设计

### 3.1 两个框架的对比

| 方面 | Playground | App (真实游戏) |
|------|-----------|---------------|
| 目的 | 快速验证策略、流程模拟 | 与真实设备交互 |
| Env 实现 | `SimEnv`（包装 `GameSimulator`） | `GameEnv`（程序逻辑追踪） |
| 时间推进 | `tick(0.1s)` 显式调用 | `time.time()` 实时流逝 |
| 动作执行 | 符号操作（`sim.start_cooking()`） | UI swipe + 状态更新 |
| 订单来源 | 模拟器随机生成 | 图像检测 |
| 编排 | `run_episode()` 循环 | `Runner` 异步循环 |

### 3.2 可复用部分

```
共享（不区分 playground/app）：
├── Strategy 实现（DefaultStrategy, CPMStrategy, ...）
├── Action 定义（CookAction, ServeOrderAction, ...）
├── Recipe 数据格式
├── UnifiedState 定义
└── 配方数据加载（data/recipes.json）

各自实现（不共享）：
├── Env（状态管理 + get_unified_state + 统计）
├── 编排逻辑（循环 + 唤醒 + 动画窗口处理）
└── 动作执行（符号操作 vs UI swipe）
```

---

## 4. 甜点平台扩展预留

### 4.1 两种平台的流程对比

| 步骤 | Gastronomy（当前） | Dessert（未来） |
|------|-------------------|----------------|
| 1 | 食材 → 灶台烹饪 | 食材 A → 搅拌盆 |
| 2 | 烹饪完成 → 组装站 | 食材 B → 搅拌盆 |
| 3 | 调味（组装站） | 调味（搅拌盆） |
| 4 | 送餐（组装站→取餐台） | 搅拌（搅拌盆内往复 swipe） |
| 5 | — | 搅拌盆 → 灶台烹饪 |
| 6 | — | 烹饪完成 → 取餐台（直接从灶台） |

### 4.2 关键差异

| 维度 | Gastronomy | Dessert |
|------|-----------|---------|
| 中间容器 | 组装站（Assembly Station） | 搅拌盆（Mixing Bowl） |
| 烹饪时机 | 食材先烹饪再组装 | 食材先组装、搅拌再烹饪 |
| 特殊操作 | 无 | 搅拌（往复 swipe） |
| 灶台→取餐台 | 不直接，必须经过组装站 | 直接（烹饪完从灶台 serve） |
| 食材数量 | 1 或 2 | 始终 2 |
| 库存支持 | 有 | 无 |
| 物理位置 | 组装站 | 搅拌盆（不同位置，类似瓶颈） |

### 4.3 Recipe 数据模型

```python
from enum import Enum

class Platform(Enum):
    GASTRONOMY = "gastronomy"
    DESSERT = "dessert"

@dataclass
class Recipe:
    slug: str
    name: str
    platform: Platform
    ingredients: list[Ingredient]
    condiments: dict[str, int]       # {condiment_name: count}

@dataclass
class Ingredient:
    name: str
    cooker: str                      # 需要使用的灶台类型
    duration: float                  # 烹饪时长（秒）
```

### 4.7 UnifiedState 扩展

```python
@dataclass(frozen=True)
class UnifiedState:
    # 现有字段
    time: float
    orders: tuple[OrderInfo | None, ...]
    cookers: dict[str, CookerState]
    assembly: AssemblyState              # Gastronomy 组装站
    stockpile: dict[str, StockpileSlot]
    recipes: dict[str, Recipe]           # 标准化 Recipe（不再用 object）
    game_duration: float
    is_in_animation_window: bool
    total_visibility: float

    # 新增字段
    mixing_bowl: MixingBowlState         # Dessert 搅拌盆
    platform: Platform                   # 当前订单的 platform（用于 Strategy 决策）

    @property
    def remaining_time(self) -> float:
        return max(0.0, self.game_duration - self.time)
```

### 4.4 Action 按 platform 分组

```python
# 基础动作（两种平台共享）
class Action: ...                        # 基类
class AddCondimentAction(Action):        # 调味（两种平台都需要）
    condiment: str
class ClearCookerAction(Action):         # 清理灶台
    cooker: str

# Gastronomy 专用
class CookAction(Action):                # 食材区 → 灶台
    ingredient: str; cooker: str; duration: float
class MoveToAssemblyAction(Action):      # 灶台 → 组装站
    cooker: str
class MoveToStockpileAction(Action):     # 灶台 → 库存
    cooker: str; slot: str
class PullFromStockpileAction(Action):   # 库存 → 组装站
    slot: str; ingredient: str
class ServeFromAssemblyAction(Action):   # 组装站 → 取餐台
    slot_idx: int
class ClearAssemblyAction(Action):       # 清空组装站

# Dessert 专用
class MoveToMixingBowlAction(Action):    # 食材区 → 搅拌盆
    ingredient: str
class StirAction(Action):                # 搅拌（往复 swipe，参数从配置读取）
    pass  # 坐标/次数/速度等参数后续从 config 读取
class MoveMixingBowlToCookerAction(Action):  # 搅拌盆 → 灶台
    cooker: str
class ServeFromCookerAction(Action):     # 灶台 → 取餐台（甜点直接从灶台出餐）
    cooker: str; slot_idx: int
class ClearMixingBowlAction(Action):     # 清空搅拌盆
```

### 4.5 状态模型扩展

组装站和搅拌盆是**不同的物理位置**，需要独立的状态追踪：

```python
@dataclass
class MixingBowlState:
    """搅拌盆状态（甜点专用，有配方校验）"""
    ingredients: list[str] = field(default_factory=list)
    condiments: dict[str, int] = field(default_factory=dict)
    target_recipe_slug: str | None = None   # 校验用：只接受属于该 recipe 的食材
    is_stirred: bool = False                 # 是否已完成搅拌

    @property
    def is_empty(self) -> bool:
        return len(self.ingredients) == 0

    @property
    def is_ready_to_cook(self) -> bool:
        """食材齐全 + 已调味 + 已搅拌"""
        ...
```

### 4.6 Env 扩展

```python
class Env(ABC):
    # ── 现有方法（Gastronomy） ──
    @abstractmethod
    def start_cooking(self, ingredient: str, cooker: str, duration: float) -> bool: ...
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
    def clear_cooker(self, cooker: str) -> bool: ...
    @abstractmethod
    def clear_assembly(self) -> bool: ...

    # ── 新增方法（Dessert） ──
    @abstractmethod
    def add_to_mixing_bowl(self, ingredient: str) -> bool:
        """食材 → 搅拌盆"""
    @abstractmethod
    def stir_mixing_bowl(self) -> bool:
        """搅拌操作（具体 swipe 参数从配置读取）"""
    @abstractmethod
    def move_mixing_bowl_to_cooker(self, cooker: str) -> bool:
        """搅拌盆 → 灶台（搅拌完成后送入灶台烹饪）"""
    @abstractmethod
    def serve_from_cooker(self, cooker: str, slot_idx: int) -> bool:
        """灶台 → 取餐台（甜点：烹饪完成后直接从灶台出餐）"""
    @abstractmethod
    def clear_mixing_bowl(self) -> bool:
        """清空搅拌盆"""

    # ── 统一接口 ──
    @abstractmethod
    def get_unified_state(self) -> 'UnifiedState': ...
    @abstractmethod
    def get_stats(self) -> dict: ...
```

---

## 5. 命名问题诊断

### 5.1 当前命名不清晰的变量/类

| 当前命名 | 问题 | 建议 |
|---------|------|------|
| `CookingAgent` | "Cooking" 误导，它不做烹饪决策 | `AgentShell` 或直接移除 |
| `_build_unified_state()` | "build" 暗示 Agent 在构造 | 移到 env，改为 `get_unified_state()` |
| `_recipe_by_slug` | 在 agent 和 strategy 中各有一份 | 统一为 `RecipeStore` 或由 env 持有 |
| `ingredients_cookers` | 混合了两种信息 | 拆分为 `ingredients: list[Ingredient]` |
| `target_recipe_slug` | 只存 slug，需要额外查找 Recipe | 直接存 `Recipe` 引用 |
| `assembly.is_free` | 语义模糊（是"空闲"还是"可用"） | `is_empty` 更准确 |
| `step_with_diagnostics()` | Agent Shell 的核心方法名太长 | 移除或改为 `tick()` |
| `step()` (agent) vs `step()` (env) | 同名不同义 | agent 改为 `decide()`，env 保持 `step()` |

### 5.2 目录结构命名建议

```
当前：                          建议：
src/hawarma/                →  保持
  agent/                    →  保持（Strategy 在此）
  bridge/                   →  rename: runtime/ 或 executor/
  env_simulator.py          →  merge into playground/
  env_simulator_types.py    →  merge into playground/
playground/                 →  保持
  env/                      →  保持
  strategies/               →  移到 src/hawarma/agent/strategies/（已完成）
```

---

## 6. 已确认决策

| # | 问题 | 决策 |
|---|------|------|
| Q9 | 甜点流程细节 | ✅ 食材→组装站→调味→灶台烹饪→取餐台，始终双食材，无库存 |
| Q10 | 统计由谁追踪 | ✅ Env 内部追踪 |
| Q11 | Actions 结构 | ✅ 按 platform 分组，共享基础动作 + 平台专用动作 |
| Q12 | platform 字段类型 | ✅ Enum 枚举（`Platform.GASTRONOMY` / `Platform.DESSERT`） |
| Q13 | Env 扩展 | ✅ 新增 `move_assembly_to_cooker` + `serve_from_cooker` + `get_unified_state` + `get_stats` |
| Q14 | 重构顺序 | ✅ Phase 1 → 2 → 3 |

---

## 7. 开发方案

### Phase 1：提取数据层（无破坏性变更）

**目标**：将 Actions、Recipe、UnifiedState 提取到独立模块，消除循环依赖。

| 步骤 | 变更 | 影响文件 |
|------|------|---------|
| 1.1 | 创建 `src/hawarma/core/` 目录 | 新目录 |
| 1.2 | 创建 `src/hawarma/core/actions.py`，从 `agent.py` 迁移所有 Action 定义 | `agent.py`, 新文件 |
| 1.3 | 创建 `src/hawarma/core/recipe.py`，定义 `Platform` Enum + `Recipe` + `Ingredient` dataclass | 新文件 |
| 1.4 | 创建 `src/hawarma/core/state.py`，从 `agent/unified_state.py` 迁移 `UnifiedState` | `agent/unified_state.py`, 新文件 |
| 1.5 | 创建 `src/hawarma/core/__init__.py`，导出所有类型 | 新文件 |
| 1.6 | 更新所有 import：agent/strategy/bridge/playground 改为从 `core` 导入 | 全局 |

**验证**：`python -m pytest playground/tests/` 全部通过。

### Phase 2：统一 Env 接口 + 移除 Agent Shell

**目标**：Env 持有 `get_unified_state()` 和统计，移除 Agent Shell。

| 步骤 | 变更 | 影响文件 |
|------|------|---------|
| 2.1 | `Env` 添加 `get_unified_state()` 和 `get_stats()` 抽象方法 | `base_environment.py` |
| 2.2 | `GameEnv` 实现 `get_unified_state()` 和 `get_stats()`，从 `CookingAgent._build_unified_state()` 迁移逻辑 | `environment.py` |
| 2.3 | `SimEnv`（playground）实现 `get_unified_state()`（已有）和 `get_stats()`（从 `EpisodeResult` 迁移） | `game_env_impl.py` |
| 2.4 | 更新 `Strategy.on_game_start()` 接收标准化 `Recipe` dict（而非混合格式） | `strategy.py`, 所有 Strategy 实现 |
| 2.5 | Bridge 的 `_agent_loop` 改为直接调用 `strategy.decide(env.get_unified_state())` | `bridge.py` |
| 2.6 | 移除 `CookingAgent`，Bridge 直接持有 Strategy + Env | `bridge.py`, `agent.py` |
| 2.7 | Playground 的 `Agent` 简化为纯透传壳（或直接由 `run_episode` 调用 Strategy） | `playground/agents/base.py` |

**验证**：`python -m playground bench --games 50 --strategies cpm_enhanced` 结果与 Phase 1 一致。

### Phase 3：甜点平台扩展

**目标**：在不破坏现有 gastronomy 流程的前提下，预留甜点平台接口。

| 步骤 | 变更 | 影响文件 |
|------|------|---------|
| 3.1 | `Env` 添加甜点方法（`add_to_mixing_bowl`, `stir_mixing_bowl`, `move_mixing_bowl_to_cooker`, `serve_from_cooker`, `clear_mixing_bowl`） | `base_environment.py` |
| 3.2 | `GameEnv` 实现甜点方法（gastronomy 版本 raise `NotImplementedError`） | `environment.py` |
| 3.3 | `SimEnv` 实现甜点方法（调用 `GameSimulator` 对应操作） | `game_env_impl.py` |
| 3.4 | `core/actions.py` 添加甜点动作（`MoveToMixingBowlAction`, `StirAction`, `MoveMixingBowlToCookerAction`, `ServeFromCookerAction`, `ClearMixingBowlAction`） | `core/actions.py` |
| 3.5 | `base_environment.py` 添加 `MixingBowlState` 数据结构 | `base_environment.py` |
| 3.6 | `core/state.py` 的 `UnifiedState` 添加 `mixing_bowl` 和 `platform` 字段 | `core/state.py` |
| 3.7 | `data/recipes.json` 中添加 `platform` 字段（现有配方标记为 `gastronomy`，甜点标记为 `dessert`） | `data/recipes.json` |
| 3.8 | Recipe 加载逻辑适配 `Platform` Enum | `recipe_manager.py` |
| 3.9 | 搅拌操作参数预留配置入口（`configs/config.yaml` 添加 `dessert.stir_*` 字段） | `configs/config.yaml` |

**验证**：`python -m playground bench --games 50 --strategies default` 结果不变。

---

## 8. 文件变更清单

### 新增文件

| 文件 | 内容 |
|------|------|
| `src/hawarma/core/__init__.py` | 导出 Action, Recipe, UnifiedState |
| `src/hawarma/core/actions.py` | 所有 Action 定义（按 platform 分组） |
| `src/hawarma/core/recipe.py` | Platform Enum, Recipe, Ingredient |
| `src/hawarma/core/state.py` | UnifiedState（从 agent/unified_state.py 迁移） |

### 修改文件

| 文件 | 变更 |
|------|------|
| `src/hawarma/agent/agent.py` | Phase 2 后移除或大幅简化 |
| `src/hawarma/agent/unified_state.py` | 改为从 `core.state` re-export |
| `src/hawarma/agent/strategy.py` | `on_game_start` 接收标准化 Recipe dict |
| `src/hawarma/agent/strategies/*.py` | 更新 import，移除 `hasattr` 检查 |
| `src/hawarma/bridge/base_environment.py` | 添加 `MixingBowlState` + 新抽象方法 |
| `src/hawarma/bridge/environment.py` | 实现 `get_unified_state()`, `get_stats()`, 甜点方法 |
| `src/hawarma/bridge/bridge.py` | 直接调用 strategy，移除 agent 依赖 |
| `playground/env/game_env_impl.py` | 统一 import 路径，实现甜点方法 |
| `playground/agents/base.py` | 简化或移除 |
| `data/recipes.json` | 添加 `platform` 字段 |
| `configs/config.yaml` | 添加 `dessert.stir_*` 配置项（预留） |

### 删除文件（Phase 2 完成后）

| 文件 | 原因 |
|------|------|
| `src/hawarma/env_simulator.py` | 模拟器逻辑已下沉到 playground |
| `src/hawarma/env_simulator_types.py` | 同上 |
| `playground/strategies/*.py` | 兼容层，已迁移到 agent/strategies |

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Phase 1 的 import 变更影响全局 | 所有文件需要更新 import | 用 IDE 全局替换 + 测试覆盖 |
| Phase 2 移除 Agent Shell 可能破坏停滞诊断 | 停滞诊断暂时丢失 | 停滞诊断已确认可插件化，Phase 2 后通过 Strategy 或 Bridge 的日志扩展恢复 |
| Phase 3 的新方法在 gastronomy 中无意义 | `move_assembly_to_cooker` 在 gastronomy 中 raise NotImplementedError | gastronomy 的 Strategy 不会产出 `MoveToCookerAction`，运行时安全 |
| `data/recipes.json` 添加 platform 字段 | 现有代码需要兼容 | 加载时默认 `platform="gastronomy"` |

---

## 10. 已确认决策

| # | 问题 | 决策 |
|---|------|------|
| Q9 | 甜点流程细节 | ✅ 食材→搅拌盆→调味→搅拌→灶台烹饪→取餐台，始终双食材，无库存 |
| Q10 | 统计由谁追踪 | ✅ Env 内部追踪 |
| Q11 | Actions 结构 | ✅ 按 platform 分组，共享基础动作 + 平台专用动作 |
| Q12 | platform 字段类型 | ✅ Enum 枚举（`Platform.GASTRONOMY` / `Platform.DESSERT`） |
| Q13 | Env 扩展 | ✅ 新增甜点方法 + `get_unified_state` + `get_stats` |
| Q14 | 重构顺序 | ✅ Phase 1 → 2 → 3 |
| C1 | 甜点配方数据 | ✅ 已存在 |
| C2 | SimulatorEnvironment | ✅ 不需要保留 |
| C3 | _get_recipe_attr 可移除 | ✅ 统一数据层后移除 |
| C4 | 搅拌盆 vs 组装站 | ✅ 不同物理位置，类似瓶颈，独立状态追踪 |
| C5 | 搅拌参数 | ✅ 从配置读取，后续实际游戏测试确定 |
| C6 | 每局 platform | ✅ 每局开始前确定，不混合 |
| C7 | 甜点超时/计分 | ✅ 计分看 reward.csv，超时后续补充（甜点订单持续时间长，基本不会过期） |
| C8 | 搅拌盆配方校验 | ✅ 有校验，只接受属于同一 recipe 的食材（类似组装站） |
| C9 | condiments 格式 | ✅ 格式一致，无需特殊处理 |