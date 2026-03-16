# 烹饪Bot优化架构蓝图

## 零、系统完整组成

### 0.1 CLI用户界面 (main.py)

```python
# 主要功能
- setup_airtest(): 初始化Airtest设备（Android模拟器mumu）
- get_recipe_selection(): 用户交互式选择配方和准备顺序
- main(): 应用入口，协调各组件初始化和运行

# 用户交互流程
1. 用户通过checkbox选择要使用的配方
2. 用户输入菜谱顺序（如'012'表示按原顺序） # 我在这里修改了你原先的typo
3. 等待游戏开始（检测timer-icon）
4. 运行应用主循环
5. 支持暂停/继续/退出
```

### 0.2 日志系统 (logging_setup.py)

```python
# 日志配置
- 输出到stderr（彩色格式）
- 输出到logs/app_{time}.log（文件轮转）
- 日志级别：DEBUG/INFO/WARNING/ERROR
- 轮转策略：10MB/文件，保留10天

# 日志格式
- 控制台：<时间> | <级别> | <文件:函数:行> - <消息>
- 文件：{time} {level} {message}
```

---

## 一、当前架构问题分析

### 1.1 UI操作锁与资源锁混淆

**问题**：当前存在两类不同职责的锁，但未区分清晰：
- **资源锁**（cooker_locks、assembly_lock、stockpile_locks）：防止多个订单占用同一游戏资源
- **UI操作锁**：确保同一时刻只有1个UI操作发送到游戏（游戏规则要求）

**正确理解**：
- 资源锁应该**保留**，防止订单之间的资源冲突
- UI操作锁是**新增**层，确保UI操作串行发送到游戏
- 两类锁是**正交**的，可以共存

**影响**：需要在架构中明确区分这两层锁的职责。

### 1.2 Rush Order优先级未实现

**问题**：虽然文档说明rush order具有更高优先级，但当前代码中未实现该逻辑。同时rush order识别代码未正确实现。 # 这部分你可以参考相关的test文件

**影响**：rush order可能得不到及时处理，导致超时失败。

### 1.3 StockpileManager未被使用

**问题**：已实现完整的事件驱动StockpileManager，但app.py仍在使用旧的轮询方式（`_manage_stockpile_task`）。

**影响**：代码重复，事件驱动架构的优势未发挥。

### 1.4 订单识别逻辑与文档不符

**问题**：文档描述"先检测食材，无冲突则确定，有冲突则检测厨具"，但代码仅检测食材。

**影响**：当多个配方使用相同第一个食材时无法正确区分。

### 1.5 订单补位机制不完整

**问题**：订单提交后槽位补位的逻辑未完整实现，特别是submit位置的动态变化。以及补位动画期间不应进行scan操作。

**影响**：
- 补位后订单submit位置计算错误
- 补位动画期间（1-1.5秒）scan可能捕捉到未刷新完的页面

**解决方案**：在订单提交后设置1.5秒冷却时间，期间禁止scan操作。

---

## 二、优化架构设计

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         启动层 (main.py)                                 │
│  ┌─────────────────────┐              ┌─────────────────────────────┐  │
│  │      CLI界面        │              │       日志系统              │  │
│  │  (questionary)      │              │     (loguru)                │  │
│  │                     │              │                             │  │
│  │ - 配方选择          │              │ - 控制台输出                │  │
│  │ - 顺序配置          │              │ - 文件轮转                  │  │
│  │ - 游戏开始检测      │              │ - 级别控制                  │  │
│  └─────────────────────┘              └─────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                           CookingBotApp                                  │
│                     (核心协调器，仅做决策)                                │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────┐ │
│  │  OrderScheduler │  │ PipelineExecutor│  │ StockpileController     │ │
│  │   订单调度器     │  │   管道执行器     │  │     库存控制器          │ │
│  │                 │  │                 │  │                         │ │
│  │ - 排序rush优先  │  │ - 阶段状态机    │  │ - 事件驱动集成         │ │
│  │ - 计算submit位置│  │ - 并发协调      │  │ - 触发stockpile        │ │
│  └────────┬────────┘  └────────┬────────┘  └────────────┬────────────┘ │
│           │                    │                       │              │
│           └────────────────────┼───────────────────────┘              │
│                                ↓                                         │
│                    ┌─────────────────────┐                             │
│                    │ UIOperationManager  │                             │
│                    │   全局UI操作管理器   │                             │
│                    │                     │                             │
│                    │ - 全局UI操作锁      │                             │
│                    │ - 序列化所有swipe   │                             │
│                    │ - 操作队列管理      │                             │
│                    └──────────┬──────────┘                             │
│                               ↓                                          │
│                    ┌─────────────────────┐                             │
│                    │    CookingService   │                             │
│                    │     (执行层)        │                             │
│                    └─────────────────────┘                             │
└─────────────────────────────────────────────────────────────────────────┘
                                      ↓
                    ┌─────────────────────────────────┐
                    │         游戏界面                │
                    │  (通过Airtest API交互)          │
                    └─────────────────────────────────┘
```

### 2.2 核心组件设计

#### 2.2.1 UIOperationManager - 全局UI操作管理器

```python
class UIOperationManager:
    """
    统一管理所有UI操作，确保同一时刻只有1个UI操作发送到游戏
    
    职责：
    1. 全局UI锁 - 序列化所有swipe/click操作
    2. 操作队列 - 按优先级执行操作
    3. 操作日志 - 记录所有UI操作便于调试
    
    注意：此锁与资源锁（cooker_locks, assembly_lock等）是正交的
    - 资源锁：防止多个订单占用同一游戏资源
    - UI操作锁：确保UI操作串行发送到游戏
    两者可以共存，执行顺序：先获取资源锁，再获取UI锁
    """
    
    def __init__(self):
        self._global_ui_lock = asyncio.Lock()
        self._operation_queue: asyncio.Queue = asyncio.Queue()
    
    async def execute(self, operation_type: str, operation: callable, *args, **kwargs):
        """
        执行UI操作的统一入口
        
        Args:
            operation_type: 操作类型（swipe, click, drag等）
            operation: 要执行的异步操作函数
            *args, **kwargs: 操作参数
        """
        async with self._global_ui_lock:
            logger.debug(f"Executing UI operation: {operation_type}")
            result = await operation(*args, **kwargs)
            logger.debug(f"UI operation completed: {operation_type}")
            return result
    
    async def swipe(self, start, end, **kwargs):
        """封装swipe操作"""
        return await self.execute(
            "swipe",
            self._do_swipe,
            start, end, **kwargs
        )
    
    async def _do_swipe(self, start, end, duration=0.1):
        """实际的swipe执行"""
        swipe(start, end, duration=duration)
        await asyncio.sleep(0.1)  # 等待动画
```

**设计要点**：
- 所有UI操作必须通过此类执行
- 内部维护全局锁，确保串行执行
- 可扩展支持操作队列和优先级

#### 2.2.2 OrderScheduler - 订单调度器

```python
class OrderScheduler:
    """
    订单调度器：负责排序和调度订单处理顺序
    
    职责：
    1. Rush order优先处理
    2. 根据槽位补位机制计算实际的submit位置
    3. 动态调整处理顺序
    """
    
    def __init__(self, max_slots: int = 4):
        self._max_slots = max_slots
    
    def get_processing_order(self, order_slots: list[Order | None]) -> list[tuple[int, Order]]:
        """
        获取订单处理顺序，rush订单优先
        
        Returns:
            [(slot_index, order), ...] 按优先级排序的订单列表
        """
        rush_orders = []
        normal_orders = []
        
        for i, order in enumerate(order_slots):
            if order is None or order.done:
                continue
            
            if order.is_rush:
                rush_orders.append((i, order))
            else:
                normal_orders.append((i, order))
        
        # Rush订单优先处理
        return rush_orders + normal_orders
    
    def get_submit_position(self, order: Order, order_slots: list[Order | None]) -> int:
        """
        计算订单的实际提交位置
        
        槽位补位机制：
        - 订单提交后，右侧订单自动向左补位
        - 提交位置 = 订单当前在slots中的索引
        - 补位后，后续订单的提交位置发生变化
        - **补位动画时间**：约1秒（建议保守1.5秒），此期间应避免scan操作
        
        Args:
            order: 要提交的客户订单
            order_slots: 当前所有订单槽位
            
        Returns:
            提交目标在pickup_stations中的索引
        """
        # 找到订单在当前slots中的位置
        for i, o in enumerate(order_slots):
            if o is order:
                return i
        
        raise ValueError(f"Order {order.order_id} not found in slots")
    
    def should_accept_new_order(self, order_slots: list[Order | None]) -> bool:
        """
        判断是否应该接受新订单
        
        规则：4个槽位满时不会刷新新订单
        """
        return None in order_slots
```

**设计要点**：
- rush订单始终排在前面
- submit位置根据当前slots动态计算
- 支持判断是否接受新订单
- **Cooker留存时间**：食材烹饪完成后在cooker上最多留存5秒，超时需移到厨余垃圾箱(130, 560)
- **Stockpile配合优化**：后续订单食材可先烹饪存stockpile，前订单提交后立即组装

#### 2.2.3 PipelineExecutor - 管道执行器

```python
class PipelineExecutor:
    """
    订单处理管道执行器
    
    职责：
    1. 管理订单的各个处理阶段
    2. 协调并发执行（内部通过全局UI锁串行）
    3. 处理订单完成和槽位补位
    """
    
    def __init__(
        self,
        ui_manager: UIOperationManager,
        cooking_service: CookingService,
        stockpile_controller: "StockpileController",
    ):
        self._ui_manager = ui_manager
        self._cooking_service = cooking_service
        self._stockpile_controller = stockpile_controller
    
    async def process_order(self, order: Order, slot_index: int, order_slots: list):
        """
        处理单个订单的完整流程
        
        流程：食材准备 → 烹饪 → 调味 → 上菜
        """
        # 阶段1: 食材准备
        await self._prepare_ingredients(order, slot_index)
        
        # 阶段2: 烹饪（与食材准备并行）
        # 注意：内部通过UI锁串行执行
        
        # 阶段3: 调味
        await self._season_order(order)
        
        # 阶段4: 上菜
        await self._serve_order(order, slot_index)
    
    async def _prepare_ingredients(self, order: Order, slot_index: int):
        """准备订单所需食材"""
        order.current_stage = OrderStage.HEATING
        
        # 并发准备所有食材（内部会串行执行UI操作）
        tasks = []
        for ingredient in order.recipe.raw_ingredients:
            # 优先使用库存
            if await self._stockpile_controller.use_stock(ingredient):
                tasks.append(self._use_stocked_ingredient(ingredient))
            else:
                tasks.append(self._cook_ingredient(order.recipe, ingredient))
        
        await asyncio.gather(*tasks)
        order.current_stage = OrderStage.READY_TO_SEASON
    
    async def _season_order(self, order: Order):
        """为订单添加调料"""
        order.current_stage = OrderStage.SEASONING
        
        for condiment, count in order.condiment_preference.items():
            for _ in range(count):
                await self._ui_manager.swipe(
                    self._condiments_positions[condiment],
                    self._assembly_station
                )
        
        order.current_stage = OrderStage.SERVING
    
    async def _serve_order(self, order: Order, slot_index: int):
        """将菜品送到取餐区"""
        submit_pos = self._pickup_stations[slot_index]
        await self._ui_manager.swipe(self._assembly_station, submit_pos)
        
        order.done = True
        order.served_ts = asyncio.get_event_loop().time()
```

**设计要点**：
- 内部使用UIOperationManager保证UI操作串行
- 支持食材准备和烹饪的并行协调
- 完成后自动标记订单状态

#### 2.2.4 StockpileController - 库存控制器

```python
class StockpileController:
    """
    库存控制器：集成事件驱动的StockpileManager
    
    职责：
    1. 管理预烹饪食材库存
    2. 与StockpileManager事件驱动集成
    3. 提供库存使用接口
    """
    
    def __init__(
        self,
        stockpile_manager: StockpileManager,
        ingredient_stock_counts: Counter,
        stock_lock: asyncio.Lock,
    ):
        self._stockpile_manager = stockpile_manager
        self._stock_counts = ingredient_stock_counts
        self._stock_lock = stock_lock
    
    async def start(self):
        """启动库存管理"""
        await self._stockpile_manager.start()
    
    async def stop(self):
        """停止库存管理"""
        await self._stockpile_manager.stop()
    
    async def use_stock(self, ingredient_name: str) -> bool:
        """
        尝试使用库存食材
        
        Returns:
            True if stock was used, False if no stock available
        """
        async with self._stock_lock:
            if self._stock_counts[ingredient_name] > 0:
                self._stock_counts[ingredient_name] -= 1
                return True
            return False
    
    async def notify_order_status(self, order: Order, status: str):
        """通知订单状态变化，触发stockpile决策"""
        await self._stockpile_manager.notify_order_status_changed(order, status)
    
    async def notify_cooker_available(self, cookers: list[str]):
        """通知有烹饪设备可用"""
        await self._stockpile_manager.notify_cooker_available(cookers)
```

**设计要点**：
- 包装StockpileManager，提供简洁API
- 管理库存计数和锁
- 事件驱动与主流程解耦

#### 2.2.5 改进的DetectionService

```python
class DetectionService:
    """订单检测服务 - 改进版"""
    
    def _detect_recipe(self, order_slot: int, screen: np.ndarray) -> Tuple[Recipe | None, float]:
        """
        识别订单配方
        
        策略：
        1. 先检测第一个食材
        2. 如果只有一个配方匹配该食材，直接返回
        3. 如果有多个配方匹配（冲突），再检测厨具来区分
        """
        # Step 1: 检测第一个食材
        ingredient_matches = self._detect_first_ingredient(order_slot, screen)
        
        if not ingredient_matches:
            return None, 0.0
        
        # Step 2: 冲突检测
        if len(ingredient_matches) == 1:
            # 无冲突，直接返回
            return ingredient_matches[0]
        
        # Step 3: 有冲突，检测厨具来区分
        return self._resolve_cooker_conflict(ingredient_matches, order_slot, screen)
    
    def _detect_first_ingredient(self, order_slot: int, screen: np.ndarray) -> list[Tuple[Recipe, float]]:
        """
        检测第一个食材，返回所有匹配该食材的配方
        
        Returns:
            [(recipe, confidence), ...] 所有第一个食材匹配的配方
        """
        matches = []
        roi = self._get_ingredient_roi(order_slot, 0)
        
        for recipe in self.recipes:
            template_path = self.image_dir / f"ingredient-{recipe.raw_ingredients[0]}.jpg"
            if not template_path.exists():
                continue
            
            result = local_match(Template(str(template_path)), roi=roi, screen=screen)
            if result and (confidence := float(result["confidence"])) > 0.7:
                matches.append((recipe, confidence))
        
        return matches
    
    def _resolve_cooker_conflict(
        self,
        candidate_recipes: list[Tuple[Recipe, float]],
        order_slot: int,
        screen: np.ndarray
    ) -> Tuple[Recipe | None, float]:
        """
        通过检测厨具解决冲突
        
        当多个配方使用相同的第一个食材时，检测订单区中的厨具图标来区分
        """
        best_match = None
        best_confidence = 0.0
        
        for recipe, ingredient_confidence in candidate_recipes:
            # 获取该配方第一个食材对应的厨具
            cooker = recipe.cookers[0]
            cooker_icon_path = self.image_dir / f"icon-{cooker}.jpg"
            
            if not cooker_icon_path.exists():
                continue
            
            # 在订单区域检测厨具图标
            # 注意：厨具图标位于订单区域的最左边1/4处，与第一个食材位于同一区域（上下关系）
            order_region = self.config.screen.orders_regions[order_slot]
            match = local_match(
                Template(str(cooker_icon_path), threshold=0.7),
                roi=order_region,
                screen=screen
            )
            
            if match:
                # 组合置信度：食材置信度 * 厨具置信度
                combined_confidence = ingredient_confidence * float(match["confidence"])
                if combined_confidence > best_confidence:
                    best_match = recipe
                    best_confidence = combined_confidence
        
        return best_match, best_confidence
```

---

## 三、数据流设计

### 3.1 主循环流程

```
┌─────────────────────────────────────────────────────────────────┐
│                        CookingBotApp.run()                       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  1. 订单扫描 (OrderScanner)                                      │
│     - 检测空槽位                                                 │
│     - 调用DetectionService.detect_order()                       │
│     - OrderScheduler判断是否接受新订单                          │
│     - 提交订单后需等待1.5秒补位动画完成再scan                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  2. 订单调度 (OrderScheduler)                                    │
│     - 按rush优先排序                                             │
│     - 计算各订单的submit位置                                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  3. 管道执行 (PipelineExecutor)                                  │
│     - 对每个订单执行: 准备→烹饪→调味→上菜                        │
│     - 通过UIOperationManager保证UI操作串行                       │
│     - 完成后触发订单状态变化事件                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  4. 槽位补位                                                     │
│     - 订单完成/超时后从slots移除                                  │
│     - 右侧订单自动向左补位                                       │
│     - 更新各订单的submit位置                                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  5. 库存管理 (StockpileController)                               │
│     - 响应订单状态变化事件                                       │
│     - 烹饪设备可用时尝试预烹饪                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 事件驱动库存流程

```
订单完成/烹饪开始
        ↓
StockpileController.notify_order_status()
        ↓
StockpileManager事件队列
        ↓
_on_order_status_changed() / _on_cooker_available()
        ↓
计算stockpile优先级
        ↓
执行烹饪并更新库存
```

---

## 四、关键设计决策

### 4.1 UI操作序列化

- **决策**：使用全局UIOperationManager单一锁
- **理由**：游戏规则要求"同一时刻只能有1个UI操作"
- **影响**：所有swipe操作必须通过此管理器

### 4.2 Rush Order优先处理

- **决策**：OrderScheduler.get_processing_order()返回排序列表，rush订单排在前面
- **理由**：游戏规则"rush order有更高的优先级，应该优先处理"
- **实现**：分离rush和normal订单列表，rush在前

### 4.3 槽位补位与submit位置

- **决策**：submit位置 = 订单当前在order_slots中的索引
- **理由**：订单槽位同时也是提交位置
- **动态性**：补位后需重新计算submit位置

### 4.4 事件驱动库存

- **决策**：保留StockpileManager事件驱动架构，集成到主流程
- **理由**：事件驱动消除轮询，更高效
- **集成**：通过StockpileController包装，提供简洁API

---

## 五、文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `main.py` | 修改 | 集成新的架构组件，CLI流程保持不变 |
| `hawarma/logging_setup.py` | 保留 | 日志系统保持不变 |
| `hawarma/app.py` | 重构 | 拆分出OrderScheduler、PipelineExecutor等组件 |
| `hawarma/services/cooking_service.py` | 修改 | 保留资源锁（cooker_locks等），增加UIOperationManager集成 |
| `hawarma/services/detection_service.py` | 修改 | 实现食材+厨具组合识别 |
| `hawarma/services/stockpile_manager.py` | 保留 | 事件驱动架构，保持不变 |
| `hawarma/ui_operation_manager.py` | 新增 | 全局UI操作管理器 |
| `hawarma/services/__init__.py` | 更新 | 导出新组件 |

---

## 六、总结

优化后的架构：

1. **UIOperationManager** - 确保所有UI操作串行执行，符合游戏规则
2. **OrderScheduler** - 实现rush订单优先和submit位置计算
3. **PipelineExecutor** - 清晰的订单处理管道
4. **StockpileController** - 集成事件驱动库存管理
5. **改进DetectionService** - 食材+厨具组合识别
6. **资源锁保留** - cooker_locks、assembly_lock、stockpile_locks继续保护游戏资源

核心原则：
- 资源锁（cooker_locks等）：保护游戏资源不被多订单并发占用 - **保留**
- UI操作锁（UIOperationManager）：确保UI操作串行发送到游戏 - **新增**
- 两类锁正交共存，执行顺序：先获取资源锁，再获取UI锁
- Rush订单始终优先处理
- 事件驱动库存管理
- 订单识别采用食材+厨具双重验证