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

## 3. 策略

每个 station 只有一个策略（合并后无变体）：

| 注册名 | 类名 | Station | 特点 |
|--------|------|---------|------|
| `gastronome` | `GastronomeStrategy` | 美食站 | 10 级贪心瀑布 + CPM + visibility 阈值跨越 + 单食材优先 + 延迟感知 |
| `dessert` | `DessertStrategy` | 甜点站 | 搅拌盆流水线决策 |

### 3.1 性能基准

`GastronomeStrategy` 是 6 个历史变体（`GreedyCascade` / `CPMCascade` / `VisibilityAwareCascade` / `CPMEnhancedCascade` / `PreemptScoreCascade` / `DelayAwareCascade`）的最优特性合并结果。合并前 100 局配对 benchmark（vs `GreedyCascadeStrategy` 基线 3736）：

| 变体 | Avg Reward | vs baseline | 合并状态 |
|------|-----------|------------|----------|
| `CPMEnhancedCascadeStrategy` | 3934 | +5.3% ★ | 全部并入 |
| `VisibilityAwareCascadeStrategy` | 3923 | +5.0% | 阈值跨越 `CROSSING_BONUS=5.0` |
| `CPMCascadeStrategy` | 3878 | +3.8% | CPM 评分、assembly 抢占 |
| `DelayAwareCascadeStrategy` | 4711（带 300+400ms 延迟） | +2.1% vs 同延迟基线 | 激进预烹饪/存储阈值 |
| `PreemptScoreCascadeStrategy` | 3793 | +1.5% | 已被 CPM 涵盖，未并入 |
| `GreedyCascadeStrategy` | 3736 | — | 10 级瀑布框架基类 |

### 3.2 策略切换

```bash
# CLI
python -m playground run --strategy gastronome
python -m playground bench --strategies gastronome

# 代码
from hawarma.agent.registry import get_strategy
strategy = get_strategy("gastronome")
```

## 4. 核心优化总结（GastronomeStrategy）

| 优化 | 说明 | 来源 |
|------|------|------|
| SPT 排序 | 最短处理时间优先（关键路径法） | `CPMCascadeStrategy` |
| visibility 阈值 | 跨越阈值订单 CP -5s 加成 | `VisibilityAwareCascadeStrategy` |
| 单食材优先 | 1-ingredient 订单 CP -0.3s | `CPMEnhancedCascadeStrategy` |
| Rush tiebreaker | 同 CP 时 Rush 优先 | 修复后所有变体共有 |
| 调料优先 | 食材齐全时先加调料再烹饪 | `GreedyCascadeStrategy` |
| 最长烹饪优先 | 同订单内先煮最慢的食材 | `GreedyCascadeStrategy` |
| 主动预烹饪 | 灶台空闲时预烹饪（仅 stop_time=15s 前） | `GreedyCascadeStrategy` + `DelayAwareCascadeStrategy` 阈值 |
| 智能存储 | 紧急度排序（needed > near-expired > normal） | `DelayAwareCascadeStrategy` |
| 动画期间烹饪 | 送餐动画不阻塞烹饪 | `GreedyCascadeStrategy` |

## 5. 效率指标说明

Playground 基准测试输出以下效率指标：

| 指标 | Gastronome（参考值） | 说明 |
|------|---------------------|------|
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
python -m playground bench --games 100 --strategies gastronome

# 导出 CSV
python -m playground bench --games 100 --csv results.csv

# 单局
python -m playground run --seed 42 --strategy gastronome
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

### 7.6 订单优先级

甜点订单的优先级排序：

1. **rush 订单优先**：rush 订单始终最高优先级
2. **先进先出**：相同优先级的订单按到达顺序处理
3. **超时时间**：即将超时的订单优先处理

### 7.7 状态追踪

甜点策略使用隐式状态追踪：

- **MixingBowlState**：追踪搅拌盆状态（食材、调味品、是否搅拌完成）
- **CookerState**：追踪 cooker 状态（复用现有）

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
      distance: 400        # 滑动距离（像素）
      duration: 1.5        # 滑动持续时间（秒）
      steps: 10            # Airtest 插值步数
    mixing_bowl_position:  # 搅拌盆屏幕坐标
      - 1245
      - 870
    cookers_positions:     # 甜点灶台固定坐标
      dessert_oven:
        - 715
        - 615
      cooling_plate:
        - 1260
        - 590
    cooker_retention: 5.0  # 甜点灶台食材停留时间
```

### 7.10 使用方法

```bash
# CLI（station 模式默认为 gastronome）
python -m hawarma --station dessert --strategy dessert

# TUI
python -m hawarma.tui  # 在配置面板中选择 station 和 strategy

# 代码
from hawarma.agent.registry import get_strategy
strategy = get_strategy("dessert")
```

### 7.11 未来扩展

甜点策略支持未来扩展：

- 支持更多甜点类型：只需在 `recipes.json` 中添加新的甜点菜谱
- 可配置参数：搅拌参数、位置参数、超时参数都可配置
- 架构易于扩展：策略设计支持未来添加新的决策逻辑
