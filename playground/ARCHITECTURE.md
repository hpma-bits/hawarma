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
| `cli.py` | CLI 实现 | `run` / `bench` / `replay` 子命令 |
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

### `agents/` — Agent shell module

| 文件 | 地位 | 输入 | 输出 |
|------|------|------|------|
| `base.py` | Agent 基类 | UnifiedState | Action \| None（默认透传 Strategy） |

### `core/` — 游戏循环

| 文件 | 地位 | 输入 | 输出 |
|------|------|------|------|
| `runner.py` | 运行器 | GameEnv + Agent + seed | EpisodeResult / BenchmarkResult |

### `replay/` — 回放系统

| 文件 | 地位 | 输入 | 输出 |
|------|------|------|------|
| `recorder.py` | 记录与回放 | EpisodeResult | JSON 文件 / CLI 交互式回放 |

### `bench/` — 基准测试

| 文件 | 地位 | 输入 | 输出 |
|------|------|------|------|
| `runner.py` | benchmark 运行器 | strategies + num_games | {name: [EpisodeResult]} |
| `compare.py` | 统计对比 | benchmark results | 打印表格 / CSV / JSON |

### `tests/` — 测试

| 文件 | 测试内容 |
|------|----------|
| `test_interfaces.py` | Phase 0: UnifiedState, Strategy, Agent, GameEnv 接口验证 |
| `test_game_env_impl.py` | Phase 1: SimEnv 集成测试 |
| `test_end_to_end.py` | Phase 2-3: Runner + GastronomeStrategy 端到端 |
| `test_reward.py` | Reward 计算：GameDataReward (reward.csv 查表) |
| `test_runner.py` | Phase 4: run_episode + run_benchmark |

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

### 4. 配对 Benchmark

`run_benchmark()` 在同一 seed 下所有策略各跑一局，确保公平对比。

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
