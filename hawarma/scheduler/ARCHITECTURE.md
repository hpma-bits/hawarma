# hawarma/scheduler 目录架构

## 📁 目录概述

此目录包含游戏的唯一决策中心（调度器）。所有业务策略都在这里：
- 订单优先级
- Stockpile分配和补货
- 动作规划

## ⚠️ 重要提示

**一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**

## 📄 文件列表

### `__init__.py`
- **地位**: 包初始化文件
- **导出**: `Scheduler`, `OrderPolicy`, `StockpilePolicy`

### `scheduler.py`
- **地位**: 统一调度器
- **状态**: ✅ 完成
- **功能**:
  - 协调所有决策
  - 返回Action列表供Executor执行
  - 阶段规划（finish → prep → refill → advance）
- **关键方法**:
  - `get_next_actions()` - 主入口，每tick调用
  - `_get_finish_actions()` - 获取完成订单动作
  - `_get_prep_actions()` - 获取食材准备动作
  - `_get_slot_advance_actions()` - 获取槽位移动作

### `order_policy.py`
- **地位**: 订单优先级策略
- **状态**: ✅ 完成
- **功能**:
  - Rush-first排序
  - 按提交时间打破平局
  - 防止饥饿（不让普通订单等待太久）
- **关键方法**:
  - `get_sorted_active_orders()` - 按优先级排序
  - `get_order_urgency()` - 计算紧急程度
  - `get_orders_needing_seasoning()` - 获取待调味订单

### `stockpile_policy.py`
- **地位**: Stockpile策略
- **状态**: ✅ 完成
- **功能**:
  - 会话级别: 分配3个stockpile槽位
  - Tick级别: 决定何时补货
- **关键方法**:
  - `should_use_stockpile()` - 是否使用库存
  - `get_stockpile_refill_actions()` - 获取补货动作
  - `_assign_slots()` - 分配stockpile槽位

### `agent_scheduler.py`
- **地位**: 高效 Agent 调度器
- **状态**: ✅ 完成
- **功能**:
  - 替换原有 Scheduler，提供更高性能
  - 全局优化：跨订单共享资源
  - 预烹饪：空闲灶台补充库存
  - 激进并行：同时启动多个灶台
- **关键方法**:
  - `get_next_actions()` - 主入口
  - `_try_finish_order()` - 立即送餐
  - `_try_start_cooking()` - 全局灶台分配
  - `_precook_for_stockpile()` - 预烹饪策略
- **性能**: 平均 13.5 订单/90秒，最高 20 订单

## 🔗 模块间关系

```
GameState (读取) + SessionState (读取)
         ↓
┌────────────────────────────────────────┐
│           Scheduler                     │
│  - 调用OrderPolicy获取优先级             │
│  - 调用StockpilePolicy获取补货决策       │
│  - 生成Action列表                       │
└────────────────┬───────────────────────┘
                 ↓
         [Action列表]
                 ↓
┌────────────────────────────────────────┐
│           Executor                     │
│  执行动作，更新GameState                 │
└────────────────────────────────────────┘
```

## 决策流程

```
_tick_loop():
    1. Scheduler.get_next_actions()
           ↓
    2. Phase 1: _get_finish_actions()
           - 检查 READY_TO_SEASON 订单
           - 返回 FinishOrder 动作
           ↓
    3. Phase 2: _get_prep_actions()
           - 遍历排序后的pending订单
           - 对每个食材: stockpile优先 or 烹饪
           - 返回 CookIngredient / PullFromStockpile 动作
           ↓
    4. Phase 3: _get_slot_advance_actions()
           - 检查槽位是否有空隙
           - 返回 AdvanceSlots 动作
           ↓
    5. Executor.execute_batch(actions)
           ↓
    6. GameState更新 → 下一tick
```

## 策略设计

### Stockpile槽位分配

```
_assign_slots():
    for ingredient in unique_ingredients:
        score = freq + cooker_contention*0.5 + duration*0.2
    top_3_by_score → stockpile_assignments
```

### 补货决策

```
get_stockpile_refill_actions():
    for slot, ingredient in stockpile_assignments:
        if stock < 5 AND cooker_free:
            return CookIngredient(→stockpile)
```

### 准备决策

```
_get_prep_actions():
    for order in sorted_orders:
        for ingredient in recipe.raw_ingredients:
            if stockpile.has(ingredient):
                return PullFromStockpile
            elif cooker_free:
                return CookIngredient(→assembly)
```
