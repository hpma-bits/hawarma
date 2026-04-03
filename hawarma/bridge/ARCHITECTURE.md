# hawarma/bridge 目录架构

## 📁 目录概述

此目录包含真实游戏环境的桥接层，连接 Agent 与真实游戏。

## ⚠️ 重要提示

**一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**

## 📄 文件列表

### `__init__.py`
- **地位**: 包初始化文件
- **功能**: 导出所有桥接组件
- **导出**: `GameEnvironment`, `OrderScanner`, `UIRunner`, `RealGameBridge`

### `base_environment.py`
- **地位**: 游戏环境抽象基类
- **状态**: ✅ 完成
- **功能**:
  - 定义 Agent 与环境交互的统一接口
  - 定义统一数据结构（OrderInfo, CookerState, AssemblyState, StockpileSlot）
  - 确保 GameEnvironment 和 SimulatorEnvironment 使用相同的数据结构
- **输入**: 无（纯接口定义）
- **输出**: BaseEnvironment 抽象基类和统一数据结构
- **关键类**: `BaseEnvironment`, `OrderInfo`, `CookerState`, `AssemblyState`, `StockpileSlot`

### `environment.py`
- **地位**: 真实游戏环境
- **状态**: ✅ 完成
- **功能**:
  - 继承 BaseEnvironment，实现统一接口
  - 追踪灶台状态（通过程序逻辑）
  - 追踪组装站状态
  - 追踪库存状态
  - 追踪订单状态
  - 管理游戏时间
- **输入**: UI操作结果、订单检测结果
- **输出**: 游戏状态供Agent决策
- **关键类**: `GameEnvironment`

### `scanner.py`
- **地位**: 订单扫描器
- **状态**: ✅ 完成
- **功能**:
  - 检测屏幕上的订单
  - 识别配方和加急状态
  - 检测游戏开始（timer图标）
- **输入**: 屏幕截图、配置对象
- **输出**: 检测到的订单信息
- **关键类**: `OrderScanner`, `DetectedOrder`

### `ui_runner.py`
- **地位**: UI操作执行器
- **状态**: ✅ 完成
- **功能**:
  - 封装所有swipe操作
  - 从config.yaml读取坐标配置
  - 提供异步执行接口
  - **动态坐标映射**：根据菜谱选择顺序确定元素位置
- **输入**: 符号化操作（食材名、灶台名等）
- **输出**: swipe操作执行结果
- **关键类**: `UIRunner`

#### 坐标映射规则

UIRunner根据菜谱选择顺序动态确定各元素坐标：

1. **Cookers**：
   - 按菜谱顺序收集`cookers_layout`并去重
   - 根据种类数量选择槽位：1种→[1]，2种→[1,2]，3种→[0,1,2]，4种→[0,1,2,3]
   
2. **Ingredients**：
   - 按菜谱顺序收集`raw_ingredients`并去重
   - **反转顺序**后分配索引（从下到上、从左到右）
   
3. **Condiments**：
   - 按菜谱顺序收集`condiments`并去重
   - 按顺序分配索引（从下到上、从左到右）

详细规则参见 `docs/game_rules.md` 第2节。

### `bridge.py`
- **地位**: 真实游戏桥接器
- **状态**: ✅ 完成
- **功能**:
  - 协调Agent、环境、扫描器和UI执行器
  - 管理游戏生命周期
  - 运行扫描和决策循环
  - 执行Agent动作
- **输入**: 配置对象、配方列表
- **输出**: 游戏统计结果
- **关键类**: `RealGameBridge`

## 🔗 模块间关系

```
RealGameBridge (主控制器)
    ├── GameEnvironment (状态追踪)
    ├── OrderScanner (订单检测)
    ├── UIRunner (UI操作)
    └── CookingAgent (决策逻辑)
```

## 数据流

```
OrderScanner.scan_orders()
    ↓
DetectedOrder
    ↓
GameEnvironment.add_order()
    ↓
CookingAgent.step()
    ↓
Action
    ↓
RealGameBridge._execute_action()
    ↓
UIRunner.swipe()
    ↓
GameEnvironment状态更新
```

## 与模拟器的区别

| 方面 | 模拟器 (GameSimulator) | 真实环境 (GameEnvironment) |
|------|------------------------|---------------------------|
| 状态追踪 | 内置状态机 | 程序逻辑追踪 |
| 时间推进 | tick()方法 | 真实时间 |
| 操作执行 | 符号操作 | UI swipe操作 |
| 订单生成 | 随机生成 | 屏幕检测 |
| 用途 | 测试、算法优化 | 实际游戏 |

---

## 🔄 双循环并行架构详解

### 架构概述

RealGameBridge 采用 **双循环并行架构**，通过 `asyncio.gather()` 同时运行两个独立的异步循环：

```python
async def run(self) -> dict:
    # 1. 等待游戏开始
    await self._wait_for_game_start()
    
    # 2. 启动扫描和决策循环（并行执行）
    self._running = True
    try:
        await asyncio.gather(
            self._scan_loop(),      # 订单扫描循环
            self._agent_loop(),     # Agent决策循环
        )
    except asyncio.CancelledError:
        logger.info("Game cancelled")
    finally:
        self._running = False
    
    # 3. 返回统计结果
    return self._get_stats()
```

### 扫描循环 (_scan_loop)

**职责**：检测屏幕上新出现的订单，更新环境状态

**频率**：每 0.5 秒扫描一次

```python
async def _scan_loop(self) -> None:
    """订单扫描循环"""
    while self._running and not self.env.is_game_over():
        try:
            # 检查是否在动画窗口期（避免冲突）
            if not self.env.is_in_animation_window():
                # 扫描新订单
                new_orders = self.scanner.scan_new_orders()
                
                # 添加到环境状态
                for order in new_orders:
                    recipe = self._recipe_by_slug.get(order.recipe_slug)
                    if recipe:
                        self.env.add_order(
                            slot_idx=order.slot_idx,
                            recipe_slug=order.recipe_slug,
                            is_rush=order.is_rush,
                        )
            
            await asyncio.sleep(0.5)  # 扫描间隔
        except Exception as e:
            logger.error(f"Scan loop error: {e}")
            await asyncio.sleep(0.5)
```

**关键点**：
- 使用 `OrderScanner` 进行图像检测
- 只检测订单，其他状态通过程序逻辑维护
- 在动画窗口期暂停扫描，避免误判

### 决策循环 (_agent_loop)

**职责**：调用 Agent 进行决策，执行动作

**频率**：每 0.1 秒决策一次

```python
async def _agent_loop(self) -> None:
    """Agent 决策循环"""
    while self._running and not self.env.is_game_over():
        try:
            # 检查是否在动画窗口期
            if not self.env.is_in_animation_window():
                # 获取 Agent 决策
                action = self.agent.step()
                
                if action:
                    # 执行动作
                    await self._execute_action(action)
            
            await asyncio.sleep(0.1)  # 决策间隔
        except Exception as e:
            logger.error(f"Agent loop error: {e}")
            await asyncio.sleep(0.1)
```

**关键点**：
- 决策频率（0.1s）高于扫描频率（0.5s）
- 确保对状态变化的快速响应
- Agent 每次只返回一个动作

### 为什么采用双循环？

| 设计选择 | 原因 |
|----------|------|
| 扫描和决策分离 | 图像检测较慢（~100ms），不应阻塞决策 |
| 不同频率 | 扫描0.5s足够（订单变化慢），决策0.1s保证响应性 |
| 异步并发 | 避免 I/O 阻塞，最大化利用等待时间 |
| 动画窗口检查 | 两个循环都检查，双重保护防止冲突 |

---

## ⏱️ 时间推进机制

### 实时时间计算

GameEnvironment 使用 **系统时钟** 计算游戏时间，而非模拟 tick：

```python
@property
def time(self) -> float:
    """当前游戏时间（秒）"""
    if self._game_start_time is None:
        return 0.0
    return time.time() - self._game_start_time
```

### 游戏生命周期

```python
def start_game(self) -> None:
    """开始游戏计时"""
    self._game_start_time = time.time()
    logger.info("Game started!")

def is_game_over(self) -> bool:
    """游戏是否结束"""
    if self._game_start_time is None:
        return False
    return self.time >= self._game_duration  # 默认90秒
```

### 与模拟器 tick 的对比

| 方面 | 真实环境 (GameEnvironment) | 模拟器 (GameSimulator) |
|------|---------------------------|------------------------|
| 时间源 | `time.time()` 系统时钟 | `self._state.time` 模拟时间 |
| 推进方式 | 自动流逝 | 显式调用 `tick(dt)` |
| 精度 | 毫秒级 | 取决于 tick 间隔 |
| 确定性 | 非确定性（受系统影响） | 完全确定性 |
| 适用场景 | 真实游戏 | 测试和算法优化 |

### 为什么选择实时时间？

1. **简化设计**：不需要手动推进时间，系统自动处理
2. **真实同步**：与游戏实际时间保持同步
3. **减少错误**：避免 tick 间隔设置不当导致的时间跳跃
4. **自然超时**：订单超时、烹饪完成等事件自然触发

---

## 🛡️ 动画窗口保护机制

### 问题背景

送餐后游戏会播放 1.5 秒的动画（槽位前移），期间：
- 屏幕状态不稳定
- 操作可能导致冲突
- 订单检测可能误判

### 解决方案

```python
def is_in_animation_window(self) -> bool:
    """是否在动画窗口期间"""
    return time.time() < self._animation_until

def set_animation_window(self, duration: float = 1.5) -> None:
    """设置动画窗口"""
    self._animation_until = time.time() + duration
```

### 触发时机

```python
async def _execute_serve_order(self, action) -> None:
    """执行送餐"""
    await self.ui.serve_order(action.slot_idx)
    self.env.serve_order(action.slot_idx)  # 内部调用 set_animation_window()
```

### 保护范围

1. **扫描循环**：动画期间不检测新订单
2. **决策循环**：动画期间 Agent 不返回动作
3. **Agent 内部**：`_try_serve()` 首先检查动画窗口

```python
def _try_serve(self) -> Optional[ServeOrderAction]:
    # 首先检查动画窗口
    if self.env.is_in_animation_window():
        return None
    # ... 其他逻辑
```

---

## 🎯 状态追踪机制

### 核心设计原则

**只检测订单，其他状态通过程序逻辑维护**

| 状态类型 | 追踪方式 | 原因 |
|----------|----------|------|
| 订单 | 图像检测 | 订单内容变化不可预测 |
| 灶台 | 程序逻辑 | 状态变化由 Agent 控制 |
| 组装站 | 程序逻辑 | 状态变化由 Agent 控制 |
| 库存 | 程序逻辑 | 状态变化由 Agent 控制 |

### 灶台状态追踪

```python
@dataclass
class CookerState:
    """灶台状态"""
    busy: bool = False
    ingredient_name: Optional[str] = None
    cooker_type: Optional[str] = None
    started_at: Optional[float] = None
    done_at: Optional[float] = None
```

**状态更新时机**：
- 开始烹饪时：`env.start_cooking(ingredient, cooker, duration)`
- 移动食材时：`env.clear_cooker(cooker)` 或 `env.move_to_stockpile()`

### 组装站状态追踪

```python
@dataclass
class AssemblyState:
    """组装站状态"""
    ingredients: list[str] = field(default_factory=list)
    target_recipe_slug: Optional[str] = None
    owner_order_id: Optional[int] = None
```

**状态更新时机**：
- 添加食材时：`env.add_to_assembly(ingredient, cooker, order_id, recipe_slug)`
- 送餐时：`env.serve_order(slot_idx)` 内部清空组装站

### 库存状态追踪

```python
@dataclass
class StockpileSlot:
    """库存槽位"""
    ingredient_name: Optional[str] = None
    cooker_type: Optional[str] = None
    count: int = 0
```

**状态更新时机**：
- 存入时：`env.move_to_stockpile(cooker, slot)`
- 取出时：`env.pull_from_stockpile(slot)`

---

## 🔌 异步并发设计

### asyncio.gather() 的作用

```python
await asyncio.gather(
    self._scan_loop(),
    self._agent_loop(),
)
```

**效果**：
- 两个协程并发执行
- 任一协程异常会导致整体取消
- 最大化利用等待时间

### 锁机制

UIRunner 使用异步锁确保 UI 操作的原子性：

```python
class UIRunner:
    def __init__(self, ...):
        self._lock = asyncio.Lock()
    
    async def swipe(self, start, end, duration=0.1) -> None:
        async with self._lock:
            # 执行 swipe 操作
            await asyncio.to_thread(swipe, start, end, duration)
            await asyncio.sleep(0.05)  # 操作间隔
```

**作用**：
- 防止多个 swipe 操作同时执行
- 避免 UI 冲突和混乱

### 频率选择依据

| 循环 | 频率 | 依据 |
|------|------|------|
| 扫描循环 | 0.5s | 订单变化较慢，图像检测开销大 |
| 决策循环 | 0.1s | 需要快速响应状态变化 |
| UI操作间隔 | 0.05s | 游戏需要时间响应操作 |

### 异常处理

每个循环都有独立的异常处理，确保单点故障不影响整体：

```python
while self._running and not self.env.is_game_over():
    try:
        # 主要逻辑
        ...
    except Exception as e:
        logger.error(f"Loop error: {e}")
        await asyncio.sleep(0.5)  # 错误后等待再重试
```

---

## 📊 完整游戏流程

```
1. 初始化阶段
   ├── 创建 RealGameBridge
   ├── 初始化 GameEnvironment, OrderScanner, UIRunner
   └── 创建 CookingAgent 并注入 env

2. 等待游戏开始
   ├── OrderScanner.detect_timer() 循环检测
   ├── 检测到 timer 图标后等待 3 秒
   └── 调用 env.start_game() 开始计时

3. 游戏运行阶段（双循环并行）
   ├── 扫描循环 (0.5s)
   │   ├── 检查动画窗口
   │   ├── OrderScanner.scan_new_orders()
   │   └── GameEnvironment.add_order()
   │
   └── 决策循环 (0.1s)
       ├── 检查动画窗口
       ├── CookingAgent.step() → Action
       └── RealGameBridge._execute_action()
           ├── UI 操作 (UIRunner.swipe)
           └── 状态更新 (GameEnvironment)

4. 游戏结束
   ├── env.is_game_over() 返回 True
   ├── 双循环自动退出
   └── 返回统计结果
```
