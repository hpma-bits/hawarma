# playground/strategies 目录架构

## 📁 目录概述

此目录包含 Strategy 兼容层和 re-export。所有实际策略实现位于 `src/hawarma/agent/strategies/`。

## ⚠️ 重要提示

**一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**

## 📄 文件列表

### `base.py`
- **地位**: Strategy 抽象基类（re-export from `hawarma.agent.strategy`）
- **功能**: 定义 `decide(state) -> Action | None` 接口

### `__init__.py`
- **地位**: 兼容层 re-export
- **功能**: 导出所有可用策略类，方便 playground 和测试使用

## 可用策略

所有策略实现在 `src/hawarma/agent/strategies/` 中：

| 策略名 | 类 | 说明 |
|--------|-----|------|
| default | DefaultStrategy | 安全默认：主动预烹饪 + 决策优先级优化 |
| cpm | CPMStrategy | 关键路径法：SPT 优先，高吞吐 |
| visibility_aware | VisibilityAwareStrategy | CPM + visibility 阈值感知（当前最佳） |
| preempt_score | PreemptScoreStrategy | 分数权重抢占（激进型变体） |

## 策略基准测试排名（50局）

| Rank | Strategy | Avg Reward | vs #1 |
|------|----------|-----------|-------|
| 1 | VisibilityAwareStrategy | 3916 | baseline |
| 2 | CPMStrategy | 3878 | Δ -38 (n.s.) |
| 3 | PreemptScoreStrategy | 3793 | Δ -124 (p=0.01) |
| 4 | DefaultStrategy | 3736 | Δ -180 (p=0.01) |

## 已存档策略

无效/冗余策略移至 `src/hawarma/agent/strategies/archive/`：
- AgedCPMStrategy, ScoreAwareCPMStrategy, ScorePreemptStrategy
- BaselineStrategy, BaselineWithStockpileStrategy, PipelineBaselineStrategy
- CookingFirstV2Strategy, StockpileFirstStrategy

## 🔗 相关文档

- 策略实现：`src/hawarma/agent/strategies/ARCHITECTURE.md`
- 注册表：`src/hawarma/agent/strategy_registry.py`