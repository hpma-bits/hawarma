# 组装站 Deadlock 分析报告

> **日期**: 2026-04-05
> **日志**: `logs/game_20260405_212255.log`
> **影响**: 35秒 Agent 完全瘫痪，37个订单仅完成6个

---

## 1. 事件概述

在真实游戏运行中，Agent 在 t=43.8s 到 t=78.9s 之间完全停止行动，持续 35 秒。日志表现为一片空白——没有错误、没有警告、没有任何动作。

## 2. 时间线重建

```
t=37.8s  Stored dough_wrappers from pot -> slot0
t=38.1s  Stored plump_wing from grill -> slot1
t=40.3s  Served order 16 (braisedNewYearFish) slot 0
         → assembly.reset() 清空组装站
t=40.6s  Pulled dough_wrappers from slot0 -> assembly
         → assembly = ["dough_wrappers"], target_recipe_slug = None  ← 问题起点
t=43.8s  Moved tender_lamb from grill -> assembly
         → assembly = ["dough_wrappers", "tender_lamb"], target_recipe_slug = None  ← 问题确认
         → 完整 newYearJiaozi 已组装，但缺少调料
t=45.0s  ~68.8s  15个 newYearJiaozi 订单到达，Agent 零行动
t=78.9s  honeyGlazedWings 订单到达，Agent 恢复行动
t=90.4s  游戏结束：6 orders done, 0 timeout, 46 actions
```

## 3. 根因分析

### 3.1 状态缺陷链

```
pull_from_stockpile()
  → 只追加 ingredient，不设置 target_recipe_slug
  → assembly = ["dough_wrappers"], target = None

add_to_assembly()
  → 只在 assembly.is_free 时设置 target_recipe_slug
  → 此时 assembly 不为空（已有 dough_wrappers）
  → 跳过 target 设置
  → assembly = ["dough_wrappers", "tender_lamb"], target = None
```

### 3.2 决策瘫痪链

```
step() 调用（每50ms一次，共~700次）：

0. _check_and_clear_expired_assembly()
   → 有活跃 newYearJiaozi 订单，不清空 → None

1. _try_serve()
   → 食材匹配 newYearJiaozi
   → 但调料为空，hearthspice 和 fleur_de_sel 都未添加
   → _condiments_complete({}, {...}) = False → None

2. _try_clear_expired()
   → 无过期食材 → None

3. _try_move_to_assembly()
   → 无完成的食材可移动 → None

4. _try_parallel_cooking()
   → 两个食材都在 assembly 中
   → 无需烹饪 → None

5. _try_add_condiment()
   → target_slug = None
   → if not target_slug: return None  ← 关键阻塞点
   → 直接返回 None，不尝试添加调料

6. _try_store_to_stockpile()
   → 无多余食材 → None

7. _try_pull_from_stockpile()
   → 无需要的食材 → None

→ step() 返回 None
→ 循环继续，下一次还是同样的结果
```

### 3.3 为什么 35 秒后才恢复

t=78.9s 时 `honeyGlazedWings` 订单到达，该配方只需要 `plump_wing`（grill）。此时 grill 是空闲的，`_try_parallel_cooking()` 找到可烹饪的食材并返回 CookAction，Agent 恢复行动。

但 assembly 中的 newYearJiaozi 仍然卡住，直到游戏结束。

## 4. 修复方案

### 4.1 环境层修复（预防）

**`GameEnvironment.pull_from_stockpile()`**:
```python
# 如果组装站为空，根据食材推断目标配方
if self._assembly.is_free:
    inferred_slug = self._infer_recipe_slug_from_ingredient(ingredient)
    if inferred_slug:
        self._assembly.target_recipe_slug = inferred_slug
```

**`GameEnvironment.add_to_assembly()`**:
```python
# 如果组装站为空且无 order_id/recipe_slug，推断
if self._assembly.is_free:
    ...
    else:
        self._assembly.target_recipe_slug = self._infer_recipe_slug_from_ingredient(ingredient)

# 如果组装站有食材但没有目标配方，尝试推断
if not self._assembly.target_recipe_slug and self._assembly.ingredients:
    all_ingredients = self._assembly.ingredients + [ingredient]
    inferred = self._infer_recipe_slug_from_ingredients(all_ingredients)
    if inferred:
        self._assembly.target_recipe_slug = inferred
```

**新增辅助方法**:
- `_infer_recipe_slug_from_ingredient(ingredient)` — 单食材匹配第一个活跃订单
- `_infer_recipe_slug_from_ingredients(ingredients)` — 多食材集合匹配活跃订单

### 4.2 Agent 层修复（恢复）

**`CookingAgent._try_add_condiment()`**:
```python
target_slug = assembly.target_recipe_slug

# 如果没有目标配方，尝试从食材推断
if not target_slug:
    target_slug = self._infer_recipe_from_assembly()
    if not target_slug:
        return None
```

**新增辅助方法**:
- `_infer_recipe_from_assembly()` — 遍历优先级订单，匹配组装站食材

### 4.3 防御层关系

```
环境层（预防）          Agent 层（恢复）
pull_from_stockpile  →  _infer_recipe_from_assembly
add_to_assembly      →  _try_add_condiment fallback
```

## 5. 优化方向

### 5.1 停滞检测（✅ 已实现）

在 `CookingAgent` 中实现 `_consecutive_none` 计数器，通过 `step_with_diagnostics()` 暴露。连续 5 秒无行动时输出 WARNING 级别诊断日志，包含：
- 组装站食材和目标配方
- 活跃订单列表及剩余超时时间
- 停滞原因分析（调料缺失、无空闲灶台、烹饪中食材、库存内容等）

```python
# agent.py
self._consecutive_none = 0
self._stagnation_warned = False

def step_with_diagnostics(self) -> Optional[Action]:
    action = self.step()
    if action:
        self._consecutive_none = 0
        self._stagnation_warned = False
        return action
    self._consecutive_none += 1
    if self._consecutive_none * 0.05 >= 5.0 and not self._stagnation_warned:
        self._stagnation_warned = True
        self._log_stagnation_diagnostic(stagnant_duration)
    return action
```

bridge.py 的 `_agent_loop()` 已切换为调用 `step_with_diagnostics()`。

### 5.2 组装站超时清理（✅ 已实现）

`_check_stale_assembly()` 在 `step()` 中作为优先级 0.5 执行（在 expired assembly 检查之后）。当组装站食材齐全但调料缺失超过 15 秒时，自动清空组装站并重新开始。

```python
def _check_stale_assembly(self) -> Optional[ClearAssemblyAction]:
    STALE_THRESHOLD = 15.0
    # 检测条件：食材齐全 + 调料不完整 + 超过阈值
    if ingredients_complete and not condiments_complete:
        if self._assembly_stale_since is None:
            self._assembly_stale_since = self.env.time
        elif self.env.time - self._assembly_stale_since >= STALE_THRESHOLD:
            return ClearAssemblyAction()
```

### 5.3 日志增强（✅ 已实现）

`_log_stagnation_diagnostic()` 在停滞 5 秒时输出结构化诊断信息：

```
[t=45.0s] Agent stagnation: 5.0s without action | assembly=[dough_wrappers, tender_lamb] target=None | orders=[newYearJiaozi(25s)] | reasons=[condiments_incomplete(missing=['hearthspice', 'fleur_de_sel'])]
```

诊断信息包含：
- 停滞持续时间
- 组装站状态（食材列表、目标配方）
- 活跃订单（配方名 + 剩余超时时间）
- 原因分析（动画窗口、调料缺失、无空闲灶台、烹饪中、库存内容）

## 6. 经验教训

1. **状态完整性 > 逻辑正确性**：关键状态字段必须在所有写入路径上保持一致
2. **瀑布决策需要安全网**：所有检查都失败时应有诊断/恢复机制
3. **防御性编程需要多层**：环境层预防 + Agent 层恢复
4. **日志要覆盖"为什么没做"**：沉默的失败比报错更危险
5. **测试需要覆盖状态转换序列**：单方法测试不够，需要集成测试验证操作序列
6. **异步代码中不能有同步阻塞调用**：`G.DEVICE.snapshot()` 等 ADB 同步调用会阻塞整个 asyncio 事件循环，导致所有其他协程（包括 agent_loop）完全瘫痪。必须使用 `asyncio.to_thread()` 包装（2026-04-05 后续发现）
