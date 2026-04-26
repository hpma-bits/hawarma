# Playground 建设计划

> **状态**: 草案，待审阅  
> **目的**: 将游戏模拟器重构为标准的 RL 风格环境，使策略开发、Agent 验证和基准测试统一在 `Env → Agent → Strategy` 的框架下。

---

## 1. 背景与问题

当前代码中，**Agent 与 Strategy 是两个平行宇宙**，无法互通：

| 维度 | `CookingAgent` (`src/hawarma/agent/`) | `scripts/` 中的策略 |
|------|--------------------------------------|-------------------|
| **状态来源** | `BaseEnvironment.orders/cookers/assembly/stockpile` | 直接访问 `sim._state` 内部属性 |
| **动作表示** | `Action` 子类（`CookAction`, `ServeOrderAction`...） | 元组 `('cook', 'beef', 'grill')` |
| **环境交互** | 通过 `BaseEnvironment` 方法（`start_cooking`, `serve_order`...） | 直接调用 `sim.start_cooking()` |
| **职责范围** | 决策逻辑 + 环境交互 + 错误处理 + 停滞检测 | 仅有决策逻辑 |
| **可替换性** | 决策逻辑硬编码在 `step()` 中，无法注入外部策略 | 无法被 Agent 使用 |

**核心痛点**：
1. **Agent 集成困难**：`simulate_full_game.py` 和 `benchmark_agent.py` 几乎是两套独立代码，Agent验证和策略sandbox之间没有桥梁。
2. **调试困难**：Agent在模拟中做出错误决策时，无法回放、无法单步检查状态。
3. **策略对比缺乏统计严谨性**：现有benchmark只输出平均值，无方差、无显著性检验。
4. **参数调优全靠手工**：修改策略参数需要手动改代码、重新跑benchmark，无自动化sweep能力。

---

## 2. 目标

将模拟器彻底重构为 **RL 风格** 的游戏引擎：

1. **GameEnv 是标准的 RL 环境**：`reset()` → `step(action)` → `(obs, reward, done, info)`
2. **Strategy 是纯策略 π(s) → a**：接收 `UnifiedState`，返回 `Action`，无环境引用，无内部状态（除非需要记忆）
3. **Agent 是 Strategy 的容器 + Safety Layer**：持有 Strategy，接收 State，输出 Action，处理停滞/错误恢复
4. **Playground 是策略的试验场**：Sandbox、Validator、Replay、Benchmark、Sweep 全部基于同一套 `Env-Agent-Strategy` 接口

---

## 3. 核心架构：Env → Agent → Strategy

```
┌─────────────────────────────────────────────────────────────────────┐
│                         GameEnv (环境)                               │
│  ┌─────────────────┐      UnifiedState      ┌─────────────────────┐ │
│  │   内部状态机     │  ───────────────────>  │   get_unified_state │ │
│  │ (orders,cookers,│                       │   (observation)     │ │
│  │  assembly,...)  │  <───────────────────  │                     │ │
│  │                 │        Action          │   step(action)      │ │
│  └─────────────────┘                        │   → (obs,r,done,info)│ │
│                                             └─────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │ UnifiedState
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Agent (交互壳)                               │
│  ┌─────────────────┐      UnifiedState      ┌─────────────────────┐ │
│  │  Safety Layer   │  <───────────────────  │   act(state)        │ │
│  │ (停滞检测/容错)  │                       │                     │ │
│  │                 │  ───────────────────>  │   → Action          │ │
│  └─────────────────┘                        └─────────────────────┘ │
│                              │
│                              │ UnifiedState
│                              ▼
│                        ┌─────────────────┐
│                        │   Strategy      │
│                        │  (决策脑/策略)   │
│                        │  decide(state)  │
│                        │   → Action      │
│                        └─────────────────┘
│
│  内部记忆（可选）：
│  - _consecutive_none: int          # 连续无动作计数（停滞检测）
│  - _assembly_stale_since: float    # assembly 停滞计时
│  - _last_action_time: float        # 上次动作时间
└─────────────────────────────────────────────────────────────────────┘
```

### 3.1 为什么 Agent 和 Strategy 分离？

| 组件 | 类比 | 职责 | 状态 |
|------|------|------|------|
| **GameEnv** | OpenAI Gym Env | 维护真实状态、执行动作、计算 reward、判断 done | 有内部状态（时间、订单、灶台...） |
| **Strategy** | Policy π(a\|s) | 纯决策：给定 State，返回 Action | **无状态**（或仅策略参数） |
| **Agent** | RL Agent Wrapper | 持有 Strategy、执行 safety checks、维护运行时记忆 | 有内部记忆（停滞计数器等） |

**关键原则**：
- **Strategy 不可直接访问 Env**。它只能通过 `UnifiedState` 感知环境。
- **Strategy 不可修改自身参数以外的状态**。它是纯函数（或接近纯函数）。
- **Agent 是 Strategy 和 Env 之间的唯一桥梁**。

---

## 4. 接口定义

### 4.1 GameEnv（环境）

```python
class GameEnv:
    """
    RL 风格的游戏环境。
    职责：维护状态机、构造 Observation、执行 Action、计算 Reward、判断 Done。
    """

    def reset(
        self,
        seed: int | None = None,
        recipe_slugs: list[str] | None = None,
        game_duration: float | None = None,
    ) -> tuple[UnifiedState, dict]:
        """
        重置环境，开始新一局游戏。

        Returns:
            observation: 初始 UnifiedState
            info: 额外信息（如选中的 recipe_slugs）
        """

    def step(self, action: Action) -> tuple[UnifiedState, float, bool, bool, dict]:
        """
        执行一个动作，推进环境。

        Args:
            action: 要执行的动作

        Returns:
            observation: 执行动作后的 UnifiedState
            reward: 该步获得的奖励（如 serve 的分数）
            terminated: 是否自然结束（游戏时间到）
            truncated: 是否被截断（如手动停止）
            info: 额外信息（events, error_message 等）
        """

    def get_unified_state(self) -> UnifiedState:
        """获取当前观测状态（不推进时间）"""
```

**与现有 `GameSimulator` 的区别**：
- `GameSimulator` 需要外部调用 `tick(dt)` 推进时间，动作执行和时间推进是分离的。
- `GameEnv.step(action)` 是**原子操作**：执行动作 + 推进时间到下一个决策点（或固定 tick）。
- 这更符合 RL 范式，也简化了 Strategy 的决策逻辑（Strategy 不需要关心 `tick`）。

**时间推进策略（二选一，待确认）**：

| 方案 | 说明 | 优点 | 缺点 |
|------|------|------|------|
| A. 固定 Tick | `step()` 内部固定推进 0.1s，返回期间发生的事件 | 简单、与现有 Simulator 一致 | Strategy 需要在每个 tick 都决策，即使无事可做 |
| B. 事件驱动 | `step()` 推进到「下一个需要决策的时间点」（如烹饪完成、订单刷新、动画结束） | Strategy 只在关键时刻决策，效率高 | 实现复杂，需要预测下一个事件时间 |

**建议**：先实现 **方案 A（固定 Tick）**，与现有代码兼容。未来可扩展方案 B。

### 4.2 UnifiedState（观测）

```python
@dataclass(frozen=True)
class UnifiedState:
    """
    环境对 Agent/Strategy 暴露的统一观测。
    frozen=True 确保 Strategy 不会意外修改状态。
    """
    time: float
    orders: tuple[OrderInfo | None, ...]      # 4个槽位
    cookers: dict[str, CookerState]
    assembly: AssemblyState
    stockpile: dict[str, StockpileSlot]
    recipes: dict[str, RecipeAdapter]         # 当前局可用配方
    game_duration: float
    is_in_animation_window: bool              # 是否处于动画期间
```

### 4.3 Strategy（策略 / 决策脑）

```python
class Strategy(ABC):
    """
    策略抽象基类。
    纯决策单元：接收 UnifiedState，返回 Action。
    不直接接触环境，不处理动画等待，不处理错误恢复。
    """

    @abstractmethod
    def decide(self, state: UnifiedState) -> Action | None:
        """给定当前状态，返回下一个动作。"""

    def on_game_start(self, recipes: dict[str, RecipeAdapter]) -> None:
        """可选：游戏开始时调用（用于预计算、初始化缓存）"""
        pass
```

**已有的 Strategy 实现**：
- `DefaultStrategy`：从当前 `CookingAgent.step()` 提取的默认多订单并行策略。
- `NaiveStrategy`：文档优先级策略。
- `ParallelStrategy`：多订单并行策略（带 stockpile 优化）。
- `SmartPrecookStrategy`：智能预烹饪策略。

### 4.4 Agent（交互壳）

```python
class Agent:
    """
    Agent 交互壳。
    持有 Strategy，接收 UnifiedState，输出 Action。
    负责 Safety Layer：停滞检测、错误恢复、内部记忆维护。
    """

    def __init__(self, strategy: Strategy):
        self.strategy = strategy
        self._consecutive_none = 0
        self._assembly_stale_since: float | None = None
        self._last_action_time = 0.0

    def act(self, state: UnifiedState) -> Action | None:
        """
        接收状态，输出动作。
        流程：
        1. 调用 strategy.decide(state) 获取候选动作
        2. Safety Layer 检查（停滞检测、强制清理等）
        3. 更新内部记忆
        4. 返回最终动作
        """

    def observe(self, state: UnifiedState, reward: float, terminated: bool, info: dict) -> None:
        """
        可选：观察执行结果（用于未来 RL 训练、在线学习）。
        当前 rule-based strategy 不需要实现。
        """
        pass

    def reset(self) -> None:
        """重置内部记忆（新一局游戏开始时调用）"""
        self._consecutive_none = 0
        self._assembly_stale_since = None
        self._last_action_time = 0.0
```

**Safety Layer 职责**（与 Strategy 无关，所有 Strategy 共享）：
- 停滞检测：连续 N 步无动作 → 强制清空 assembly
- Assembly 超时清理：assembly 长时间不匹配任何订单 → 强制清空
- 动作合法性校验：Strategy 返回了在当前状态下非法的 Action → 过滤或替换

---

## 5. 游戏循环

```python
def run_episode(env: GameEnv, agent: Agent, seed: int) -> EpisodeResult:
    obs, info = env.reset(seed=seed)
    agent.reset()
    agent.strategy.on_game_start(info["recipes"])

    total_reward = 0.0
    steps = 0
    history: list[tuple[float, UnifiedState, Action | None]] = []

    while True:
        action = agent.act(obs)
        history.append((obs.time, obs, action))

        next_obs, reward, terminated, truncated, info = env.step(action)
        agent.observe(next_obs, reward, terminated, info)

        total_reward += reward
        steps += 1
        obs = next_obs

        if terminated or truncated:
            break

    return EpisodeResult(
        total_reward=total_reward,
        steps=steps,
        history=history,
        final_state=obs,
    )
```

**关键设计点**：
- `action` 可以为 `None`（Strategy 认为当前无动作可做）。Env 的 `step(None)` 等价于「等待一个 tick」。
- `reward` 设计：当前建议「仅 serve 时给予分数作为 reward」，其他动作 reward=0。这保持了与游戏评分的一致性。未来可以探索 shaped reward。
- `history` 同时记录了 State 和 Action，天然支持 Replay。

---

## 6. 目录结构

```
playground/
├── ARCHITECTURE.md              # Playground 架构设计文档
├── README.md                    # 快速上手指南
├── __init__.py
│
├── env/                         # RL 风格游戏环境（从 GameSimulator 重构）
│   ├── __init__.py
│   ├── game_env.py              # GameEnv 主类（reset, step, get_unified_state）
│   ├── unified_state.py         # UnifiedState 数据类
│   └── rewards.py               # Reward 计算逻辑（可扩展 shaped reward）
│
├── strategies/                  # 策略库（决策脑）
│   ├── __init__.py
│   ├── base.py                  # Strategy ABC
│   ├── default.py               # 从 CookingAgent 提取的默认策略
│   ├── naive.py                 # 文档优先级策略
│   ├── parallel.py              # 多订单并行策略
│   └── registry.py              # register_strategy, list_strategies()
│
├── agents/                      # Agent 壳 + Safety Layer
│   ├── __init__.py
│   ├── base.py                  # Agent 基类
│   └── safety.py                # Safety Layer 实现（停滞检测等）
│
├── core/                        # 游戏循环和基础设施
│   ├── __init__.py
│   ├── runner.py                # run_episode, run_benchmark
│   ├── replay.py                # EpisodeResult 记录和回放
│   └── metrics.py               # 丰富的指标收集
│
├── bench/                       # 基准测试与统计对比
│   ├── __init__.py
│   ├── compare.py               # 配对 t-test / Wilcoxon
│   └── reporter.py              # CLI 表格、CSV/JSON/Markdown 导出
│
├── sweep/                       # 参数扫掠自动化
│   ├── __init__.py
│   ├── grid.py                  # 网格搜索
│   ├── random_search.py         # 随机搜索
│   └── visualizer.py            # matplotlib 可视化
│
└── cli.py                       # 统一入口: python -m playground ...
```

---

## 7. CLI 设计

```bash
# 运行单局（指定 Strategy）
python -m playground run --strategy default --seed 42 --record replay.json

# 运行单局（指定 Agent，使用默认 Strategy）
python -m playground run --agent default --seed 42 --record replay.json

# 回放
python -m playground replay replay.json --step

# 基准测试（多 Strategy 对比）
python -m playground bench --strategies default,naive,parallel --games 100 --csv results.csv

# 参数扫掠
python -m playground sweep --strategy parallel --config sweep.py --games 30
```

---

## 8. 实施阶段与验证拆分

### Phase 0: 接口冻结 ✅ 已完成

1. **定义 `UnifiedState`**：`playground/env/unified_state.py`
2. **定义 `Action` 空间**：复用 `src/hawarma/agent/agent.py` 中的 `Action` 子类
3. **定义 `Strategy` ABC**：`playground/strategies/base.py`
4. **定义 `GameEnv` 接口**：`playground/env/game_env.py`（仅接口，空实现）
5. **定义 `Agent` 基类**：`playground/agents/base.py`

**验收标准**：
- 能写出一个 mock `GameEnv` 和一个 `NaiveStrategy`，`run_episode()` 能跑通（不报错）。
- 所有接口通过 `mypy` 类型检查。

### Phase 1: GameEnv 实现 + 旧 Simulator 迁移 ✅ 已完成

1. **实现 `GameEnv`**：基于 `GameSimulator` 重构，实现 `reset()` / `step()` / `get_unified_state()`
2. **Reward 设计**：当前为 sparse reward（仅 serve 给分），`rewards.py` 预留 shaped reward 接口
3. **时间推进**：先实现固定 Tick（0.1s），`step(action)` 内部执行动作 + `tick(0.1)`
4. **迁移旧测试**：`tests/test_env_simulator.py` 改为测试 `GameEnv`

**验收标准**：
- `run_episode(env, agent, seed=42)` 能完整跑完一局 90s 游戏
- `env.step(action)` 返回的 `UnifiedState` 与手动检查 `sim._state` 一致
- 旧测试全部通过（或等价迁移到新测试）

### Phase 2: Strategy 提取与重写 ✅ 已完成

1. **从 `CookingAgent` 提取 `DefaultStrategy`**：
   - 将 `step()` 中「决策逻辑」提取到 `DefaultStrategy.decide()`
   - `CookingAgent` 改造为 `Agent` 子类，注入 `DefaultStrategy`
2. **重写旧策略为 Strategy 类**：`NaiveStrategy`, `ParallelStrategy`
3. **Strategy 单元测试**：每个 Strategy 都有 mock state 测试（不启动 Simulator）

**验收标准**：
- `DefaultStrategy.decide(mock_state)` 的输出与改造前 `CookingAgent.step()` 的输出一致
- `NaiveStrategy` 在 100 局 benchmark 中的平均分与旧 `naive_strategy` 一致（±2%）
- `tests/test_agent_proactive_cooking.py` 等现有 Agent 测试通过

### Phase 3: Agent Shell ✅ 已完成（Safety Layer 已移除，clear_assembly 由 Strategy 处理）

1. **实现 `Agent` 基类**：`act()`, `observe()`, `reset()`
2. **实现 `SafetyLayer`**：停滞检测、assembly 超时清理
3. **集成到 `run_episode()`**

**验收标准**：
- `Agent(DefaultStrategy)` 与 `StrategyPlayer(DefaultStrategy)` 的 benchmark 分数差异 < 5%（Safety Layer 开销）
- Safety Layer 能在模拟的停滞场景中正确触发恢复动作

### Phase 4: Playground 基础设施 ✅ 已完成

1. **实现 `core/runner.py`**：`run_episode()`, `run_benchmark()`
2. **实现 `core/replay.py`**：`EpisodeResult` 记录和回放
3. **实现 `bench/compare.py`**：统计对比
4. **实现 `cli.py`**：基础命令

**验收标准**：
- `python -m playground run --strategy naive --seed 42` 输出与旧 `benchmark_agent.py` 一致
- `python -m playground bench --strategies naive,parallel --games 100` 输出带 p-value 的对比表

### Phase 5: 高级功能 📝 待办

1. **参数扫掠**：`sweep/grid.py`, `sweep/random_search.py`
2. **可视化**：`sweep/visualizer.py`
3. **调试钩子**：`agents/debug_hooks.py`

**状态**：Phase 0-4 已完成，Phase 5 暂缓。当前 playground 已具备核心功能。

---

## 9. Reward 设计（关键决策）

| 方案 | 说明 | 优点 | 缺点 |
|------|------|------|------|
| **Sparse（当前建议）** | 只有 serve 成功时 reward = score，其他动作 reward = 0 | 与游戏真实得分一致，易于验证 | 信用分配困难，不利于 RL 训练 |
| **Shaped（未来扩展）** | 烹饪完成 +1，移动食材 +1，serve +score，超时 -10 | 更密集的奖励信号，利于 RL | 需要精心设计，容易引入偏差 |

**当前决定**：先实现 **Sparse Reward**。`rewards.py` 设计成可插拔的，未来可以无缝切换为 Shaped Reward。

```python
# playground/env/rewards.py
class RewardFunction(ABC):
    @abstractmethod
    def compute(self, prev_state: UnifiedState, action: Action, next_state: UnifiedState, events: list[Event]) -> float:
        ...

class SparseReward(RewardFunction):
    """仅 serve 给分"""
    def compute(self, prev_state, action, next_state, events):
        for event in events:
            if event.event_type == EventType.ORDER_SERVED:
                return event.details.get("score", 0)
        return 0.0
```

---

## 10. 待确认事项

| 事项 | 选项 | 当前倾向 | 需要确认 |
|------|------|---------|---------|
| **时间推进** | A. 固定 Tick (0.1s) / B. 事件驱动 | **A** | 是否同意先固定 Tick？ |
| **Reward** | Sparse / Shaped / 可插拔 | **Sparse + 可插拔** | 是否接受？ |
| **旧 Simulator** | 完全删除 / 保留为 shim / 重构为 GameEnv | **重构为 GameEnv** | 是否接受重写 `GameSimulator`？ |
| **Action None** | step(None) 等待 / 不允许 None | **step(None) 等待** | Strategy 返回 None 时如何处理？ |
| **旧脚本过渡** | 保留 shim 1-2 周 / 直接删除 | **保留 shim** | 是否同意？ |
| **可视化库** | matplotlib / 纯 CSV | **matplotlib** | 是否接受？ |
| **统计显著性局数** | 30 / 50 / 100 | **50** | 每策略默认多少局？ |

---

## 11. 相关文档更新清单

- [x] `docs/ARCHITECTURE.md` — 新增 `playground_plan.md` 条目
- [ ] `AGENTS.md` — 更新「常用命令」和「快速导航」
- [ ] `playground/ARCHITECTURE.md` — 新建，描述模块关系和数据流
- [ ] `playground/README.md` — 新建，快速上手指南
- [ ] `experiments/ARCHITECTURE.md` — 更新实验规范，引用 playground
- [ ] `src/hawarma/agent/ARCHITECTURE.md` — 更新 Agent-Strategy 关系
