# 游戏规则覆盖缺口

> playground 模拟游戏环境，不关心功能侧如何实现。
> 通过文本输入订单，观测 game_state 和 mock_ui.operations（swipe 序列），判断游戏规则是否被违反。
> 完成后可删除。

---

## 观测接口

- **输入**：文本订单检测（MockDetectionService）
- **观测点 A**：`mock_ui.operations` — Executor 输出的 swipe 序列（起点/终点/时序）
- **观测点 B**：`game_state` — 组装站归属、库存计数、灶台占用、slot 状态

## 硬规则

| 规则 | 来源 | 观测点 | 验证状态 |
|------|------|--------|---------|
| R1 组装站互斥 | §3.6 | game_state.assembly_owner | ✅ 已验证 |
| R2 库存上限 5 | §3.5 | game_state.stockpile_counts | ⚠️ 正常场景通过，但 `increment_stock` 无上限保护 |
| R3 灶台过期清理 | §3.5 | game_state.get_overdue_cookers | ❌ 检测到但无清理机制 |
| R4 动画窗口禁操作 | §2.4 | mock_ui.operations | ✅ 已验证 |
| R5 swipe 坐标合法 | — | mock_ui.operations | ✅ 已验证 |
| R6 送餐目的地与当前 slot 一致 | §2.4 | mock_ui.operations | ❌ 未验证 |

## 软规则

- rush 订单应尽早完成（记录完成时间，供分析）

---

## 覆盖缺口

### M1. 送餐目的地与 slot 位移一致性

规则涉及：R6（新增）

游戏规则（§2.4）：订单完成后右侧订单左移，pickup station 跟随左移。

当前实现问题：`FinishOrder.pickup_slot` 在调度时确定（`scheduler.py:100`），但 `advance_slots()` 在执行完成后才调用。如果 slot 在调度和执行之间发生位移，swipe 目标会指向错误的 pickup station。

预期行为：
```
orders = [A, B, C, D] in slots [0, 1, 2, 3]
完成 A → swipe assembly→pickup[0]，advance_slots → [B, C, D, None]
完成 B → swipe assembly→pickup[0]（不是 1），advance_slots → [C, D, None, None]
完成 C → swipe assembly→pickup[0]
完成 D → swipe assembly→pickup[0]
```
如果 B 的 swipe 指向 pickup[1] 而不是 pickup[0]，说明 pickup_slot 在位移前就已确定，违反 R6。

缺失的规则验证：
- [ ] 每次 `assembly → pickup` 的终点是否等于 `pickup_stations[该订单完成时的 slot 位置]`
- [ ] 先完成中间 slot（如 slot 1），后续订单的 pickup 目标是否正确跟随位移

### H1. 库存补货从未发生

规则涉及：R2、R5

现状：没有任何场景触发过库存补货。Executor 的 `destination="stockpile"` 和 `PullFromStockpile` 分支从未执行。

缺失的规则验证：
- [ ] `CookIngredient(stockpile)`: swipe `raw → cooker → stockpile_slot`，坐标合法
- [ ] `PullFromStockpile`: swipe `stockpile → assembly`，坐标合法
- [ ] 库存到达 5 后是否停止补货
- [ ] 消耗后计数是否正确递减

### H2. 订单超时从未发生

规则涉及：R1

现状：没有订单会超时。无法验证超时清槽行为。

缺失的规则验证：
- [ ] 超时后 slot 是否清空
- [ ] 超时订单是否不再产出 swipe
- [ ] 清空后新订单能否填入

### M2. 调味 swipe 次数未校验

规则涉及：R5

现状：测试校验了坐标合法性，但未校验每个 condiment 的 swipe 次数是否等于 `condiment_preference[count]`。

缺失的规则验证：
- [ ] 每个 condiment 的 swipe 次数 = `condiment_preference[condiment]`
- [ ] 调味 swipe 全部在 `assembly → pickup` 之前

### M3. 灶台过期清理机制缺失

规则涉及：R3

现状：`test_r3_no_cleanup_triggered` 验证失败 —— `get_overdue_cookers()` 能检测过期灶台，但无清理逻辑触发。

需要的变更：
- Executor 构造参数新增 `trash_position: tuple[int, int]`
- Executor 或独立协程定期检查 `get_overdue_cookers()` 并执行 `swipe(cooker_pos, trash_pos)`

---

## 总结

| # | 规则缺口 | 硬规则 | 严重度 | 状态 |
|---|---------|--------|--------|------|
| M1 | 送餐目的地与 slot 位移一致 | R6 | **High** | ❌ 新增，未验证 |
| H1 | 库存补货全链路 | R2, R5 | High | ❌ 未触发 |
| H2 | 订单超时清槽 | R1 | High | ❌ 未触发 |
| M2 | 调味 swipe 次数 | R5 | Medium | ⚠️ 坐标已验证，次数未验 |
| M3 | 灶台过期清理机制 | R3 | Medium | ❌ 机制缺失 |
