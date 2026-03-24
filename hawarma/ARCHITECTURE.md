# hawarma Directory Architecture

## 📁 目录概述

此目录是hawarma项目的核心模块，包含应用的主要逻辑、服务、模型和工具。

## ⚠️ 重要提示

**一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**

## 📄 文件列表

### `__init__.py`
- **地位**: 包初始化文件
- **功能**: 标识Python包

### `app.py`
- **地位**: 核心应用类（已重构为生命周期管理器）
- **功能**:
  - 初始化服务和全局状态
  - 运行扫描循环（检测新订单）
  - 运行调度循环（调度+执行动作）
  - 停止和清理
- **输入**: 配置对象、配方列表
- **输出**: 应用运行状态、订单完成统计
- **注意**: 所有业务决策已移至Scheduler，执行已移至Executor

### `actions.py`
- **地位**: 动作类型定义
- **功能**: 定义Scheduler返回的所有行动计划类型
- **输入**: Scheduler决策结果
- **输出**: Executor可执行的原子动作对象
- **关键类型**: `CookIngredient`, `PullFromStockpile`, `FinishOrder`, `AdvanceSlots`

### `config.py`
- **地位**: 配置管理模块
- **功能**:
  - 从YAML文件加载配置
  - 使用Pydantic进行配置验证
- **输入**: YAML配置文件路径
- **输出**: AppConfig对象

### `logging_setup.py`
- **地位**: 日志配置模块
- **功能**: 使用loguru配置应用日志系统

### `models.py`
- **地位**: 数据模型定义模块
- **功能**:
  - 定义Ingredient、Cooker、Recipe等数据模型
  - 定义Order和OrderStage枚举
- **输入**: JSON数据或构造参数
- **输出**: 验证后的模型对象

### `monkey_patches.py`
- **地位**: 兼容性补丁模块
- **功能**: 修复airtest框架的兼容性问题

### `scheduler/` 子目录
- **地位**: 调度策略层（唯一决策中心）
- **功能**: 所有业务决策（订单优先级、stockpile策略、动作规划）
- **文件**:
  - `scheduler.py`: 统一调度器
  - `order_policy.py`: 订单优先级逻辑
  - `stockpile_policy.py`: Stockpile决策逻辑

### `services/` 子目录
- **地位**: 服务执行层
- **功能**: 检测和执行
- **文件**:
  - `detection_service.py`: 订单检测（保持不变）
  - `executor.py`: 原子UI动作执行
  - `resource_guards.py`: 物理资源锁
  - `recipe_manager.py`: 配方管理（保持不变）

### `state.py`
- **地位**: 运行时真相来源
- **功能**:
  - GameState: 游戏运行时状态
  - SessionState: 会话配置状态
- **输入**: DetectionService检测结果、Executor操作结果
- **输出**: 供Scheduler决策的完整游戏状态快照

### `ui_operation_manager.py`
- **地位**: UI操作管理器
- **功能**: 全局UI锁，序列化所有swipe/click操作

### `utils/` 子目录
包含工具函数：
- `image_utils.py`: 图像处理工具

## 🔗 模块间关系

```
main.py
    ↓
CookingBotApp (app.py) - 生命周期管理
    ↓
    ├─→ DetectionService (订单检测)
    ├─→ Scheduler (唯一决策中心)
    │       ├─→ OrderPolicy (订单优先级)
    │       └─→ StockpilePolicy (库存策略)
    ├─→ Executor (原子动作执行)
    ├─→ ResourceGuards (物理资源锁)
    └─→ GameState / SessionState (全局状态)
```

## 架构设计原则

1. **Scheduler是唯一大脑**: 所有业务决策都在scheduler层
2. **Executor只执行**: 不做决策，只执行UI动作
3. **State是唯一真相**: 所有组件通过GameState同步状态
4. **ResourceGuards只保护**: 不包含任何业务策略
