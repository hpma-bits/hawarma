# 实验规范 Skill

## 概述

本skill定义了Hawarma项目中实验的标准流程和规范，确保实验的可重复性和可追溯性。

## 目录结构

```
experiments/
├── README.md                    # 实验总览
├── ARCHITECTURE.md              # 目录说明
├── [实验名称]/                  # 每个实验一个子目录
│   ├── design.md                # 实验设计
│   ├── script.py                # 实验脚本
│   └── report.md                # 实验报告
└── [另一个实验]/
    ├── design.md
    ├── script.py
    └── report.md
```

## 可复用模块

实验脚本应使用以下可复用模块：

### `scripts/benchmark_utils.py`

提供实验脚本可复用的功能：

```python
from scripts.benchmark_utils import (
    GameMetrics,      # 游戏指标数据类
    run_single_game,  # 运行单局游戏
    run_benchmark,    # 运行基准测试
    print_results,    # 打印结果
    count_active_cookers,  # 计算忙碌灶台数
    get_needed_ingredients, # 获取需要的食材
    get_stockpile_info,     # 获取库存信息
    execute_action,         # 执行动作
)
```

### `scripts/base_strategies.py`

定义标准的基准策略：

```python
from scripts.base_strategies import (
    naive_strategy,      # 按文档优先级的策略
    parallel_strategy,   # 多订单并行策略
    BASE_STRATEGIES,     # 标准策略字典
)
```

## 实验流程

### 1. 创建实验目录

```bash
mkdir experiments/[实验名称]
```

### 2. 实验设计（必须）

创建 `design.md`：

```markdown
# 实验设计：[实验名称]

## 实验目的
[明确说明要验证什么假设或对比什么策略]

## 假设
[可选] 要验证的假设

## 实验配置
- 测试局数: [建议30局以上]
- 随机种子: [起始种子] - [结束种子]
- 菜谱选择: [随机/固定]
- 策略列表: [要对比的策略]

## 预期结果
[可选] 预期的实验结果

## 时间
[实验日期]
```

### 3. 实验脚本（必须）

创建 `script.py`，使用可复用模块：

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
from scripts.benchmark_utils import run_benchmark, print_results
from scripts.base_strategies import BASE_STRATEGIES

# 如果需要新策略，在这里定义
def new_strategy(sim):
    # 策略实现
    return actions

def main():
    parser = argparse.ArgumentParser(description="实验描述")
    parser.add_argument("--seeds", type=int, default=30, help="测试局数")
    args = parser.parse_args()
    
    # 要对比的策略
    strategies = {
        "naive": BASE_STRATEGIES["naive"],
        "new": new_strategy,  # 新策略
    }
    
    # 运行基准测试
    results = run_benchmark(strategies=strategies, num_games=args.seeds)
    print_results(results)

if __name__ == "__main__":
    main()
```

### 4. 实验执行

```bash
cd experiments/[实验名称]
python script.py
```

### 5. 实验报告（必须）

创建 `report.md`：

```markdown
# 实验报告：[实验名称]

## 实验时间
[实际执行时间]

## 实验配置
[复制实验设计中的配置]

## 实验结果

| 策略 | 指标1 | 指标2 | ... |
|------|-------|-------|-----|
| 策略A | 值 | 值 | ... |
| 策略B | 值 | 值 | ... |

## 结论
[基于数据的结论]

## 分析
[为什么会有这样的结果]

## 后续工作
[可选] 基于实验结果的下一步计划
```

## 命名规范

- **实验目录**: `[实验名称]`（小写，下划线分隔）
- **设计文件**: `design.md`
- **脚本文件**: `script.py`
- **报告文件**: `report.md`

## 关键指标

标准收集的指标：
- `orders_served`: 完成订单数
- `orders_timeout`: 超时订单数
- `total_score`: 总得分
- `idle_time`: 灶台空闲时间
- `waiting_for_order_time`: 等待订单时间

## 注意事项

1. **独立性**: 每个实验独立，避免相互影响
2. **可重复性**: 使用固定随机种子，确保结果可重复
3. **多局测试**: 至少30局，减少随机波动影响
4. **数据保存**: 实验数据应保存到报告中
5. **代码保存**: 实验脚本必须保存
6. **使用可复用模块**: 避免重复代码
