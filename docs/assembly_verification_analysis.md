# Assembly 空检测机制分析

## 1. 当前机制概览

检测 assembly 是否为空的逻辑分布在多个位置：

### 1.1 真实游戏环境（GameEnvironment）

| 位置 | 方法 | 检测方式 | 用途 |
|------|------|---------|------|
| `assembly_verifier.py` | `is_assembly_empty()` | **图像模板匹配** | 验证送餐是否成功 |
| `environment.py` | `clear_assembly()` | **环境状态** | 清理 assembly |
| `base_environment.py` | `AssemblyState.is_free` | **环境状态** | 判断 assembly 是否空闲 |

### 1.2 执行流程

```
Bridge._serve_with_verify()
    │
    ├─ 1. 执行 ui.serve_order()        → 发送送餐swipe
    ├─ 2. 等待 0.1s             → 等待动画
    ├─ 3. verifier.is_assembly_empty() → 图像检测 ← 关键！
    ├─ 4. 如果失败 → 重试或清理
    └─ 5. env.serve_order()         → 更新环境状态
```

---

## 2. 问题分析

### 2.1 检测机制对比

| 检测方式 | 优点 | 缺点 |
|---------|------|------|
| **图像检测** (`AssemblyVerifier`) | 反映真实游戏状态 | 需要截图，耗时；可能有误判 |
| **环境状态** (`env.assembly.ingredients`) | 快速、准确 | 需要信任操作成功 |

### 2.2 当前逻辑问题

#### 问题1：检测位置单一
当前只在 **送餐后** 检测 assembly 是否为空，无法在 **送餐前** 验证放置是否正确。

#### 问题2：图像检测的不确定性
- 模板匹配阈值 0.7 可能产生误判
- 截图耗时（30-50ms）
- 环境光线变化影响准确率

#### 问题3：状态不同步
- `verifier.is_assembly_empty()` 检测图像区域
- `env.assembly.ingredients` 检测环境状态
- 两者可能不一致

### 2.3 理想流程 vs 实际流程

**理想流程**：
```
1. move_to_assembly()
2. 验证放置是否成功 ← 缺失
3. serve_order()
4. 验证送餐是否成功
```

**实际流程**：
```
1. move_to_assembly()
2. serve_order()
3. 验证 assembly 为空 → 送餐后检测
```

---

## 3. 代码位置汇总

### 3.1 图像检测

```python
# hawarma/bridge/assembly_verifier.py:49
def is_assembly_empty(self) -> bool:
    """
    检测组装站区域是否为空
    
    Returns:
        True 如果区域为空（提交成功），False 如果区域不为空（提交失败）
    """
    if self._empty_template is None:
        return True  # 没有模板时默认空
    
    screen = G.DEVICE.snapshot()  # 截图
    cropped = crop_image(screen, self.assembly_region)  # 裁剪
    match = self._empty_template._cv_match(cropped)  # 模板匹配
    return match is not None
```

### 3.2 环境状态检测

```python
# hawarma/bridge/base_environment.py:62
@property
def is_free(self) -> bool:
    """组装站是否空闲"""
    return len(self.ingredients) == 0 and self.target_recipe_slug is None
```

### 3.3 送餐执行流程

```python
# hawarma/bridge/bridge.py:330
async def _exec_serve_order(self, action) -> None:
    """送餐（带验证和重试）"""
    served = await self._serve_with_verify(action.slot_idx, max_retries=2)
    
    if served:
        # 验证成功后更新环境状态
        order = self.env.orders[action.slot_idx]
        if order:
            self.agent.on_order_served()
        self.env.serve_order(action.slot_idx)
    else:
        # 验证失败后清理
        await self.ui.clear_assembly()
        self.env.clear_assembly()
```

### 3.4 送餐验证核心逻辑

```python
# hawarma/bridge/bridge.py:356
async def _serve_with_verify(self, slot_idx: int, max_retries: int = 2) -> bool:
    """
    执行送餐并验证是否成功。
    
    流程：
    1. 执行 UI 送餐操作
    2. 等待动画窗口结束
    3. 验证组装站是否为空
    4. 如果为空 → 成功
    5. 如果不为空 → 重新扫描订单，找到匹配的槽位重试
    6. 重试 max_retries 次后仍失败 → 返回 False
    """
    for attempt in range(max_retries + 1):
        await self.ui.serve_order(slot_idx)
        await asyncio.sleep(0.1)
        
        # 核心：图像检测
        if self.verifier.is_assembly_empty():
            return True
        
        # 失败后重试
        if attempt < max_retries:
            matching_slot = await self._find_matching_order_slot()
            if matching_slot is not None:
                slot_idx = matching_slot
    
    return False
```

---

## 4. 潜在问题

### 4.1 误判情况

1. **模板匹配失败**：食材残留但匹配到空模板
2. **状态不同步**：图像显示有食材，但 env 状态已清空
3. **时序问题**：截图时动画尚未结束

### 4.2 漏检情况

1. **检测失败**：assembly 有食材但未被检测到
2. **重试无效**：重新扫描后仍无法找到匹配订单

### 4.3 当前重试逻辑

```python
# hawarma/bridge/bridge.py:390
async def _find_matching_order_slot(self) -> int | None:
    """
    重新扫描订单，找到与组装站食材匹配的槽位。
    
    匹配规则：assembly 食材必须完全等于订单的 raw_ingredients
    排序：优先选择最早超时的订单
    """
    scanned = await self.scanner.scan_new_orders()
    assembly = self.env.assembly
    assembly_names = [ing[0] if isinstance(ing, tuple) else ing for ing in assembly.ingredients]
    
    matches = []
    for detected in scanned:
        recipe = self._recipe_by_slug.get(detected.recipe_slug)
        if recipe:
            raw_ings = getattr(recipe, 'raw_ingredients', [])
            if sorted(assembly_names) == sorted(raw_ings):
                matches.append((detected.slot_idx, detected.timeout_at))
    
    if not matches:
        return None
    
    # 按 timeout_at 排序，优先最早超时
    matches.sort(key=lambda x: x[1])
    return matches[0][0]
```

---

## 5. 改进建议

### 5.1 方案A：增加 move_to_assembly 验证

在第一个食材移动后检测灶台是否清空：
```python
async def _exec_move_to_assembly(self, action) -> None:
    await self.ui.move_to_assembly(action.cooker)
    
    # 验证灶台是否清空（移动成功则灶台应为空）
    if not self._verify_cooker_empty(action.cooker):
        await asyncio.sleep(0.2)
        await self.ui.move_to_assembly(action.cooker)
    
    # 更新环境状态
    ...
```

### 方案B：双检测机制

- 主要：图像检测（`verifier.is_assembly_empty()`）
- 备用：环境状态检测（`env.assembly.is_free`）

### 方案C：增强重试逻辑

- 增加重试次数
- 增加等待时间
- 添加更详细的日志

---

## 6. 问题：送餐失败但仍移动食材

### 6.1 问题描述

Agent 决策送餐后，执行前 slot 变化导致送餐失败，但 assembly 仍有食材残留。

### 6.2 根因分析

```
Timeline:
┌────────────────────────────────────────────────────────────────────────┐
│  Thread 1 (Agent 决策)                                           │
│  T=15.0  agent.step() → returns ServeOrderAction(slot_idx=0)      │
│                    ↓                                          │
│                    ↓  等待执行...                              │
│                    ↓                                          │
│  Thread 2 (Bridge 执行)                                         │
│  T=15.1  ui.serve_order(slot_idx=0)  ← 此时 slot 0 可能已变！        │
│                    ↓                                          │
│  T=15.2  verifier.is_assembly_empty() → False              │
│                    ↓                                          │
│  T=15.3  clear_assembly() → 失败后清理                       │
└────────────────────────────────────────────────────────────────────────┘
```

**关键问题**：
1. **决策与执行时间不同步**
   - Agent 决策（`step()`）：在独立线程，每 0.05s 一次
   - 动作执行：在主线程，串行执行
   - 时间差：可能有 0.05-0.5s

2. **slot_idx 过时**
   - Agent 选择 `slot_idx=0` 时，假设 order 在 slot 0
   - 但执行时可能已被新 order 替代
   - 原因：`shift_orders_left()` 会改变槽位顺序

3. **TOCTTOU 问题**
   - Time-Of-Check-To-Time-Of-Use
   - Agent 检查 order 在 slot 0
   - 执行时 order 已不在 slot 0

### 6.3 代码证据

```python
# bridge.py:233
async def _agent_loop(self) -> None:
    while self._running:
        if self.env.is_in_animation_window() or self._executing_action:
            await asyncio.sleep(0.05)
            continue
        
        action = await asyncio.to_thread(self.agent.step_with_diagnostics)  # 决策
        if action:
            await self._execute_action(action)  # 执行（可能延迟）

# bridge.py:330
async def _exec_serve_order(self, action) -> None:
    served = await self._serve_with_verify(action.slot_idx, max_retries=2)
    # 注意：使用 action.slot_idx，但这个值是决策时的快照
    
    if served:
        self.env.serve_order(action.slot_idx)
    else:
        self.ui.clear_assembly()  # 失败也清理
        self.env.clear_assembly()
```

### 6.4 场景分析

| 场景 | 原因 | 影响 |
|------|------|------|
| A. 送餐失败 | slot_idx 过时 | assembly 清空但无食材送往正确订单 |
| B. 订单变化 | 新订单出现替换原订单 | 食材不匹配新订单 |
| C. 库存移动 | serve 失败后继续移动 | 食材未及时清理 |
| D. 状态不同步 | env 与 UI 不同步 | 食材残留 |

### 6.5 改进建议

#### 方案A：基于扫描的动态送餐

在送餐执行前重新扫描，找到匹配订单：

```python
async def _exec_serve_order(self, action) -> None:
    # 执行前先扫描
    matching_slot = await self._find_matching_order_slot()
    
    if matching_slot is None:
        # 没有匹配，清空 assembly
        await self.ui.clear_assembly()
        self.env.clear_assembly()
        return
    
    served = await self._serve_with_verify(matching_slot, max_retries=2)
    ...
```

#### 方案B：动态 slot 选择

在 `_try_serve()` 中返回不含 slot_idx 的动作，执行时动态选择：

```python
@dataclass
class ServeOrderAction(Action):
    # 不指定 slot_idx
    pass

async def _exec_serve_order(self, action) -> None:
    matching_slot = await self._find_matching_order_slot()
    if matching_slot is None:
        matching_slot = 0  # 默认第一个
    served = await self._serve_with_verify(matching_slot, max_retries=2)
    ...
```

#### 方案C：增强重试逻辑

在 `_find_matching_order_slot()` 中使用当前 env 状态而非 scanned：

```python
async def _find_matching_order_slot(self) -> int | None:
    # 直接使用当前 env 状态找到匹配
    assembly = self.env.assembly
    for slot_idx, order in enumerate(self.env.orders):
        if order and not order.done:
            if self._ingredients_match(assembly.ingredients, order.recipe):
                return slot_idx
    return None
```

---

## 7. Swipe 操作优化分析

### 7.1 问题假设

用户反馈：serve 操作失败的主要原因是 **swipe 操作完成度不高**，表现为滑动不到位。

可能原因：
1. **设备卡顿**：Android 设备性能不足
2. **Maxtouch 延迟**：命令发送与执行的时间差
3. **终点停留不足**：滑动到终点后立即抬起，未等待稳定

### 7.2 当前参数

| 操作 | 当前 duration | 当前 steps |
|------|--------------|------------|
| move_to_assembly | 0.1s | 5 |
| move_to_stockpile | 0.1s | 5 |
| pull_from_stockpile | 0.1s | 5 |
| add_condiment | 0.1s | 5 |
| serve_order (<400) | 0.25s | 12 |
| serve_order (400-600) | 0.3s | 15 |
| serve_order (600-800) | 0.35s | 18 |
| serve_order (>=800) | 0.4s | 20 |
| clear_cooker | 0.4s | 16 |
| clear_assembly | 0.4s | 16 |

### 7.3 优化方案

#### 方案A：增加终点停留时间

在 swipe 完成后增加等待时间，确保操作稳定：

```python
# ui_runner.py
async def swipe(self, start, end, duration=0.1, steps=5) -> None:
    logger.debug(f"Swipe: {start} -> {end} duration={duration}s steps={steps}")
    from airtest.core.api import swipe
    swipe(start, end, duration=duration, steps=steps)
    await asyncio.sleep(0.05)  # 增加：终点停留等待
```

#### 方案B：优化 steps 数量

steps 影响滑动路径的平滑度：
- 过多 steps：可能导致滑动过慢
- 过少 steps：可能导致滑动不均匀

```python
def _calculate_swipe_params(self, distance):
    # 增加 steps 数量以提高完成度
    if distance < 400:
        return 0.25, 20  # 增加 steps
    elif distance < 600:
        return 0.3, 25
    ...
```

#### 方案C：分段滑动

对于长距离移动，分段滑动确保到位：

```python
async def swipe分段(self, start, end, duration=0.2, steps=10):
    """分段滑动，确保到位"""
    mid_x = (start[0] + end[0]) // 2
    mid_y = (start[1] + end[1]) // 2
    mid = (mid_x, mid_y)
    
    swipe(start, mid, duration=duration/2, steps=steps//2)
    await asyncio.sleep(0.05)
    swipe(mid, end, duration=duration/2, steps=steps//2)
    await asyncio.sleep(0.05)
```

### 7.4 待验证

1. 当前参数是否需要调整？
2. 是否需要增加终点停留时间？
3. 建议的参数调整值？

---

## 8. 待确认

1. 图像检测的准确率是否满足要求？
2. 是否需要增加 move_to_assembly 验证？
3. Swipe 优化方案是否合理？