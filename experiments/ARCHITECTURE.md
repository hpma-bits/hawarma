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
- **依赖**: `scripts/benchmark_utils.py`, `scripts/base_strategies.py`

### `report.md`
- **地位**: 实验报告
- **内容**: 实验结果、结论、分析、后续工作

## 🔧 可复用模块

实验脚本应使用以下可复用模块：

### `scripts/benchmark_utils.py`
提供实验脚本可复用的功能：
- `GameMetrics`: 游戏指标数据类
- `run_single_game`: 运行单局游戏
- `run_benchmark`: 运行基准测试
- `print_results`: 打印结果

### `scripts/base_strategies.py`
定义标准的基准策略：
- `naive_strategy`: 按文档优先级的策略
- `parallel_strategy`: 多订单并行策略
- `BASE_STRATEGIES`: 标准策略字典

## 🔗 相关文档

- 实验规范：`.opencode/skills/experiment.md`
- 策略文档：`docs/agent_strategy.md`
