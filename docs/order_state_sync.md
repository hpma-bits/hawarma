# 订单状态同步机制

> 记录真实游戏中订单状态的检测、更新机制，对比代码实现与游戏规则

---

## 1. 当前代码实现

### 1.1 订单检测流程

```
OrderScanner.scan_new_orders()  (hawarma/bridge/scanner.py)
    ↓
检测 4 个 slot 位置的食材图标
    ↓
检测 rush 状态（红色像素判断）
    ↓
返回 DetectedOrder 列表
```

### 1.2 订单同步流程

```
bridge._sync_orders_from_scan()  (hawarma/bridge/bridge.py:147-197)
    ↓
扫描当前屏幕订单
    ↓
按 slot 位置匹配：env_order[slot] == scanned[slot]?
    ↓
如果不匹配：
    - 如果 recipe 在其他 slot 存在 → 左移，标记为已匹配
    - 如果不存在 → 新订单，调用 env.add_order()
```

### 1.3 环境状态更新

```
env.add_order(recipe_slug, is_rush)  (hawarma/bridge/environment.py:325-352)
    ↓
找到最左空 slot
    ↓
创建 OrderInfo(order_id, recipe_slug, is_rush, created_at, timeout_at)
    ↓
timeout: rush=40s, normal=70s
```

### 1.4 扫描频率

```
bridge._compute_scan_interval()  (hawarma/bridge/bridge.py:130-145)
    ↓
有灶台空闲 + 有活跃订单 → 0.4s
所有灶台都在忙 → 0.5s
无活跃订单 → 0.5s
```

---

## 2. 游戏规则_vs_代码实现对比

### 2.1 订单生成时机

| 游戏规则 | 代码实现 | 状态 |
|---------|----------|------|
| 每隔 4 秒自动刷新 | 自适应扫描 0.4-0.5s | ⚠️ 不精确 |
| 提交后如果没有订单，立即刷新 | 等待下次扫描 (max 0.5s) | ⚠️ 延迟 |
| 新订单有 1 秒动画时间 | 无 | ❌ 未实现 |
| 订单超时后重置 4 秒计时器 | check_and_remove_timed_out_orders() | ✅ 已实现 |

### 2.2 槽位位移

| 游戏规则 | 代码实现 | 状态 |
|---------|--------|------|
| 提交后 slot 左移填补空位 | `_shift_orders_left()` | ✅ 已实现 |
| 位移需要 1.5 秒动画 | animation_window 检查 | ✅ 已实现 |
| 状态立即更新（非动画后） | 提交后立即更新 | ✅ 已实现 |

### 2.3 Rush 检测

| 游戏规则 | 代码实现 | 状态 |
|---------|--------|------|
| 红色背景识别 | 像素红色值 < 阈值 | ✅ 已实现 |

---

## 3. 发现的问题

### 3.1 缺少："提交后立即刷新"机制

**问题**：游戏规则说"如果场上有 4 个订单，提交了 1 个后剩下 3 个，则**从提交时刻开始计时，4 秒后刷新新订单**"

**当前代码**：固定扫描周期 0.4-0.5s，可能错过最佳刷新时机

**影响**：
- 提交后可能延迟最多 0.5s 才检测到"需要刷新"
- 不是精确的 4 秒周期

### 3.2 缺少：新订单动画时间

**问题**：游戏规则说"新出现的订单有 **1 秒动画时间**，动画结束后（1秒后）玩家才能检测到该订单"

**当前代码**：扫描结果立即使用，没有考虑动画延迟

**影响**：新订单可能在动画期间被误检测或不检测

### 3.3 扫描频率 vs 4 秒规则

**当前实现**：自适应 0.4-0.5s 扫描

**游戏规则**：精确的 4 秒间隔 + 立即刷新

**影响**：代码比游戏规则更频繁，但不是精确的 4s 周期

---

## 4. 建议的优化

### 4.1 添加精确的 4 秒刷新计时器

```python
class GameEnvironment:
    def __init__(self, ...):
        self._last_order_time = 0.0  # 上次订单生成时间
        self._order_interval = 4.0    # 订单间隔
    
    def should_spawn_order(self) -> bool:
        """检查是否应该生成新订单"""
        # 情况1：没有订单，立即
        if not any(self._orders):
            return True
        # 情况2：距离上次生成 >= 4s
        if time.time() - self._last_order_time >= self._order_interval:
            return True
        return False
```

### 4.2 添加新订单动画延迟

```python
class RealGameBridge:
    def _sync_orders_from_scan(self) -> None:
        # 检测到新订单后，等待 1 秒动画再添加到 env
        await asyncio.sleep(1.0)  # 新订单动画时间
        self.env.add_order(...)
```

### 4.3 提交后立即扫描

```python
async def _serve_with_verify(self, ...) -> bool:
    result = await self.ui.serve_order(...)
    if result:
        self.env.serve_order(...)
        # 提交后立即触发一次扫描
        await self._sync_orders_from_scan()
        return True
```

---

## 5. 关键文件

| 文件 | 功能 |
|------|------|
| `hawarma/bridge/scanner.py` | 订单检测（图像识别） |
| `hawarma/bridge/environment.py` | 订单状态管理 |
| `hawarma/bridge/bridge.py` | 同步逻辑（_sync_orders_from_scan） |

---

## 6. 优化：动画窗口期间允许烹饪（2026-04-19）

### 问题分析

从日志分析 serve 后阻塞：
```
t=51.5s: serve完成 (animation_window=1.5s 开始)
t=51.2s: 扫描
t=53.4s: 开始烹饪  ← 延迟 ~2s (1.5s动画 + 扫描/决策延迟)
```

**根因**：之前 agent_loop 在 animation_window 期间完全跳过，包括烹饪决策。

### 优化方案

bridge.py `_agent_loop()` 修改：
```python
action = await asyncio.to_thread(self.agent.step_with_diagnostics)
if action:
    action_type = type(action).__name__
    if in_animation and action_type == "ServeOrderAction":
        await asyncio.sleep(0.05)
        continue  # 跳过送餐，烹饪/移动正常执行
```

**效果**：动画期间允许烹饪，只禁止送餐

---

## 7. 待确认问题（已回答）

1. **4秒间隔**：游戏规则说是个平均值，不需要精确 ❌
2. **新订单动画**：暂时不需要 ❌
3. **提交后立即刷新**：等待是合理的 ❌
4. **serve后阻塞**：✅ 已优化（动画期间允许烹饪）