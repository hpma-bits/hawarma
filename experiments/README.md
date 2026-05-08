# 实验目录

## 📁 目录结构

```
experiments/
├── README.md                # 本文件
├── ARCHITECTURE.md          # 目录说明
├── parallel_strategy/       # 实验：多订单并行策略
│   ├── design.md            # 实验设计
│   ├── script.py            # 实验脚本
│   └── report.md            # 实验报告
└── [其他实验]/              # 每个实验一个子目录
```

## ⚠️ 测试规范

**必须通过策略函数运行测试，不要直接调用模拟器方法！**

### ✅ 正确方法
```python
from playground.core.episode import run_episode
from playground.env.sim import SimEnv
from playground.strategies.default import DefaultStrategy
from playground.agents.base import Agent

env = SimEnv()
agent = Agent(DefaultStrategy())
result = run_episode(env, agent, seed=42)
```

### ❌ 错误方法（会导致状态不一致）
```python
sim.serve_order(0)
sim.add_condiment('buttermilk_cream')  # 失败：assembly已清空
sim.move_to_assembly('pot')  # 失败：pot可能已空
```

**原因**：直接调用模拟器方法会跳过策略的状态检查逻辑，导致操作失败。

## 📋 实验流程

1. 创建实验目录：`mkdir experiments/[实验名称]`
2. 编写实验设计：`design.md`
3. 编写实验脚本：`script.py`（使用 `playground/` 的 CLI 或 API）
4. 执行实验：`python -m playground bench --games 50`
5. 编写实验报告：`report.md`

详见 `.opencode/skills/experiment.md`

## 🔧 可复用模块

使用 `playground/` 下的模块：
- `playground.core.runner`: `run_episode`, `run_benchmark`
- `playground.env.game_env_impl`: `SimEnv`
- `playground.strategies.default`: `DefaultStrategy`
- `playground.bench.compare`: `print_comparison`, `export_csv`

## 📊 实验历史

| 实验名称 | 状态 | 主要结论 |
|----------|------|----------|
| parallel_strategy | ✅完成 | parallel策略优于naive，提升7.6% |

## 🔗 相关文档

- 实验规范：`.opencode/skills/experiment.md`
- 策略文档：`docs/agent_strategy.md`
