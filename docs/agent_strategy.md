# Agent 核心算法与策略文档

## 1. 概述

本文档描述 Hawarma 烹饪游戏 Agent 的核心算法设计、策略分析和基准测试结果。

### 1.1 问题定义

- **目标**：在 90 秒内最大化完成订单数和得分
- **约束**：
  - 最多 4 个灶台同时烹饪
  - 食材烹饪完成后 5 秒内必须移走，否则过期
  - 订单有超时时间（普通订单 55-75 秒，Rush 订单 30-45 秒，基于配方总烹饪时长动态计算）
  - 调料必须在食材齐全后才能添加

## 2. 架构

### 2.1 三层架构

```
core/       Strategy 的唯一输入，数据契约
agent/      Strategy 纯决策单元
game/       Env 状态管理 + Runner 编排 + Operator 执行
```

- **Strategy**：`decide(state) -> Action`，纯决策函数，不接触环境
- **Env**：状态管理 + `get_unified_state()` + 统计追踪
- **Runner**：编排扫描循环、超时循环、决策循环，执行 Action

### 2.2 数据流

```
Scanner/Timeout → Env.get_unified_state() → Strategy.decide(state) → Action → Runner.execute(action) → Operator.swipe() + Env.update()
```

### 2.3 动作类型

Actions 定义在 `src/hawarma/core/actions.py`，按 station 分组：

| 类别 | Action | 说明 |
|------|--------|------|
| 基础 | AddCondimentAction | 调味 |
| 基础 | ClearCookerAction | 清理灶台 |
| Gastronome | CookAction | 食材区→灶台 |
| Gastronome | MoveToAssemblyAction | 灶台→组装站 |
| Gastronome | ServeOrderAction | 组装站→取餐台 |
| Gastronome | MoveToStockpileAction | 灶台→库存 |
| Gastronome | PullFromStockpileAction | 库存→组装站 |
| Dessert | *(预留)* | 待开发 |

## 3. 策略对比（100局基准测试）

| Rank | Strategy | Avg Reward | vs #1 | 完成订单 | 超时率 |
|------|----------|-----------|-------|---------|--------|
| 1 | **CPMEnhancedStrategy** | **3934** | — | 18.9 | 0% |
| 2 | VisibilityAwareStrategy | 3923 | Δ -11 (n.s.) | 18.8 | 0% |
| 3 | CPMStrategy | 3878 | Δ -56 | 18.5 | 0% |
| 4 | PreemptScoreStrategy | 3793 | Δ -141 (p=0.01) | 18.1 | 0% |
| 5 | DefaultStrategy | 3736 | Δ -198 (p=0.01) | 17.9 | 0% |

### 3.1 可用策略

| 注册名 | 类名 | 特点 |
|--------|------|------|
| `cpm_enhanced` | CPMEnhancedStrategy | **当前最佳**：CPM + 单食材优先 + visibility 阈值 |
| `visibility_aware` | VisibilityAwareStrategy | CPM + visibility 阈值跨越加成 |
| `cpm` | CPMStrategy | 关键路径法（SPT） + assembly 抢占 |
| `preempt_score` | PreemptScoreStrategy | 分数/CP 效率排序 + 进度感知抢占 |
| `default` | DefaultStrategy | 主动预烹饪 + 决策优先级优化，稳定保守 |

### 3.2 策略切换

```bash
# CLI
python -m playground run --strategy cpm_enhanced
python -m playground bench --strategies default,cpm,cpm_enhanced

# 代码
from hawarma.agent.registry import get_strategy
strategy = get_strategy("cpm_enhanced")
```

## 4. 核心优化总结

| 优化 | 说明 | 效果 |
|------|------|------|
| SPT 排序 | 最短处理时间优先（关键路径法） | 提升吞吐 4-5% |
| visibility 阈值 | 跨越阈值订单获得优先级加成 | Δ +38 (n.s.) |
| 单食材优先 | 1-ingredient 订单 CP 减 0.3s | Δ +11 (n.s.) |
| 调料优先 | 食材齐全时先加调料再烹饪 | 更快释放组装站 |
| 最长烹饪优先 | 同订单内先煮最慢的食材 | 最大化并行重叠 |
| 主动预烹饪 | 灶台空闲时预烹饪 | 减少空闲时间 |
| 快速存储 | 不需要的食材 2s 后存储 | 更快释放灶台 |
| 动画期间烹饪 | 送餐动画不阻塞烹饪 | +11.2%（旧基准） |

## 5. 效率指标说明

Playground 基准测试输出以下效率指标：

| 指标 | VisibilityAware | 说明 |
|------|----------------|------|
| Idle% | 60.1% | 灶台空闲时间比例 |
| Expired | 1.2 | 每局食材过期数 |
| ClrAsm | 1.4 | 清空组装站次数（抢占） |
| SrvGap | 4.5s | 两次 serve 平均间隔 |
| None% | 84.8% | 策略返回 None 的步数比 |
| StkIn/Out | 11/10 | 库存进出次数 |
| StkMax | 3.0 | 库存峰值 |

## 6. 运行基准测试

```bash
# 完整基准测试
python -m playground bench --games 100 --strategies default,cpm,cpm_enhanced

# 导出 CSV
python -m playground bench --games 100 --csv results.csv

# 单局
python -m playground run --seed 42 --strategy cpm_enhanced
```

## 7. 甜点策略

### 7.1 概述

甜点策略（DessertStrategy）是甜点模式的专用策略，采用流水线决策逻辑。与 Gastronome 策略不同，甜点策略专注于搅拌盆和灶台的协同工作。

### 7.2 甜点流程

```
食材区 → 搅拌盆 → 调味 → 搅拌 → 灶台烹饪 → 取餐台
```

### 7.3 决策优先级

甜点策略的决策优先级如下：

| 优先级 | 操作 | 条件 |
|--------|------|------|
| 1 | 送餐（灶台→取餐台） | 灶台完成 + 有匹配订单 |
| 2 | 清理过期灶台 | 灶台过期 |
| 3 | 移动搅拌盆到灶台 | 搅拌完成 + 灶台空闲 |
| 4 | 搅拌 | 食材齐全 + 调料齐全 + 未搅拌 |
| 5 | 添加调料 | 食材齐全 + 调料未齐全 |
| 6 | 添加食材到搅拌盆 | 搅拌盆未满 |
| 7 | 清理搅拌盆 | 无匹配订单 |

### 7.4 流水线决策

甜点策略采用流水线决策逻辑：

- 当当前订单在烹饪时，开始下一个订单的食材收集和搅拌
- 一般同时处理 2 个订单
- rush 订单优先处理，然后先进先出

### 7.5 资源管理

| 资源 | 约束 | 说明 |
|------|------|------|
| 搅拌盆 | 一次只能处理一个订单 | 搅拌盆是共享资源 |
| cooker | 一次只能烹饪一个甜点 | cooker 是共享资源 |
| 库存 | 一次只能存储一个半成品 | 库存是共享资源 |

### 7.6 订单优先级

甜点订单的优先级排序：

1. **rush 订单优先**：rush 订单始终最高优先级
2. **先进先出**：相同优先级的订单按到达顺序处理
3. **超时时间**：即将超时的订单优先处理

### 7.7 状态追踪

甜点策略使用隐式状态追踪：

- **MixingBowlState**：追踪搅拌盆状态（食材、调味品、是否搅拌完成）
- **CookerState**：追踪 cooker 状态（复用现有）
- **StockpileSlot**：追踪库存状态（复用现有）

### 7.8 错误处理

甜点策略的错误处理策略：

- 操作失败时记录日志
- 不实现重试机制
- 假设所有操作都成功
- 关注游戏逻辑的正确性

### 7.9 配置

甜点策略的配置在 `configs/config.yaml` 的 `stations.dessert` 节：

```yaml
stations:
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
```

### 7.10 使用方法

```bash
# CLI
python main.py --strategy dessert

# TUI
python tui.py  # 在策略选择中选择 dessert

# 代码
from hawarma.agent.registry import get_strategy
strategy = get_strategy("dessert")
```

### 7.11 未来扩展

甜点策略支持未来扩展：

- 支持更多甜点类型：只需在 `recipes.json` 中添加新的甜点菜谱
- 可配置参数：搅拌参数、位置参数、超时参数都可配置
- 架构易于扩展：策略设计支持未来添加新的决策逻辑
