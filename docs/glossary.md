# 术语表

> 本文档定义 Hawarma 项目中常用的术语，统一概念理解。

---

## 1. 游戏领域术语

### 订单系统

| 术语 | 英文 | 说明 |
|------|------|------|
| 订单 | Order | 屏幕上显示的菜品需求，最多 4 个同时存在 |
| 订单槽位 | Order Slot | 订单在界面上的显示位置，索引 0-3 |
| Rush 订单 | Rush Order | 背景为红色的加急订单，时限更短、得分更高 |
| 普通订单 | Normal Order | 非 rush 的普通订单 |
| 订单超时 | Order Timeout | 订单超过时限未完成，自动移除 |
| 订单刷新 | Order Refresh | 订单被完成后，3-5 秒随机间隔后出现新订单 |

### 食材与烹饪

| 术语 | 英文 | 说明 |
|------|------|------|
| 食材 | Ingredient | 烹饪所需的原材料，从食材区获取 |
| 调料 | Condiment | 添加到菜品中的调味品，从调料区获取 |
| 配方 | Recipe | 定义菜品所需的食材、灶台、烹饪时长和调料 |
| 烹饪 | Cook | 将食材从食材区 swipe 到灶台，开始加热 |
| 烹饪时长 | Cook Duration | 食材在灶台上需要的时间，由配方决定 |
| 过期 | Expired | 食材在灶台停留超过 5 秒未移走，需清理到垃圾桶 |

### 界面元素

| 术语 | 英文 | 说明 |
|------|------|------|
| 灶台 | Cooker | 烹饪设备，最多 4 个（grill, oven, skillet, pot） |
| 组装站 | Assembly Station | Gastronome 模式的中间容器，组装食材和调料 |
| 搅拌盆 | Mixing Bowl | Dessert 模式的中间容器，搅拌食材和调料 |
| 食材区 | Ingredients Area | 屏幕上食材所在的位置 |
| 调料区 | Condiments Area | 屏幕上调料所在的位置 |
| 库存区 | Stockpile | 存储已烹饪食材的区域，3 个槽位 |
| 取餐台 | Pickup Station | 完成的菜品送到此处，与订单槽位一一对应 |
| 垃圾桶 | Trash | 丢弃过期或不需要的食材的位置 |

### 评分机制

| 术语 | 英文 | 说明 |
|------|------|------|
| 基础分 | Base Points | 完成订单获得的基础分数 |
| Visibility | Visibility | 已完成订单的总可见度值，用于得分加成 |
| 得分加成 | Score Bonus | 根据总 visibility 所在区间，订单获得的额外百分比加成 |

---

## 2. 架构术语

### 分层架构

| 术语 | 说明 |
|------|------|
| 数据层 | `hawarma/core/` — Action、Recipe、UnifiedState 等数据定义 |
| 策略层 | `hawarma/agent/` — Strategy 纯决策单元 |
| 环境层 | `hawarma/game/` — Env 状态管理、Runner 编排、Operator 执行 |

### 核心组件

| 术语 | 英文 | 说明 |
|------|------|------|
| Strategy | Strategy | 纯决策单元：`decide(state) -> Action`，不接触环境 |
| Env | Environment | 游戏环境，管理游戏状态，提供 `get_unified_state()` |
| Runner | Runner | 编排器，协调扫描、超时、决策三个并行循环 |
| Operator | Operator | UI 操作执行器，将符号化操作转换为屏幕坐标并执行 swipe |
| Scanner | Scanner | 订单扫描器，从屏幕截图中检测订单 |
| Verifier | Verifier | 验证器，送餐后验证组装站是否清空 |

### 状态与数据

| 术语 | 英文 | 说明 |
|------|------|------|
| UnifiedState | UnifiedState | 环境对 Strategy 暴露的不可变状态快照 |
| CookerState | CookerState | 灶台状态：busy、ingredient_name、done_at、expired_at |
| AssemblyState | AssemblyState | 组装站状态：食材列表、目标配方、调料 |
| MixingBowlState | MixingBowlState | 搅拌盆状态：食材列表、调料、是否搅拌完成 |
| StockpileSlot | StockpileSlot | 库存槽位状态：食材名、灶台类型、数量 |
| OrderInfo | OrderInfo | 订单信息：order_id、recipe_slug、is_rush、timeout_at |

---

## 3. 策略术语

### 策略类型

| 术语 | 说明 |
|------|------|
| DefaultStrategy | 默认策略：主动预烹饪 + 决策优先级优化 |
| CPMStrategy | 关键路径法策略：最短处理时间优先，高吞吐 |
| CPMEnhancedStrategy | CPM 增强策略：单食材优先 + visibility 阈值，当前最佳 |
| VisibilityAwareStrategy | Visibility 感知策略：CPM + visibility 阈值跨越加成 |
| PreemptScoreStrategy | 分数抢占策略：分数/CP 效率排序 + 进度感知抢占 |
| DessertStrategy | 甜点策略：搅拌盆流水线决策 |

### 决策概念

| 术语 | 说明 |
|------|------|
| 关键路径法 (CPM) | Critical Path Method，根据最短处理时间排序的策略 |
| 抢占 | Preempt | 在组装站有未完成菜品时，清空并重新开始新订单 |
| 预烹饪 | Pre-cooking | 灶台空闲时主动烹饪可能需要的食材 |
| 决策优先级 | Decision Priority | 策略按优先级顺序检查各操作，执行第一个可行的操作 |
| 流水线决策 | Pipeline Decision | 甜点模式下，当前订单烹饪时开始下一个订单的准备 |

---

## 4. 操作术语

### Action 类型

| 术语 | Action 类名 | 说明 |
|------|------------|------|
| 烹饪 | `CookAction` | 食材区 → 灶台 |
| 移到组装站 | `MoveToAssemblyAction` | 灶台 → 组装站 |
| 调味 | `AddCondimentAction` | 调料区 → 组装站 |
| 送餐 | `ServeOrderAction` | 组装站 → 取餐台 |
| 移到库存 | `MoveToStockpileAction` | 灶台 → 库存 |
| 从库存取出 | `PullFromStockpileAction` | 库存 → 组装站 |
| 清理灶台 | `ClearCookerAction` | 清理过期食材到垃圾桶 |
| 清空组装站 | `ClearAssemblyAction` | 丢弃组装站上的所有食材 |
| 添加食材到搅拌盆 | `MoveToMixingBowlAction` | 食材区 → 搅拌盆（甜点） |
| 调味到搅拌盆 | `AddCondimentToMixingBowlAction` | 调料区 → 搅拌盆（甜点） |
| 搅拌 | `StirAction` | 搅拌盆内单次左滑（甜点） |
| 搅拌盆移到灶台 | `MoveMixingBowlToCookerAction` | 搅拌盆 → 灶台（甜点） |
| 从灶台出餐 | `ServeFromCookerAction` | 灶台 → 取餐台（甜点） |
| 清空搅拌盆 | `ClearMixingBowlAction` | 丢弃搅拌盆中的食材（甜点） |

---

## 5. Station 模式术语

| 术语 | 说明 |
|------|------|
| Station | 制作台类型枚举：`GASTRONOME`（美食）或 `DESSERT`（甜点） |
| Gastronome | 美食模式：食材 → 灶台 → 组装站 → 取餐台 |
| Dessert | 甜点模式：食材 → 搅拌盆 → 调味 → 搅拌 → 灶台 → 取餐台 |
| 不混合模式 | Gastronome 和 Dessert 不会出现在同一局游戏中 |

---

## 6. UI 操作术语

| 术语 | 英文 | 说明 |
|------|------|------|
| Swipe | Swipe | 滑动操作，从起点坐标滑动到终点坐标 |
| 动画窗口 | Animation Window | 订单提交后的 1.5 秒动画期间，限制扫描和送餐操作 |
| 模板匹配 | Template Matching | 通过图像模板在屏幕上查找目标元素 |
| ROI | Region of Interest | 感兴趣区域，限定图像匹配的搜索范围 |
| Ghost 订单 | Ghost Order | 已完成但屏幕残留的订单，1.5 秒内被过滤 |

---

## 7. 并发术语

| 术语 | 英文 | 说明 |
|------|------|------|
| 三循环并行 | Three-loop Parallelism | 扫描循环 + 超时循环 + 决策循环并行运行 |
| 扫描循环 | Scan Loop | 每 0.4-0.5 秒扫描一次订单 |
| 超时循环 | Timeout Loop | 每 0.3 秒检查订单超时 |
| 决策循环 | Agent Loop | 事件驱动，有状态变化时被唤醒 |
| 唤醒 | Wakeup | `_agent_wakeup` 事件，通知决策循环有新信息 |

---

## 8. 配置术语

| 术语 | 说明 |
|------|------|
| `config.yaml` | 主配置文件，包含所有运行参数 |
| `AppConfig` | Pydantic 配置模型，从 YAML 加载 |
| `ScreenConfig` | 屏幕坐标配置，定义各元素位置 |
| `MatchingConfig` | 图像匹配参数配置 |
| `GameConfig` | 游戏参数配置（灶台保留时间、swipe 参数等） |
| `StationsConfig` | 站点配置，包含 `gastronome` 和 `dessert` 子节 |

---

## 9. Playground 术语

| 术语 | 说明 |
|------|------|
| Playground | 模拟器，用于快速验证策略和基准测试 |
| SimEnv | 模拟器环境，实现 Env 接口的模拟版本 |
| 基准测试 | Benchmark | 运行多局游戏，统计策略的平均表现 |
| Episode | 一局完整游戏 |
| EpisodeResult | 一局游戏的结果统计 |

---

## 10. 缩写与符号

| 缩写 | 全称 | 说明 |
|------|------|------|
| CPM | Critical Path Method | 关键路径法 |
| SPT | Shortest Processing Time | 最短处理时间优先 |
| DIP | Dependency Inversion Principle | 依赖倒置原则 |
| DI | Dependency Injection | 依赖注入 |
| ABC | Abstract Base Class | 抽象基类 |
| DTO | Data Transfer Object | 数据传输对象 |
| Env | Environment | 环境 |
| Ing | Ingredient | 食材（简写） |
| Cond | Condiment | 调料（简写） |
| Cooker | Cooker | 灶台 |
