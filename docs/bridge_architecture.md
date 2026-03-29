# 轻量级 Agent Bridge 架构设计

## 1. 核心思路

基于现有的 `GameSimulator` + `CookingAgent`，创建一个轻量级 bridge 与真实游戏交互。

**不重用**：复杂的 Scheduler/Executor/ResourceGuards/State 架构
**重用**：GameSimulator（规则引擎）+ CookingAgent（决策大脑）

## 2. 架构图

```
┌─────────────────────────────────────────────────────────┐
│                    Real Game Bridge                      │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────┐      ┌──────────────┐                 │
│  │ GameSimulator │      │ CookingAgent │                 │
│  │  (规则引擎)   │◄────►│  (决策大脑)   │                 │
│  └──────┬───────┘      └──────────────┘                 │
│         │                                               │
│         ▼                                               │
│  ┌──────────────┐      ┌──────────────┐                 │
│  │    Bridge    │      │    Airtest   │                 │
│  │  (状态同步)   │◄────►│  (UI 操作)   │                 │
│  └──────────────┘      └──────────────┘                 │
│                                                          │
└─────────────────────────────────────────────────────────┘
         │                           │
         ▼                           ▼
  ┌──────────────┐           ┌──────────────┐
  │  游戏截图    │           │  UI 操作     │
  │  (detection) │           │  (swipe)     │
  └──────────────┘           └──────────────┘
```

## 3. 核心组件

### 3.1 RealGameBridge

轻量级桥接器，整合所有功能：

```python
class RealGameBridge:
    """
    轻量级游戏桥接器
    
    职责：
    1. 从真实游戏截图检测状态
    2. 将状态同步到 GameSimulator
    3. 调用 CookingAgent 获取动作
    4. 将动作转换为 UI 操作
    """
    
    def __init__(self, config: BridgeConfig):
        self.sim = GameSimulator()           # 规则引擎
        self.agent = CookingAgent(self.sim)  # 决策大脑
        self.detector = GameDetector()       # 状态检测
        self.ui = UIRunner()                 # UI 操作
        
        # 位置映射
        self.positions = config.positions
```

### 3.2 GameDetector

状态检测器，从截图提取游戏状态：

```python
class GameDetector:
    """
    从屏幕截图检测游戏状态
    
    使用 Airtest 进行模板匹配
    """
    
    def detect_orders(self, screen) -> list[Order]:
        """检测4个订单槽位"""
        
    def detect_cookers(self, screen) -> dict[str, CookerState]:
        """检测4个灶台状态"""
        
    def detect_assembly(self, screen) -> AssemblyState:
        """检测组装站状态"""
        
    def detect_stockpile(self, screen) -> dict[str, int]:
        """检测库存状态"""
```

### 3.3 UIRunner

UI 操作执行器：

```python
class UIRunner:
    """
    执行 UI 操作（swipe）
    
    封装 Airtest 的 swipe 函数
    """
    
    def swipe(self, start: tuple, end: tuple, duration: float = 0.1):
        """执行滑动操作"""
        from airtest.core.api import swipe
        swipe(start, end, duration=duration)
    
    def cook(self, ingredient_pos: tuple, cooker_pos: tuple):
        """烹饪：食材 → 灶台"""
        self.swipe(ingredient_pos, cooker_pos)
    
    def move_to_assembly(self, cooker_pos: tuple, assembly_pos: tuple):
        """移动到组装站：灶台 → 组装站"""
        self.swipe(cooker_pos, assembly_pos)
    
    def serve(self, assembly_pos: tuple, pickup_pos: tuple):
        """送餐：组装站 → 取餐台"""
        self.swipe(assembly_pos, pickup_pos)
```

## 4. 主循环

```python
async def run(self):
    """主循环"""
    while not self.is_game_over():
        # 1. 截图
        screen = self.capture_screen()
        
        # 2. 检测状态
        game_state = self.detector.detect_all(screen)
        
        # 3. 同步到 simulator
        self.sync_state(game_state)
        
        # 4. 获取 agent 动作
        actions = self.agent.step()
        
        # 5. 执行动作
        for action in actions:
            await self.execute_action(action)
        
        # 6. 等待
        await asyncio.sleep(0.1)
```

## 5. 状态同步策略

### 5.1 订单同步

```python
def sync_orders(self, detected_orders: list[Order]):
    """
    将检测到的订单同步到 simulator
    
    策略：
    - 新订单：inject_order
    - 已完成订单：标记完成
    - 已超时订单：触发超时
    """
    for slot, order in enumerate(detected_orders):
        sim_order = self.sim.get_order(slot)
        
        if order is None and sim_order is not None:
            # 订单消失（完成或超时）
            self._handle_order_completed(slot)
        elif order is not None and sim_order is None:
            # 新订单出现
            self.sim.inject_order(slot, order.recipe, order.is_rush)
```

### 5.2 灶台同步

```python
def sync_cookers(self, detected_cookers: dict):
    """
    同步灶台状态
    
    策略：
    - 检测灶台是否 busy
    - 检测食材是否完成
    - 检测食材是否过期
    """
    for cooker_name, state in detected_cookers.items():
        sim_cooker = self.sim.get_cooker_state(cooker_name)
        
        if state.is_done and not sim_cooker.is_done(self.sim.time):
            # 烹饪完成
            self.sim.tick(state.done_at - self.sim.time)
```

## 6. 动作转换

### 6.1 CookIngredient

```python
def execute_cook(self, action: CookIngredient):
    """执行烹饪动作"""
    # 找到食材位置
    ing_pos = self.positions.ingredients[action.ingredient_name]
    
    # 找到灶台位置
    cooker_pos = self.positions.cookers[action.cooker_name]
    
    # 执行滑动
    self.ui.cook(ing_pos, cooker_pos)
    
    # 等待烹饪时间
    await asyncio.sleep(duration)
    
    # 移动到目标位置
    if action.destination == "assembly":
        self.ui.move_to_assembly(cooker_pos, self.positions.assembly)
    else:
        stockpile_pos = self.positions.stockpiles[action.stockpile_slot]
        self.ui.move_to_stockpile(cooker_pos, stockpile_pos)
```

### 6.2 PullFromStockpile

```python
def execute_pull(self, action: PullFromStockpile):
    """从库存取用"""
    stockpile_pos = self.positions.stockpiles[action.stockpile_slot]
    assembly_pos = self.positions.assembly
    
    self.ui.swipe(stockpile_pos, assembly_pos)
```

### 6.3 FinishOrder

```python
def execute_serve(self, action: FinishOrder):
    """送餐"""
    assembly_pos = self.positions.assembly
    pickup_pos = self.positions.pickups[action.pickup_slot]
    
    self.ui.serve(assembly_pos, pickup_pos)
```

## 7. 配置

```yaml
# configs/bridge_config.yaml

screen:
  resolution: [1920, 1080]

positions:
  # 组装站
  assembly: [1375, 865]
  
  # 原料位置（动态映射）
  ingredients:
    hearthspice: [115, 930]
    acacia_honey: [265, 930]
    # ... 根据游戏配置
  
  # 灶台位置
  cookers:
    grill: [595, 585]
    oven: [850, 585]
    skillet: [1120, 585]
    pot: [1370, 585]
  
  # 库存位置
  stockpiles:
    - [800, 900]
    - [950, 900]
    - [1100, 900]
  
  # 取餐台位置
  pickups:
    - [610, 145]
    - [990, 145]
    - [1360, 145]
    - [1740, 145]
  
  # 丢弃位置
  trash: [130, 560]

detection:
  # 订单检测区域
  order_regions:
    - [500, 80, 720, 210]
    - [875, 80, 1095, 210]
    - [1250, 80, 1470, 210]
    - [1620, 80, 1840, 210]
  
  # 配方检测区域
  ingredient_regions:
    - [440, 250, 780, 385]
    - [815, 250, 1155, 385]
    - [1190, 250, 1530, 385]
    - [1565, 250, 1905, 385]

  # 匹配阈值
  confidence_threshold: 0.7

timing:
  # 操作延迟
  swipe_duration: 0.1
  post_swipe_delay: 0.1
  
  # 循环间隔
  tick_interval: 0.1
  detection_interval: 0.5
```

## 8. 文件结构

```
hawarma/
├── bridge/
│   ├── __init__.py          # 导出 RealGameBridge
│   ├── bridge.py            # 主桥接器
│   ├── detector.py          # 状态检测
│   └── ui_runner.py         # UI 操作
├── agent/
│   ├── __init__.py          # CookingAgent v1
│   └── v2.py                # CookingAgent v2
└── env_simulator.py         # 规则引擎

configs/
└── bridge_config.yaml       # 桥接器配置

scripts/
├── run_bridge.py            # 运行桥接器
└── test_bridge.py           # 测试桥接器
```

## 9. 与原系统的对比

| 组件 | 原系统 | 新方案 |
|------|--------|--------|
| 决策 | Scheduler + OrderPolicy + StockpilePolicy | CookingAgent |
| 执行 | Executor + ResourceGuards | UIRunner |
| 状态 | GameState + SessionState | GameSimulator |
| 检测 | DetectionService | GameDetector |
| UI | UIOperationManager | UIRunner |
| 总代码量 | ~2000 行 | ~500 行 |

## 10. 使用示例

```python
from hawarma.bridge import RealGameBridge
from hawarma.config import load_config

# 初始化
config = load_config()
bridge = RealGameBridge(config)

# 运行
asyncio.run(bridge.run())
```

## 11. 总结

新方案的核心优势：

1. **轻量级**：~500 行代码 vs ~2000 行
2. **复用性强**：直接使用现有的 GameSimulator 和 CookingAgent
3. **易于理解**：单一职责，清晰的组件边界
4. **易于调试**：可以在 simulator 中测试，无需真实游戏
5. **可扩展**：可以轻松替换 detector 或 agent
