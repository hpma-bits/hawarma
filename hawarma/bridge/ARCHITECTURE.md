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
- **CookerState 字段**: `busy`, `ingredient_name`, `cooker_type`, `started_at`, `done_at`, `expired_at`
- **CookerState 方法**: `reset()`, `is_done(current_time)`, `is_expired(current_time)`

### `environment.py`
- **地位**: 真实游戏环境
- **状态**: ✅ 完成
- **功能**:
  - 继承 BaseEnvironment，实现统一接口
  - 追踪灶台状态（通过程序逻辑，含过期时间管理）
  - 追踪组装站状态（含配方校验）
  - 追踪库存状态
  - 追踪订单状态
  - 管理游戏时间
  - **食材过期强制阻止**：`move_to_assembly` / `move_to_stockpile` 拒绝过期食材
  - **组装站配方校验**：`add_to_assembly` / `add_condiment` 校验食材和调料是否属于目标配方
- **输入**: UI操作结果、订单检测结果、配方字典
- **输出**: 游戏状态供Agent决策
- **关键类**: `GameEnvironment`

### `scanner.py`
- **地位**: 订单扫描器
- **状态**: ✅ 完成（异步化 snapshot）
- **功能**:
  - 检测屏幕上的订单
  - 识别配方和加急状态
  - 检测游戏开始（timer图标）
  - **异步截图**：`detect_timer()`, `scan_orders()`, `scan_new_orders()` 均为 async 方法，使用 `asyncio.to_thread()` 避免阻塞事件循环
- **输入**: 屏幕截图、配置对象
- **输出**: 检测到的订单信息
- **关键类**: `OrderScanner`, `DetectedOrder`

### `assembly_verifier.py`
- **地位**: 组装站提交验证器（可插拔组件）
- **状态**: ✅ 新增
- **功能**:
  - 通过模板匹配检测组装站区域是否为空
  - 验证送餐操作是否成功提交菜品
  - ROI: `(1150, 720, 1600, 1030)`
  - 模板: `static/img/empty_assembly.jpg`
- **输入**: 配置对象
- **输出**: 验证结果（成功/失败）
- **关键类**: `AssemblyVerifier`
- **关键方法**: `is_assembly_empty()` — 返回 True 表示提交成功

### `ui_runner.py`
- **地位**: UI操作执行器
- **状态**: ✅ 完成
- **功能**:
  - 封装所有swipe操作
  - 从config.yaml读取坐标配置
  - 提供异步执行接口
  - **动态坐标映射**：根据菜谱选择顺序确定元素位置
  - 使用 Airtest 内置的 minitouch 触摸方法
  - **垃圾桶坐标配置化**：`clear_cooker()` 和 `clear_assembly()` 使用 `config.screen.trash_position`
  - **clear_assembly 增强**：使用 `duration=0.4, steps=8` 确保拖拽动作被游戏识别
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
- **状态**: ✅ 完成（含停滞检测集成 + 异步扫描）
- **功能**:
  - 协调Agent、环境、扫描器和UI执行器
  - 管理游戏生命周期
  - 运行扫描和决策循环
  - 执行Agent动作
  - **停滞检测集成**：`_agent_loop()` 使用 `step_with_diagnostics()` 替代 `step()`
  - **异步扫描**：`_sync_orders_from_scan()` 为 async 方法，await scanner 的异步截图
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
    ↓
AssemblyVerifier.is_assembly_empty() (仅送餐后)
```

### 送餐验证流程

`_exec_serve_order()` 使用 `_serve_with_verify()` 执行带验证的送餐：

```
1. 执行 UI 送餐操作
2. 等待 0.5s（动画窗口）
3. AssemblyVerifier.is_assembly_empty() 验证
   ├── 为空 → 成功 → env.serve_order() 更新状态
   └── 不为空 → 警告 → 重新扫描订单找匹配槽位
       ├── 找到匹配槽位 → 重试送餐（最多 2 次重试）
       └── 无匹配 → 重试原槽位
           └── 全部失败 → 清理组装站，继续游戏
```

**设计原则**：
- `env.serve_order()` 只在验证成功后调用，保证环境状态一致性
- 最多重试 2 次，避免无限循环
- 重试时重新扫描订单，处理订单槽位偏移问题
- 最终失败时清理组装站，防止卡死

## 与模拟器的区别

| 方面 | 模拟器 (GameSimulator) | 真实环境 (GameEnvironment) |
|------|------------------------|---------------------------|
| 状态追踪 | 内置状态机 | 程序逻辑追踪 |
| 时间推进 | tick()方法 | 真实时间 |
| 操作执行 | 符号操作 | UI swipe操作 |
| 订单生成 | 随机生成 | 屏幕检测 |
| 食材过期 | expired_at 字段，强制阻止 | expired_at 字段，move_to_assembly/stockpile 拒绝过期 |
| 配方校验 | 模拟器内部校验 | add_to_assembly/add_condiment 校验目标配方 |
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

**频率**：自适应（0.5s ~ 2.0s）

```python
async def _scan_loop(self) -> None:
    """订单扫描循环（自适应频率）"""
    while self._running and not self.env.is_game_over():
        try:
            if not self.env.is_in_animation_window():
                await self._sync_orders_from_scan()
            interval = self._compute_scan_interval()
            await asyncio.sleep(interval)
        except Exception as e:
            logger.error(f"Scan loop error: {e}")
            await asyncio.sleep(1.0)
```

**自适应频率策略**：

| 游戏状态 | 扫描间隔 | 原因 |
|----------|----------|------|
| 有灶台空闲 + 有活跃订单 | 0.5s | 快速发现新订单，立即启动烹饪 |
| 所有灶台都在忙 | 2.0s | 等烹饪完成再处理，减少不必要的扫描 |
| 无活跃订单 | 1.0s | 中速等待新订单出现 |

**关键点**：
- 使用 `OrderScanner` 进行图像检测
- 只检测订单，其他状态通过程序逻辑维护
- 在动画窗口期暂停扫描，避免误判
- **`_sync_orders_from_scan()` 是 async 方法**，内部 `await self.scanner.scan_new_orders()`
- **`G.DEVICE.snapshot()` 通过 `asyncio.to_thread()` 异步执行**，不阻塞 agent_loop
- **扫描不会重叠**：每次扫描完成后才计算间隔并 sleep，确保同一时间只有一个扫描在进行

### 决策循环 (_agent_loop)

**职责**：调用 Agent 进行决策，执行动作，检测停滞状态

**频率**：每 0.05 秒决策一次

```python
async def _agent_loop(self) -> None:
    """Agent 决策循环（每 0.05s），带停滞检测"""
    while self._running and not self.env.is_game_over():
        try:
            action = self.agent.step_with_diagnostics()
            if action:
                self.agent.stats["actions_taken"] += 1
                await self._execute_action(action)
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Agent loop error: {e}")
            await asyncio.sleep(0.05)
```

**关键点**：
- 使用 `step_with_diagnostics()` 替代 `step()`，启用自动停滞检测
- 连续 5 秒无行动时输出 WARNING 级别诊断日志，包含组装站状态、订单列表、停滞原因
- 连续 10 秒无行动时再次输出诊断（仅输出一次，避免日志洪水）

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
    expired_at: Optional[float] = None

    def is_done(self, current_time: float) -> bool:
        return self.done_at is not None and current_time >= self.done_at

    def is_expired(self, current_time: float) -> bool:
        return self.expired_at is not None and current_time >= self.expired_at
```

**状态更新时机**：
- 开始烹饪时：`env.start_cooking(ingredient, cooker, duration)` → 设置 `done_at` 和 `expired_at`
- 移动食材时：`env.move_to_assembly(cooker)` → 过期食材被拒绝，返回 False
- 存入库存时：`env.move_to_stockpile(cooker, slot)` → 过期食材被拒绝，返回 False
- 清理灶台时：`env.clear_cooker(cooker)` → 重置所有字段

### 组装站状态追踪

```python
@dataclass
class AssemblyState:
    """组装站状态"""
    ingredients: list[str] = field(default_factory=list)
    target_recipe_slug: Optional[str] = None
    owner_order_id: Optional[int] = None
    condiments: dict[str, int] = field(default_factory=dict)
```

**状态更新时机**：
- 添加食材时：`env.add_to_assembly(ingredient, cooker, order_id, recipe_slug)`
- 从库存取用时：`env.pull_from_stockpile(slot)` — 若组装站为空，自动推断 `target_recipe_slug`
- 送餐时：`env.serve_order(slot_idx)` 内部清空组装站

**⚠️ target_recipe_slug 完整性保证**（2026-04-05 修复）：

`target_recipe_slug` 是组装站的"灵魂"字段，缺失会导致 Agent 决策链完全瘫痪（参见 `docs/assembly_deadlock_analysis.md`）。以下方法会自动推断配方：

| 方法 | 推断时机 | 推断依据 |
|------|----------|----------|
| `pull_from_stockpile()` | 组装站为空时拉取食材 | 单食材匹配活跃订单 |
| `add_to_assembly()` | 组装站有食材但无目标时 | 多食材集合匹配活跃订单 |
| `add_to_assembly()` | 组装站为空且无 order_id/recipe_slug | 单食材匹配活跃订单 |

推断方法：
- `_infer_recipe_slug_from_ingredient(ingredient)` — 单食材匹配第一个活跃订单
- `_infer_recipe_slug_from_ingredients(ingredients)` — 多食材集合匹配活跃订单

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
