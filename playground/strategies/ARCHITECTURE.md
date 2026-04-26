# playground/strategies 目录架构

## 📁 目录概述

此目录包含所有策略实现。Strategy 接收 UnifiedState，返回 Action。

## ⚠️ 重要提示

**一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**

## 📄 文件列表

### `base.py`
- **地位**: Strategy 抽象基类
- **功能**: 定义 `decide(state) -> Action | None` 接口，所有策略必须实现

### `default.py`
- **地位**: 默认策略（主动预烹饪 + 决策优先级优化）
- **功能**: 
  1. 调料优先：组装站食材齐全时立即添加调料
  2. 最长烹饪优先：按时长降序烹饪食材
  3. 主动预烹饪：灶台空闲时预烹饪活跃订单的未来食材
  4. 快速存储：非必要食材2秒后存储（vs CookingFirstV2Strategy的4秒）
  5. 过期优先移动：优先移动接近过期的食材到组装站
  6. 库存优先取用：为组装站目标优先拉取库存
- **基准**: 18.9 orders/game, 3177 avg reward, 0% timeout (+10.3% reward vs CookingFirstV2Strategy)

### `cooking_first_v2.py`
- **地位**: 旧版策略（Cooking First v2）
- **功能**: 7级优先级贪婪决策：清理 → 送餐 → 过期清理 → 移动 → 烹饪 → 调料 → 库存
- **基准**: 17.0 orders/game, 2880 avg reward, 0% timeout

### `stockpile_first.py`
- **地位**: 库存优先策略变体（基于 CookingFirstV2Strategy）
- **功能**: 将 pull_from_stockpile 提升到 cook 之前

## 📊 策略对比（200局基准测试）

| 策略 | 完成订单 | 平均得分 | 超时率 | 动作数 |
|------|----------|----------|--------|--------|
| DefaultStrategy | 18.9 | 3177 | 0% | 137.6 |
| CookingFirstV2Strategy | 17.0 | 2880 | 0% | 109.6 |
| StockpileFirstStrategy | ~17.0 | ~2852 | 0% | ~108.4 |

## 🔗 与其他模块的关系

- **输入**: `UnifiedState` (from `playground/env/unified_state.py`)
- **输出**: `Action` (from `hawarma/agent/agent.py`)
- **使用**: `Agent` (from `playground/agents/base.py`) 包装 Strategy 并与环境交互