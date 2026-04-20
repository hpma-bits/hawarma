# 订单同步与 Serve 验证方案

> 基于快速重试和多点 snapshot 的新方案

---

## 1. 背景与问题

### 1.1 当前问题

1. **serve 失败后扫描**：在动画窗口期间 scan 会捕获旧画面
2. **assembly 验证的时效性**：serve 成功后截图可能显示非空

### 1.2 新方案核心思路

- **不用扫描来匹配订单**：用快速重试机制取代
- **多点 snapshot 验证**：连续获取多张截图，确保验证准确

---

## 2. Scan 触发场景分析

### 2.1 两种场景

| 场景 | 触发时机 | 是否检查动画窗口 |
|------|---------|-----------------|
| **_scan_loop** | 每 0.4-0.5s | **是**（动画期间暂停） |
| **serve 失败后重试** | verify 失败后 | **否**（当前问题所在） |

### 2.2 问题

serve 失败后重试前调用 `_find_matching_order_slot()` 直接 scan，不检查 `is_in_animation_window()`，可能在动画期间捕获旧画面。

---

## 3. 新方案：快速重试机制

### 3.1 核心思路

**不依赖 scan 匹配订单**，而是直接依次尝试可能的所有 slot。

### 3.2 算法

```
serve_failed:
1. 依次尝试 serve slot 0, 1, 2, 3（连续快速）
2. 如果全部失败 → 清空 assembly，丢弃食材
3. 如果某个成功 → 更新对应 slot，停止尝试
```

### 3.3 为什么这样可行？

假设 assembly 有 `[clearwater_fish, creamfield_rice]`（Risotto）：

```
原始目标 slot 2 失败后：
1. serve 0 → 如果 slot 0 是 Risotto，成功！
2. serve 1 → 如果 slot 1 是 Risotto，成功！
3. serve 2 → 如果 slot 2 是 Risotto，成功！（但之前失败了）
4. serve 3 → 如果 slot 3 是 Risotto，成功！
```

**关键洞察**：只要订单还在，总有一个 slot 能匹配成功。

### 3.4 优点

1. **无需 scan**：避免动画窗口期间的旧画面问题
2. **主动确认**：通过实际提交来确定正确的 slot
3. **简单可靠**：不依赖状态推理

---

## 4. Assembly 验证新方案

### 4.1 当前问题

serve 成功后，截图可能显示 assembly 非空（时效性问题），导致误判。

### 4.2 新方案：多点 Snapshot

```
当前流程：
serve swipe → sleep → verify empty？

问题：sleep 时间内截图可能过时

新流程：
serve swipe → 连续获取 3 张 snapshot → 第 4 张 verify
```

### 4.3 算法

```python
async def _verify_serve_success(self) -> bool:
    """多点 snapshot 验证"""
    # 获取 4 张 snapshot，间隔极短
    snapshots = []
    for _ in range(4):
        snapshots.append(self.ui.capture_screen())
        await asyncio.sleep(0.05)  # 极短间隔

    # 用第 4 张进行 verify
    return self.verifier.is_assembly_empty(snapshots[3])
```

---

## 5. 完整流程

### 5.1 _serve_with_verify 新流程

```python
async def _serve_with_verify(self, slot_idx: int, max_retries: int = 2) -> bool:
    for attempt in range(max_retries + 1):
        await self.ui.serve_order(slot_idx)

        # 多点 snapshot 验证
        if await self._verify_serve_success():
            if attempt > 0:
                logger.info(f"Serve succeeded on retry {attempt}")
            return True

        logger.warning(f"Serve verification failed (attempt {attempt + 1})")

        if attempt < max_retries:
            # 快速重试：依次尝试所有 slot
            for try_slot in range(4):
                if try_slot == slot_idx:
                    continue  # 已经试过了
                await self.ui.serve_order(try_slot)
                if await self._verify_serve_success():
                    logger.info(f"Found matching order at slot {try_slot}")
                    slot_idx = try_slot
                    return True

    # 全部失败，清空 assembly
    await self.ui.clear_assembly()
    self.env.clear_assembly()
    return False
```

### 5.2 移除 _find_matching_order_slot

新方案下不再需要 `_find_matching_order_slot()`，可以移除。

---

## 6. 关键约束

1. **动画窗口期间不 scan**：_scan_loop 已有约束
2. **serve 验证用多点 snapshot**：避免单次截图的时效性问题
3. **快速重试取代扫描匹配**：主动尝试取代被动推理

---

## 7. 已实现

### 7.1 快速重试机制

- `_serve_with_verify` 返回 `int | None`（成功的 slot 或 None）
- 失败后依次尝试 slot 0,1,2,3（间隔 0.05s）
- 全部失败后清空 assembly

### 7.2 多点 Snapshot 验证

- `_verify_with_multi_snapshot` 连续等待 3 次 0.05s
- 用最后的截图验证 assembly 是否为空

### 7.3 移除 `_find_matching_order_slot`

- 不再需要扫描匹配订单
- 快速重试取代被动推理
