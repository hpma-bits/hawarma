# 轻量级 Agent Bridge 架构设计 v2

## 1. 设计原则

**最轻量方案**：
1. **只 detect 订单** - 其他状态通过程序逻辑追踪
2. **GameEnvironment** - 接口兼容 GameSimulator，但内部实现不同
3. **Agent 直接持有配方数据** - 烹饪时长从配方获取

## 2. 关键决策（已确认）

| 问题 | 决策 |
|------|------|
| 订单完成/超时 | 依赖内部状态追踪，送餐后认为完成 |
| 烹饪时长 | Agent 自己持有配方数据 |
| 调料信息 | 检测时获取，存储在订单中 |
| 游戏开始 | 检测 timer 图标，3 秒后正式开始 |
| 游戏结束 | 90 秒倒计时 |
| 异常处理 | 先信任操作成功 |

---

## 3. 架构图

```
┌─────────────────────────────────────────────────────┐
│                  RealGameBridge                      │
├─────────────────────────────────────────────────────┤
│                                                      │
│  ┌────────────────┐      ┌────────────────┐         │
│  │GameEnvironment │◄────►│ CookingAgent   │         │
│  │  (状态追踪)    │      │  (持有配方数据) │         │
│  └───────┬────────┘      └────────────────┘         │
│          │                                          │
│  ┌───────┴────────┐                                 │
│  │                │                                 │
│  ▼                ▼                                 │
│ OrderScanner    UIRunner                            │
│ (定时扫描)      (swipe操作)                         │
│                                                      │
└─────────────────────────────────────────────────────┘
```

---

## 4. 核心组件

### 4.1 RealGameBridge

主控制器，管理游戏生命周期：

```python
class RealGameBridge:
    def __init__(self, config: AppConfig, recipes: list[Recipe]):
        self.config = config
        self.env = GameEnvironment(config)
        self.agent = CookingAgentV2(self.env, recipes)
        self.scanner = OrderScanner(config, recipes)
        self.ui = UIRunner(config)
        
        self.game_start_time: float = 0
        self.game_duration: float = 90  # 秒
    
    async def run(self):
        """主循环"""
        # 1. 等待游戏开始
        await self._wait_for_game_start()
        
        # 2. 启动扫描和决策循环
        await asyncio.gather(
            self._scan_loop(),
            self._agent_loop()
        )
    
    async def _wait_for_game_start(self):
        """等待游戏开始：检测 timer，然后等待 3 秒"""
        logger.info("Waiting for game to start...")
        while not self.scanner.detect_timer():
            await asyncio.sleep(0.5)
        
        logger.info("Timer detected, waiting 3 seconds...")
        await asyncio.sleep(3)
        self.game_start_time = time.time()
        logger.info("Game started!")
    
    async def _scan_loop(self):
        """订单扫描循环"""
        while not self._is_game_over():
            if not self.env.is_in_animation_window():
                orders = await asyncio.to_thread(self.scanner.scan_orders)
                self.env.sync_orders(orders)
            await asyncio.sleep(0.5)
    
    async def _agent_loop(self):
        """Agent 决策循环"""
        while not self._is_game_over():
            if not self.env.is_in_animation_window():
                action = self.agent.step()
                if action:
                    await self._execute_action(action)
            await asyncio.sleep(0.1)
    
    def _is_game_over(self) -> bool:
        """游戏是否结束"""
        return time.time() - self.game_start_time >= self.game_duration
```

### 4.2 GameEnvironment

替代 GameSimulator，状态通过程序追踪：

```python
class GameEnvironment:
    """游戏环境 - 状态通过程序逻辑追踪"""
    
    def __init__(self, config: AppConfig):
        self.config = config
        
        # 订单状态（通过检测更新）
        self.orders: list[Order | None] = [None] * 4
        
        # 灶台状态（通过操作追踪）
        self.cookers: dict[str, CookerState] = {
            name: CookerState() for name in config.cookers
        }
        
        # 组装站状态（通过操作追踪）
        self.assembly: AssemblyState = AssemblyState()
        
        # 库存状态（通过操作追踪）
        self.stockpile: dict[str, int] = {}
        
        # 动画窗口
        self._animation_until: float = 0
    
    def is_in_animation_window(self) -> bool:
        return time.time() < self._animation_until
    
    def set_animation_window(self, duration: float = 1.5):
        self._animation_until = time.time() + duration
    
    def sync_orders(self, detected_orders: list[Order | None]):
        """同步订单状态"""
        for i, order in enumerate(detected_orders):
            # 只更新变化的 slot
            if order is not None and self.orders[i] is None:
                self.orders[i] = order
                logger.info(f"New order in slot {i}: {order.recipe.name}")
    
    # === 操作方法（更新内部状态）===
    
    def start_cooking(self, ingredient: str, cooker: str, duration: float) -> bool:
        """开始烹饪"""
        if self.cookers[cooker].busy:
            return False
        
        self.cookers[cooker] = CookerState(
            busy=True,
            ingredient_name=ingredient,
            cooker_type=cooker,
            started_at=time.time(),
            done_at=time.time() + duration
        )
        return True
    
    def move_to_assembly(self, cooker: str, order_id: int) -> bool:
        """移动到组装站"""
        cooker_state = self.cookers[cooker]
        if not cooker_state.busy or cooker_state.done_at is None:
            return False
        
        # 更新组装站
        self.assembly.ingredients.append(cooker_state.ingredient_name)
        self.assembly.order_id = order_id
        
        # 清空灶台
        self.cookers[cooker] = CookerState()
        return True
    
    def serve_order(self, slot_idx: int) -> bool:
        """送餐"""
        if self.orders[slot_idx] is None:
            return False
        
        # 清空订单和组装站
        self.orders[slot_idx] = None
        self.assembly = AssemblyState()
        self.set_animation_window(1.5)
        return True
```

### 4.3 CookingAgentV2

Agent 持有配方数据，决策逻辑：

```python
class CookingAgentV2:
    """高效 Agent - 持有配方数据"""
    
    def __init__(self, env: GameEnvironment, recipes: list[Recipe]):
        self.env = env
        self.recipes = {r.slug: r for r in recipes}
        
        # 食材 → (灶台, 时长) 映射
        self.ingredient_info: dict[str, tuple[str, float]] = {}
        for recipe in recipes:
            for i, ing in enumerate(recipe.raw_ingredients):
                cooker = recipe.cookers_layout[i] if i < len(recipe.cookers_layout) else recipe.cookers[i]
                duration = recipe.cook_durations[i]
                self.ingredient_info[ing] = (cooker, duration)
    
    def step(self) -> Action | None:
        """单步决策"""
        # 1. 送餐
        if action := self._try_serve():
            return action
        
        # 2. 移动到组装站
        if action := self._try_move_to_assembly():
            return action
        
        # 3. 从库存取用
        if action := self._try_pull_from_stockpile():
            return action
        
        # 4. 烹饪
        if action := self._try_cook():
            return action
        
        return None
    
    def _try_serve(self) -> Action | None:
        """尝试送餐"""
        if self.env.is_in_animation_window():
            return None
        
        assembly = self.env.assembly
        if not assembly.ingredients:
            return None
        
        # 找到匹配的订单
        for slot_idx, order in enumerate(self.env.orders):
            if order is None:
                continue
            
            # 检查食材是否匹配
            if self._ingredients_match(assembly.ingredients, order.recipe.raw_ingredients):
                return FinishOrder(slot_idx=slot_idx)
        
        return None
    
    def _try_cook(self) -> Action | None:
        """尝试烹饪"""
        # 获取需要的食材
        needed = self._get_needed_ingredients()
        
        for ing_name in needed:
            if ing_name not in self.ingredient_info:
                continue
            
            cooker, duration = self.ingredient_info[ing_name]
            
            # 检查灶台是否空闲
            if not self.env.cookers[cooker].busy:
                return CookAction(
                    ingredient=ing_name,
                    cooker=cooker,
                    duration=duration
                )
        
        return None
```

### 4.4 OrderScanner

订单扫描器，只检测订单：

```python
class OrderScanner:
    """订单扫描器"""
    
    def __init__(self, config: AppConfig, recipes: list[Recipe]):
        self.config = config
        self.recipes = recipes
        self.image_dir = Path(config.image_directory)
    
    def detect_timer(self) -> bool:
        """检测 timer 图标（游戏开始标志）"""
        screen = G.DEVICE.snapshot()
        timer_path = self.image_dir / "icon-timer.jpg"
        
        if not timer_path.exists():
            return False
        
        # 在屏幕顶部检测 timer
        roi = (0, 0, 1920, 100)
        match = local_match(Template(str(timer_path)), roi, screen)
        return match is not None
    
    def scan_orders(self) -> list[Order | None]:
        """扫描所有订单"""
        screen = G.DEVICE.snapshot()
        orders = []
        
        for slot_idx in range(4):
            order = self._detect_order(slot_idx, screen)
            orders.append(order)
        
        return orders
    
    def _detect_order(self, slot: int, screen) -> Order | None:
        """检测单个订单"""
        roi = self.config.screen.orders_regions[slot]
        
        for recipe in self.recipes:
            # 检测第一个食材图标
            ing_path = self.image_dir / f"ingredient-{recipe.raw_ingredients[0]}.jpg"
            if not ing_path.exists():
                continue
            
            match = local_match(Template(str(ing_path)), roi, screen)
            if match and float(match["confidence"]) > 0.7:
                # 检测是否 rush
                is_rush = self._detect_rush(slot, screen)
                
                return Order(
                    recipe=recipe,
                    is_rush=is_rush,
                    created_at=time.time(),
                    timeout_at=time.time() + (40 if is_rush else 70)
                )
        
        return None
    
    def _detect_rush(self, slot: int, screen) -> bool:
        """检测是否 rush 订单"""
        timer_path = self.image_dir / "icon-timer.jpg"
        if not timer_path.exists():
            return False
        
        roi = self.config.screen.orders_regions[slot]
        match = local_match(Template(str(timer_path), threshold=0.8), roi, screen)
        return match is not None
```

### 4.5 UIRunner

UI 操作执行器：

```python
class UIRunner:
    """UI 操作执行器"""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self._lock = asyncio.Lock()
    
    async def swipe(self, start: tuple, end: tuple, duration: float = 0.1):
        """执行滑动"""
        async with self._lock:
            logger.debug(f"Swipe: {start} -> {end}")
            swipe(start, end, duration=duration)
            await asyncio.sleep(0.1)
```

---

## 5. Action 类型

```python
@dataclass
class Action:
    """动作基类"""
    pass

@dataclass
class CookAction(Action):
    """烹饪动作"""
    ingredient: str
    cooker: str
    duration: float

@dataclass
class MoveToAssemblyAction(Action):
    """移动到组装站"""
    cooker: str
    order_id: int

@dataclass
class PullFromStockpileAction(Action):
    """从库存取用"""
    ingredient: str
    slot: int

@dataclass
class FinishOrder(Action):
    """送餐"""
    slot_idx: int
```

---

## 6. 动作执行

```python
async def _execute_action(self, action: Action):
    """执行动作"""
    if isinstance(action, CookAction):
        await self._execute_cook(action)
    elif isinstance(action, MoveToAssemblyAction):
        await self._execute_move_to_assembly(action)
    elif isinstance(action, PullFromStockpileAction):
        await self._execute_pull(action)
    elif isinstance(action, FinishOrder):
        await self._execute_finish(action)

async def _execute_cook(self, action: CookAction):
    """执行烹饪"""
    ing_pos = self._get_ingredient_position(action.ingredient)
    cooker_pos = self._get_cooker_position(action.cooker)
    
    # 食材 → 灶台
    await self.ui.swipe(ing_pos, cooker_pos)
    
    # 更新状态
    self.env.start_cooking(action.ingredient, action.cooker, action.duration)
    
    # 等待烹饪
    await asyncio.sleep(action.duration)
    
    # 灶台 → 组装站
    assembly_pos = self.config.screen.assembly_station_position
    await self.ui.swipe(cooker_pos, assembly_pos)
    
    # 更新状态
    self.env.move_to_assembly(action.cooker, order_id=0)  # TODO: 正确的 order_id

async def _execute_finish(self, action: FinishOrder):
    """执行送餐"""
    assembly_pos = self.config.screen.assembly_station_position
    pickup_pos = self.config.screen.pickup_stations_positions[action.slot_idx]
    
    # 组装站 → 取餐台
    await self.ui.swipe(assembly_pos, pickup_pos)
    
    # 更新状态
    self.env.serve_order(action.slot_idx)
    self.env.set_animation_window(1.5)
```

---

## 7. 文件结构

```
hawarma/
├── bridge/
│   ├── __init__.py
│   ├── bridge.py          # RealGameBridge
│   ├── environment.py     # GameEnvironment
│   ├── scanner.py         # OrderScanner
│   ├── ui_runner.py       # UIRunner
│   └── actions.py         # Action 类型
├── agent/
│   ├── __init__.py        # CookingAgentV2（适配 bridge）
│   └── v2.py              # 原有 agent（模拟器用）

scripts/
└── run_bridge.py          # 运行脚本
```

---

## 8. 待讨论问题

### 8.1 食材位置映射

`config.yaml` 中 `raw_ingredients_positions` 是固定 8 个位置。但实际游戏中食材位置取决于选中的配方。

问题：如何确定食材的屏幕位置？
- A. 从配置的 8 个位置中，根据食材索引映射
- B. 每次检测食材位置（更灵活但更慢）

### 8.2 配料取用时机

Agent 需要从库存取用食材，但库存位置是固定的。

问题：库存槽位如何分配？
- A. 固定分配（每个槽位存固定食材）
- B. 动态分配（按需存储）

### 8.3 烹饪等待期间

执行烹饪后需要等待 `duration` 秒。期间：
- 其他灶台可以同时开始烹饪
- 订单扫描继续进行

问题：是否需要并行等待多个灶台？

### 8.4 调料添加

当前方案保留调料检测，但 Agent 如何知道添加哪种调料？
- 配方中有 `condiments` 列表
- 检测时有 `condiment_preference`

问题：是否需要实现 `add_condiment` 操作？
