# 开发流程指南

## 一、开发目标

基于 `architecture_blueprint.md` 的设计，优化现有烹饪Bot架构，实现以下目标：

1. **UI操作序列化** - 新增UIOperationManager，确保同一时刻只有1个UI操作
2. **Rush Order优先** - 新增OrderScheduler，实现rush订单优先处理
3. **完整订单识别** - 改进DetectionService，实现食材+厨具组合识别
4. **事件驱动库存** - 集成StockpileManager事件驱动架构
5. **补位冷却** - 订单提交后1.5秒内禁止scan

---

## 二、阶段划分

### 阶段0：准备与评估（1天）

**目标**：评估现有代码问题，确定开发优先级

**任务**：
- [ ] 运行现有测试，确认基线功能正常
- [ ] 分析待研究问题（Rush order时限、游戏时长延长机制）
- [ ] 确认需要修改的代码量

**依赖**：无

---

### 阶段1：基础设施 - UIOperationManager（2天）

**目标**：新增全局UI操作管理器，确保所有UI操作串行执行

**任务**：
1. 创建 `hawarma/ui_operation_manager.py`
2. 实现全局锁和操作封装
3. 修改 `CookingService` 集成 UIOperationManager

**新增文件**：
```
hawarma/ui_operation_manager.py
```

**修改文件**：
- `hawarma/services/cooking_service.py` - 集成UIOperationManager
- `hawarma/services/__init__.py` - 导出新组件

**测试**：
- 验证UI操作串行执行
- 验证多订单并发时无冲突

**依赖**：无

---

### 阶段2：订单检测改进（2天）

**目标**：改进DetectionService，实现食材+厨具组合识别

**任务**：
1. 新增 `_detect_first_ingredient()` 方法
2. 新增 `_resolve_cooker_conflict()` 方法
3. 修改 `_detect_recipe()` 调用逻辑

**修改文件**：
- `hawarma/services/detection_service.py`

**测试**：
- 验证无冲突时正确识别配方
- 验证有冲突时通过厨具正确区分

**依赖**：阶段1（需要测试验证）

---

### 阶段3：订单调度器（2天）

**目标**：新增OrderScheduler，实现rush订单优先和submit位置计算

**任务**：
1. 创建 `hawarma/services/order_scheduler.py`
2. 实现 `get_processing_order()` - rush优先排序
3. 实现 `get_submit_position()` - 计算提交位置
4. 修改 `app.py` 集成OrderScheduler

**新增文件**：
```
hawarma/services/order_scheduler.py
```

**修改文件**：
- `hawarma/app.py` - 集成OrderScheduler
- `hawarma/services/__init__.py` - 导出新组件

**测试**：
- 验证rush订单排在前面
- 验证submit位置计算正确

**依赖**：阶段2

---

### 阶段4：补位冷却机制（1天）

**目标**：订单提交后1.5秒内禁止scan操作

**任务**：
1. 修改 `app.py` 中的订单扫描逻辑
2. 添加 `last_order_completion_time` 冷却时间检查

**修改文件**：
- `hawarma/app.py`

**测试**：
- 验证补位动画期间不进行scan

**依赖**：阶段3

---

### 阶段5：库存管理重构（3天）

**目标**：集成事件驱动StockpileManager，替换现有轮询方式

**任务**：
1. 创建 `StockpileController` 包装类
2. 修改 `app.py` 集成StockpileController
3. 移除 `_manage_stockpile_task()` 旧代码

**新增文件**：
```
hawarma/services/stockpile_controller.py
```

**修改文件**：
- `hawarma/app.py` - 集成事件驱动库存
- `hawarma/services/__init__.py` - 导出新组件

**测试**：
- 验证库存事件驱动工作
- 验证库存计数正确

**依赖**：阶段4

---

### 阶段6：管道执行器重构（3天）

**目标**：新增PipelineExecutor，清晰分离订单处理阶段

**任务**：
1. 创建 `hawarma/services/pipeline_executor.py`
2. 迁移订单处理逻辑
3. 集成UIOperationManager

**新增文件**：
```
hawarma/services/pipeline_executor.py
```

**修改文件**：
- `hawarma/app.py` - 简化为仅做决策
- `hawarma/services/__init__.py` - 导出新组件

**测试**：
- 验证订单处理流程正常
- 验证阶段转换正确

**依赖**：阶段1、阶段3、阶段5

---

### 阶段7：集成与测试（2天）

**目标**：完整集成所有组件，端到端测试

**任务**：
1. 集成所有组件到main.py
2. 端到端功能测试
3. 性能测试

**修改文件**：
- `main.py` - 集成新架构

**测试**：
- 完整游戏流程测试
- 多订单并发测试
- Rush订单优先测试

**依赖**：阶段1-6全部完成

---

### 阶段8：清理与优化（1天）

**目标**：代码清理，优化性能

**任务**：
1. 移除未使用的代码
2. 优化O(n)操作
3. 更新文档

**修改文件**：
- 清理 `hawarma/services/assembly_station_manager.py` 或集成
- 更新ARCHITECTURE.md
- 更新AGENTS.md

**依赖**：阶段7

---

## 三、开发顺序图

```
阶段0: 准备
    ↓
阶段1: UIOperationManager ←─┐
    ↓                       │
阶段2: DetectionService ────┤
    ↓                       │
阶段3: OrderScheduler ──────┼── 阶段6依赖
    ↓                       │
阶段4: 补位冷却 ────────────┤
    ↓                       │
阶段5: StockpileManager ────┘
    ↓
阶段7: 集成测试
    ↓
阶段8: 清理优化
```

---

## 四、关键设计原则

### 4.1 测试驱动

每个阶段必须包含对应的测试：
- 单元测试：验证单个组件功能
- 集成测试：验证组件间协作
- 端到端测试：验证完整流程

### 4.2 渐进式重构

- 每阶段保持功能可用
- 不破坏现有测试
- 每次commit可独立运行

### 4.3 依赖管理

- 阶段按依赖排序
- 前置阶段完成后才开发后续阶段
- 并行开发需明确依赖边界

---

## 五、待研究问题

在开发过程中需要研究并补充：

1. **Rush Order时限**
   - 具体秒数未知
   - 需要通过游戏测试获取

2. **游戏时长延长机制**
   - 90秒基础，随玩家等级延长
   - 具体公式未知
   - 需要研究游戏逻辑

3. **AssemblyStationManager集成**
   - 现有代码未使用
   - 考虑是否需要集成或移除

---

## 六、文件变更总览

| 文件 | 阶段 | 操作 | 说明 |
|------|------|------|------|
| `hawarma/ui_operation_manager.py` | 1 | 新增 | 全局UI操作管理器 |
| `hawarma/services/detection_service.py` | 2 | 修改 | 食材+厨具组合识别 |
| `hawarma/services/order_scheduler.py` | 3 | 新增 | 订单调度器 |
| `hawarma/app.py` | 3,4,5,6 | 修改 | 集成各组件 |
| `hawarma/services/stockpile_controller.py` | 5 | 新增 | 库存控制器 |
| `hawarma/services/pipeline_executor.py` | 6 | 新增 | 管道执行器 |
| `main.py` | 7 | 修改 | 集成新架构 |
| `hawarma/services/__init__.py` | 1-7 | 修改 | 导出新组件 |

---

## 七、风险与缓解

### 风险1：现有功能破坏

**缓解**：每个阶段完成后运行现有测试

### 风险2：集成复杂性

**缓解**：阶段6之前保持组件独立测试

### 风险3：游戏机制不明确

**缓解**：阶段0确认待研究问题，必要时可先实现后调整

---

## 八、开发检查清单

每个阶段开始前：
- [ ] 确认前置阶段已完成
- [ ] 理解设计文档相关部分
- [ ] 规划具体任务

每个阶段完成后：
- [ ] 新增测试通过
- [ ] 现有测试仍然通过
- [ ] 提交代码并附说明

---

**总计预估**：约17天（不含阶段0准备和阶段8清理）