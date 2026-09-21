# playground 目录架构

## 📁 目录概述

Hawarma 项目的 RL 风格游戏模拟与策略验证环境。

核心目标：将游戏模拟器重构为标准 RL 环境（Env → Agent → Strategy），使策略开发、Agent 验证和基准测试统一在同一套接口下。

## ⚠️ 重要提示

**一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**

## 📄 文件列表

### 根目录

| 文件 | 地位 | 说明 |
|------|------|------|
| `__init__.py` | 包初始化 | 版本号 `0.1.0` |
| `__main__.py` | CLI 入口 | `python -m playground` |
| `cli.py` | CLI 实现 | `run`（默认策略 gastronome）/ `bench` / `replay` 子命令 |
| `README.md` | 快速上手 | 面向用户的使用指南 |
| `ARCHITECTURE.md` | 本文件 | 面向开发者的架构文档 |
| `env_simulator.py` | 游戏状态机 | 规则"真理之源"（#14 后含 serve 校验/过期占灶/双窗口语义） |
| `env_simulator_types.py` | 模拟器类型 | Event/EventType/GameState/GameConfig（复用 hawarma.core 模型） |

### `env/` — 环境模块

| 文件 | 地位 | 输入 | 输出 |
|------|------|------|------|
| `game_env.py` | GameEnv ABC (RL interface) | Action | StepResult |
| `sim.py` | SimEnv implementation | Action | RL-style StepResult via GameSimulator |
| `reward.py` | Reward calculation | events + state | float reward |

SimEnv 观测口径（#14）：新订单在 `max(detection_delay, GameSimulator.NEW_ORDER_ANIMATION=1s)`
窗口内对 agent 不可见（规则 3.4.2 检测盲区），与 `GameSimulator.get_order` 单一口径。

SimEnv 观测隔离（#16）：`get_unified_state()` 对 orders/cookers/assembly/stockpile
做字段级深快照（各模型 `snapshot()`），无 `sim._state` 引用逃逸；与真实环境侧
`GameEnv.get_unified_state()` 的"观测不可变"语义对齐（模拟器内部 `GameState.copy()`
仍为 deepcopy，仅用于模拟器自身的回滚/分支场景）。

### `agents/` — Agent shell module

| 文件 | 地位 | 输入 | 输出 |
|------|------|------|------|
| `base.py` | Agent 基类 | UnifiedState | Action \| None（默认透传 Strategy） |

### `core/` — 游戏循环

| 文件 | 地位 | 输入 | 输出 |
|------|------|------|------|
| `episode.py` | 单局运行器 | GameEnv + Agent + seed | EpisodeResult（多策略基准在 bench/ 下） |

### `replay/` — 回放系统

| 文件 | 地位 | 输入 | 输出 |
|------|------|------|------|
| `recorder.py` | 记录与回放 | EpisodeResult | JSON 文件 / CLI 交互式回放 |

### `bench/` — 基准测试

| 文件 | 地位 | 输入 | 输出 |
|------|------|------|------|
| `bench.py` | benchmark 运行器（`run_benchmark` 唯一实现） | strategies + num_games | {name: [EpisodeResult]} |
| `compare.py` | 统计对比 | benchmark results | 打印表格 / CSV / JSON |
| `stats.py` | 纯统计函数 | 分数序列 | 配对 t 检验（真实 p 值）/ Cohen's d / 95% CI |
| `metric.py` | 效率指标收集器 | 每步 UnifiedState + StepResult | EfficiencyMetrics（含首帧空闲统计） |

### `tests/` — 测试

| 文件 | 测试内容 |
|------|----------|
| `test_interfaces.py` | Phase 0: UnifiedState, Strategy, Agent, GameEnv 接口验证 |
| `test_game_env_impl.py` | Phase 1: SimEnv 集成测试 |
| `test_end_to_end.py` | Phase 2-3: Runner + GastronomeStrategy 端到端 |
| `test_reward.py` | Reward 计算：GameDataReward (reward.csv 查表) |
| `test_runner.py` | Phase 4: run_episode + run_benchmark（bench/bench.py） |

## 🔗 模块关系与数据流

```
┌─────────────────────────────────────────────────────────────┐
│                    SimEnv (环境)                        │
│  ┌─────────────────┐      UnifiedState      ┌─────────────┐ │
│  │   GameSimulator  │  ───────────────────>  │get_unified  │ │
│  │  (内部状态机)     │                       │_state()     │ │
│  │                 │  <───────────────────  │             │ │
│  │                 │        Action          │ step(action)│ │
│  │                 │                       │ → StepResult│ │
│  └─────────────────┘                       └─────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ UnifiedState
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Agent (交互壳)                             │
│                        │                                    │
│                        │ UnifiedState                         │
│                        ▼                                    │
│                  ┌─────────────┐                            │
│                  │   Strategy  │                            │
│                  │  decide()   │                            │
│                  │   → Action  │                            │
│                  └─────────────┘                            │
│                                                             │
│  默认实现直接透传，可子类化扩展                               │
└─────────────────────────────────────────────────────────────┘
```

## 🔧 关键设计决策

### 1. Agent Shell 无 Safety Layer

所有决策（包括 `ClearAssemblyAction`）都由注入的 Strategy 处理。Agent Shell 默认只做一件事：透传 `strategy.decide(state)`。

### 2. UnifiedState 是 Strategy 的唯一输入

Strategy 不直接接触环境，不访问 `sim._state`。这保证了：
- Strategy 可在任何环境中运行（真实游戏 / 模拟器 / mock）
- Strategy 可被单元测试（mock state，不启动 Simulator）

### 3. Reward 可插拔

默认 `GameDataReward`（基于 `reward.csv` 精确查表），也可切换为 `SparseReward`（读 simulator 的 score 字段）。

### 4. 配对 Benchmark 与统计口径（Issue #15）

`run_benchmark()`（唯一实现在 `bench/bench.py`）在同一 seed 下所有策略各跑一局，
确保公平对比。

**CRN 配对局限**：同 seed 只配平初始条件，各策略的不同动作会使
其后的随机流发散——配对只降低方差，不构成严格的同随机流对照
（bench 输出中有 CRN note 提示，p 值应视为近似）。

**统计口径**：表格、配对检验与 CSV 导出统一使用 `final_score`
（v2 = 逐单 reward 之和 + 终局 visibility）。配对检验为
df = n-1 的双侧 t 检验，输出真实 p 值（`bench/stats.py` 用
`math.lgamma` + 连分式 betacf 实现正则化不完全 beta 函数，无第三方依赖）、
配对 Cohen's d 与 Δ 均值 95% CI。零方差边界按保守规则处理：
差值非零 → p 取 1e-12 下限并标注；两组完全一致 → p = 1.0。

### 5. 模拟器保真度（#14，2026-09-22）

`env_simulator.py` 对齐 `docs/game_rules.md` 第 3/4/9 节的 4 项机制：

- **serve 校验**：`serve_order` 比对组装站食材 (name, cooker_type) 集合与 recipe
  完全一致，不一致失败且菜品留在组装站（规则 3.5 "被退回"）
- **过期占灶**：过期食材留在灶台直到显式 `clear_cooker` / `move_to_trash`
  （清理动作经 SimEnv 一次 action_delay=0.3s）；INGREDIENT_EXPIRED 按过期时刻发一次
- **新单可见性**：1s 出现动画（`NEW_ORDER_ANIMATION`）独立于 serve 禁令窗口
  （`_serve_ban_until`，slot 位移 1.5s），观测路径取 `max(detection_delay, 1s)`
- **立即刷新**：提交/超时后场上无单，下一 tick 立即创建新订单（不被禁令窗口推迟）

基准口径 v2（含 #14 修复）的对照数据见 `docs/agent_strategy.md` §3.1.1。

## 📝 待办

- [ ] Phase 5: 参数扫掠 (`sweep/`)
- [ ] Phase 5: 可视化 (`sweep/visualizer.py`)
- [ ] Phase 5: 调试钩子 (`agents/debug_hooks.py`)
