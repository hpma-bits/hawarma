# Playground

Hawarma 项目的 RL 风格游戏模拟与策略验证环境。

## 快速开始

```bash
# 运行单局游戏
python -m playground run --seed 42

# 运行基准测试（50 局）
python -m playground bench --games 50

# 导出 CSV
python -m playground bench --games 100 --csv results.csv

# 回放记录的游戏
python -m playground replay replay.json
```

## 核心架构

```
GameEnvImpl  →  UnifiedState  →  Strategy.decide()  →  Action  →  GameEnvImpl.step()
     ↑                                                                            ↓
     └──────────────────── Reward + Next State ───────────────────────────────────┘
```

- **GameEnvImpl**: RL 风格环境（reset/step/get_unified_state）
- **UnifiedState**: 不可变状态快照，Strategy 的唯一输入
- **Strategy**: 纯决策函数 `decide(state) -> Action | None`
- **Agent**: 持有 Strategy 的交互壳（默认透传）

## 目录结构

| 目录 | 职责 |
|------|------|
| `env/` | GameEnv, UnifiedState, Reward, RecipeAdapter |
| `strategies/` | Strategy ABC + DefaultStrategy |
| `agents/` | Agent 壳（透传 Strategy） |
| `core/` | run_episode, run_benchmark |
| `replay/` | 回放记录与 CLI 播放器 |
| `bench/` | 统计对比（t-test）+ CSV/JSON 导出 |
| `tests/` | 53 个测试 |

## 运行测试

```bash
.venv\Scripts\activate
$env:PYTHONPATH="src;$PWD"
python -m pytest playground\tests\ -v
```

## 自定义 Strategy

```python
from playground.strategies.base import Strategy
from playground.env.unified_state import UnifiedState
from hawarma.agent.agent import Action, CookAction

class MyStrategy(Strategy):
    def decide(self, state: UnifiedState) -> Action | None:
        # 你的决策逻辑
        return CookAction(ingredient="beef", cooker="grill", duration=3.0)
```

然后在 CLI 中使用（需要扩展 cli.py 注册策略）。

## Reward 计算

默认使用 `GameDataReward`，基于 `playground/reward.csv` 中的真实游戏数据精确计算 serve 得分：
- 分数 = base_points + visibility
- Rush 订单 +60%

也可切换回 `SparseReward`（读 simulator 的 score 字段）。

## 与旧 scripts/ 的关系

Playground 替代了 `scripts/` 下的模拟/基准测试脚本：
- `scripts/simulate_full_game.py` → `python -m playground run`
- `scripts/benchmark_agent.py` → `python -m playground bench`

旧脚本保留向后兼容 shim，但新开发请使用 playground。
