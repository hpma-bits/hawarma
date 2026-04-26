# experiments 目录架构

## 📁 目录结构

```
experiments/
├── README.md                # 实验总览
├── ARCHITECTURE.md          # 本文件
├── [实验名称]/              # 每个实验一个子目录
│   ├── design.md            # 实验设计
│   ├── script.py            # 实验脚本
│   └── report.md            # 实验报告
└── [另一个实验]/
    ├── design.md
    ├── script.py
    └── report.md
```

## ⚠️ 重要提示

**一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**

## 📄 文件说明

### `design.md`
- **地位**: 实验设计
- **内容**: 实验目的、假设、配置、预期结果

### `script.py`
- **地位**: 实验脚本
- **内容**: 实验配置、策略实现、数据收集、结果输出
- **依赖**: `playground/` 环境、策略模块

### `report.md`
- **地位**: 实验报告
- **内容**: 实验结果、结论、分析、后续工作

## 🔧 可复用模块

实验脚本应使用以下可复用模块：

### `playground/` 模块
提供实验脚本可复用的功能：
- `playground.core.runner`: `run_episode`, `run_benchmark`
- `playground.env.game_env_impl`: `GameEnvImpl`
- `playground.strategies`: 策略基类和实现
- `playground.bench.compare`: 结果对比和导出

## 🔗 相关文档

- 实验规范：`.opencode/skills/experiment.md`
- 策略文档：`docs/agent_strategy.md`
