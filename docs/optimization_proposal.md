# Agent 优化方案

> 供审阅，批准后实施

---

## 已完成 ✅

### 1. 送餐成功率优化 ✅
- **修改位置**: `hawarma/bridge/ui_runner.py`
- **方案**: 根据距离动态计算 swipe 参数
  - 距离 < 400: `duration=0.25s, steps=12`
  - 距离 400-600: `duration=0.3s, steps=15`
  - 距离 600-800: `duration=0.35s, steps=18`
  - 距离 >= 800: `duration=0.4s, steps=20`

### 2. 前瞻性烹饪策略 ✅
- **修改位置**: `hawarma/agent/agent.py`
- **核心思路**: 引入"预烹饪"机制，基于订单时间紧迫度提前开始烹饪
- **新增方法**:
  - `_get_urgent_ingredients()` - 获取紧迫食材列表
  - `_get_time_until_needed()` - 计算食材紧迫度
  - `_has_cooked_ingredient()` - 检查灶台是否有已完成食材

### 3. 扫描日志优化 ✅
- **修改位置**: `hawarma/bridge/bridge.py`
- 记录每次扫描的检测数量、新订单数量、耗时

### 4. 清理无用日志 ✅
- 删除 `Using device touch` 日志

---

## 新问题（调整后）

### 问题1：Serve 失败后的处理（已完成 ✅）
- **已实现**: 首次失败后重新扫描订单，尝试匹配后重试；无匹配则丢弃

### 问题2：食材超时防护（已完成 ✅）
- **已实现**: WARN_THRESHOLD=4s，提前存入库存，优先增加同槽位数量

---

## 方案三：Serve 失败后重试策略 ✅（已实现）

### 当前流程
```
1. serve_order()
2. 验证 assembly 为空
3. 失败重试 max_retries 次
4. 仍失败 → 丢弃到 trash bin
```

### 期望流程
```
1. serve_order()
2. 验证 assembly 为空
3. 失败 → 重新扫描订单，找到匹配的订单（最早超时）
4. 如果找到匹配 → 重试提交到该订单
5. 如果没有匹配 → 丢弃到 trash bin
```

### 关键设计

#### 3.1 匹配逻辑
- assembly 食材必须完全匹配订单的 raw_ingredients
- 如果有多个匹配，按 timeout_at 排序，优先选择最早超时的订单

#### 3.2 重试次数
- 保持 max_retries=2 不变
- 重试时使用新的匹配 slot_idx

#### 3.3 代码修改位置
- `hawarma/bridge/bridge.py` 的 `_serve_with_verify()` 方法

#### 3.4 丢弃时机
- 所有重试都失败后，且没有找到匹配订单时

---

## 方案四：食材超时防护机制 ✅（已实现）

### 问题分析
- 当前灶台超时逻辑：完成烹饪后 5 秒未取走 → 标记过期
- 真实环境：操作可能有阻塞，导致时间累积
- 需要在灶台食材接近超时前主动存入 stockpile

### 实现思路

#### 4.1 提前存入库存
在 `_try_store_to_stockpile()` 中增加更激进的判断：

```python
def _try_store_to_stockpile(self) -> Optional[MoveToStockpileAction]:
    """
    将灶台完成的多余食材存入库存（增强版）
    """
    # 降低超时阈值：从 5s 改为 3s
    EXPIRED_THRESHOLD = 3.0

    # 增加：提前存入判断
    WARN_THRESHOLD = 4.0  # 接近超时前 1s 存入

    for cooker_name, cooker in self.env.cookers.items():
        if not cooker.busy or cooker.done_at is None:
            continue

        time_since_done = self.env.time - cooker.done_at
        if time_since_done < 0:
            continue

        # 如果接近超时，立即存入
        if time_since_done > WARN_THRESHOLD:
            slot = self._find_available_slot(
                cooker.ingredient_name, cooker.cooker_type
            )
            if slot:
                return MoveToStockpileAction(cooker=cooker_name, slot=slot)

        # 如果已过期，也存入
        if time_since_done > EXPIRED_THRESHOLD:
            slot = self._find_available_slot(
                cooker.ingredient_name, cooker.cooker_type
            )
            if slot:
                return MoveToStockpileAction(cooker=cooker_name, slot=slot)
```

#### 4.2 增加优先级
确保 `_try_store_to_stockpile()` 在烹饪前被调用。

---

## 待验证

所有优化已在代码中实现，需要在真实游戏环境中验证效果：
- 动态swipe参数是否能提升送餐成功率？
- 前瞻性烹饪是否能减少灶台空闲时间？
- Serve失败重试是否能减少误丢弃？
- 食材超时防护是否能减少食材浪费？