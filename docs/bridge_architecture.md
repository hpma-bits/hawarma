# 轻量级 Agent Bridge 架构设计 v2

## 1. 设计原则

**最轻量方案**：
1. **只 detect 订单** - 其他状态通过程序逻辑追踪
2. **不使用 GameSimulator** - 实现 `GameEnvironment` 类，接口兼容但内部实现不同
3. **Agent 直接交互** - Agent 与 GameEnvironment 交互，无需中间层

## 2. 架构图

```
┌─────────────────────────────────────────────────────┐
│                  Real Game Bridge                    │
├─────────────────────────────────────────────────────┤
│                                                      │
│  ┌────────────────┐      ┌────────────────┐         │
│  │ GameEnvironment│◄────►│ CookingAgent   │         │
│  │  (状态追踪)    │      │  (决策大脑)    │         │
│  └───────┬────────┘      └────────────────┘         │
│          │                                          │
│          │ 执行动作时                              │
│          ▼                                          │
│  ┌────────────────┐      ┌────────────────┐         │
│  │   OrderScanner │      │   UIRunner     │         │
│  │   (订单检测)    │      │   (swipe)      │         │
│  └────────────────┘      └────────────────┘         │
│                                                      │
└─────────────────────────────────────────────────────┘
```

## 3. 核心组件

### 3.1 GameEnvironment

替代 GameSimulator，接口兼容但实现不同：

```python
class GameEnvironment:
    """
    游戏环境 - 状态通过程序逻辑追踪
    
    与 GameSimulator 的区别：
    - 不模拟游戏规则
    - 不 tick() 推进时间
    - 状态通过实际操作和订单检测更新
    """
    
    def __init__(self, config: AppConfig):
        # 订单状态（通过检测更新）
        self.orders: list[Order | None] = [None] * 4
        
        # 灶台状态（通过操作追踪）
        self.cookers: dict[str, CookerState] = {}
        
        # 组装站状态（通过操作追踪）
        self.assembly: AssemblyState = AssemblyState()
        
        # 库存状态（通过操作追踪）
        self.stockpile: dict[str, int] = {}
        
        # 时间追踪
        self.start_time: float = 0
        self.is_running: bool = False
    
    # === Agent 接口（与 GameSimulator 兼容）===
    
    def get_order(self, slot_idx: int) -> Order | None:
        """获取订单"""
        return self.orders[slot_idx]
    
    def get_cooker_state(self, cooker_name: str) -> CookerState:
        """获取灶台状态"""
        return self.cookers.get(cooker_name, CookerState())
    
    def is_in_animation_window(self) -> bool:
        """是否在动画窗口期"""
        # 通过程序追踪
        return self._animation_until > time.time()
    
    def is_game_over(self) -> bool:
        """游戏是否结束"""
        return time.time() - self.start_time >= 90
    
    # === 操作执行（更新内部状态 + 执行 UI）===
    
    async def start_cooking(self, ingredient: str, cooker: str) -> ActionResult:
        """开始烹饪"""
        # 1. 检查前置条件
        if self.cookers[cooker].busy:
            return ActionResult.failure("Cooker busy")
        
        # 2. 执行 UI 操作
        await self.ui.swipe(
            self.positions.ingredients[ingredient],
            self.positions.cookers[cooker]
        )
        
        # 3. 更新内部状态
        self.cookers[cooker] = CookerState(
            busy=True,
            ingredient_name=ingredient,
            started_at=time.time(),
            done_at=time.time() + duration
        )
        
        return ActionResult.success()
    
    async def move_to_assembly(self, cooker: str) -> ActionResult:
        """移动到组装站"""
        # 执行 UI 操作
        await self.ui.swipe(
            self.positions.cookers[cooker],
            self.positions.assembly
        )
        
        # 更新状态
        self.assembly.ingredients.append(self.cookers[cooker].ingredient_name)
        self.cookers[cooker] = CookerState()
        
        return ActionResult.success()
    
    async def serve_order(self, slot_idx: int) -> ActionResult:
        """送餐"""
        # 执行 UI 操作
        await self.ui.swipe(
            self.positions.assembly,
            self.positions.pickups[slot_idx]
        )
        
        # 更新状态
        self.orders[slot_idx] = None
        self.assembly = AssemblyState()
        self._animation_until = time.time() + 1.5
        
        return ActionResult.success()
```

### 3.2 OrderScanner

只检测订单，最轻量检测：

```python
class OrderScanner:
    """
    订单扫描器
    
    从截图检测订单，是唯一的"感知"组件
    """
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.recipes = self._load_recipes()
    
    def scan_orders(self) -> list[Order | None]:
        """
        扫描所有订单槽位
        
        Returns:
            4 个槽位的订单列表
        """
        screen = G.DEVICE.snapshot()
        orders = []
        
        for slot_idx in range(4):
            order = self._detect_order(slot_idx, screen)
            orders.append(order)
        
        return orders
    
    def _detect_order(self, slot: int, screen) -> Order | None:
        """检测单个订单"""
        roi = self.config.screen.orders_regions[slot]
        
        # 检测食材图标
        for recipe in self.recipes:
            template = Template(f"static/img/ingredient-{recipe.raw_ingredients[0]}.jpg")
            match = local_match(template, roi, screen)
            
            if match and match["confidence"] > 0.7:
                # 检测是否 rush
                is_rush = self._detect_rush(slot, screen)
                
                return Order(
                    recipe=recipe,
                    is_rush=is_rush,
                    created_at=time.time()
                )
        
        return None
```

### 3.3 UIRunner

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
            swipe(start, end, duration=duration)
            await asyncio.sleep(0.1)
```

## 4. 主循环

```python
class RealGameBridge:
    """主桥接器"""
    
    def __init__(self, config: AppConfig):
        self.env = GameEnvironment(config)
        self.agent = CookingAgent(self.env)
        self.scanner = OrderScanner(config)
        self.ui = UIRunner(config)
    
    async def run(self):
        """主循环"""
        self.env.start_time = time.time()
        
        # 启动订单扫描任务
        scan_task = asyncio.create_task(self._scan_loop())
        
        # 启动 agent 决策任务
        agent_task = asyncio.create_task(self._agent_loop())
        
        await asyncio.gather(scan_task, agent_task)
    
    async def _scan_loop(self):
        """订单扫描循环"""
        while not self.env.is_game_over():
            if not self.env.is_in_animation_window():
                orders = await asyncio.to_thread(self.scanner.scan_orders)
                self.env.orders = orders
            
            await asyncio.sleep(0.5)
    
    async def _agent_loop(self):
        """Agent 决策循环"""
        while not self.env.is_game_over():
            if not self.env.is_in_animation_window():
                action = self.agent.step()
                if action:
                    await self._execute_action(action)
            
            await asyncio.sleep(0.1)
```

## 5. 状态追踪策略

| 状态 | 追踪方式 | 原因 |
|------|---------|------|
| 订单 | 检测 | 唯一需要外部感知的状态 |
| 灶台 | 程序追踪 | 我们控制何时开始烹饪 |
| 组装站 | 程序追踪 | 我们控制何时移动食材 |
| 库存 | 程序追踪 | 我们控制何时存储/取用 |
| 时间 | time.time() | 真实时间 |
| 动画窗口 | 程序追踪 | 我们知道何时送餐 |

## 6. 与 GameSimulator 的接口兼容

Agent 只需要这些接口：

```python
# Agent 需要的接口
class GameProtocol(Protocol):
    def get_order(self, slot_idx: int) -> Order | None: ...
    def get_cooker_state(self, cooker: str) -> CookerState: ...
    def is_in_animation_window(self) -> bool: ...
    def is_game_over(self) -> bool: ...
    @property
    def state(self) -> GameState: ...
```

GameEnvironment 实现这些接口，Agent 可以直接使用。

## 7. 文件结构

```
hawarma/
├── environment/
│   ├── __init__.py
│   ├── game_env.py        # GameEnvironment
│   ├── order_scanner.py   # OrderScanner
│   └── ui_runner.py       # UIRunner
├── agent/
│   ├── __init__.py        # CookingAgent
│   └── v2.py              # CookingAgentV2
└── bridge.py              # RealGameBridge

scripts/
└── run_bridge.py          # 运行脚本
```

## 8. 配置

复用现有 `configs/config.yaml`，无需额外配置。

## 9. 对比

| 方案 | 检测范围 | 代码量 | 复杂度 |
|------|---------|--------|--------|
| 原系统 | 订单+灶台+组装站+库存 | ~2000行 | 高 |
| v1 方案 | 订单+灶台+组装站+库存 | ~500行 | 中 |
| v2 方案 | 只检测订单 | ~300行 | 低 |

## 10. 总结

v2 方案的核心优势：

1. **最轻量检测**：只检测订单，其他状态程序追踪
2. **最简架构**：3 个核心组件，~300 行代码
3. **接口兼容**：Agent 可以无缝切换 simulator/environment
4. **易于调试**：状态追踪透明，问题定位简单
