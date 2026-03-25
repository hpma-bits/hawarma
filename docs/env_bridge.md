# env_bridge.py — 环境桥接器

## 定位

连接 **Executor**（真实系统）和 **GameSimulator**（规则参考实现）的适配器。

拦截 Executor 的每个 swipe 操作，翻译为符号操作，调用 env_simulator 验证规则合规性。

```
Executor ──swipe(start, end)──→ EnvBridge ──symbolic operation──→ GameSimulator
                                        │
                                        ├── 记录 swipe（兼容 MockUI）
                                        ├── 翻译坐标 → 符号名
                                        ├── 推进模拟器时间
                                        └── 验证规则
```

## 核心职责

### 1. 坐标翻译

将 Executor 的像素坐标翻译为 env_simulator 的符号名：

```
(50, 100)  → "ingredient:clearwater_fish"
(100, 400) → "cooker:skillet"
(500, 300) → "assembly"
(150, 100) → "condiment:hearthspice"
(700, 100) → "pickup:slot0"
(300, 100) → "stockpile:slot0"
(130, 560) → "trash"
```

### 2. 操作推断

根据起点/终点符号推断操作类型：

| 起点 | 终点 | 操作 |
|------|------|------|
| `ingredient:*` | `cooker:*` | cook |
| `cooker:*` | `assembly` | move_to_assembly |
| `cooker:*` | `stockpile:*` | move_to_stockpile |
| `stockpile:*` | `assembly` | pull_from_stockpile |
| `condiment:*` | `assembly` | add_condiment |
| `assembly` | `pickup:*` | serve |
| `cooker:*` | `trash` | clear_to_trash |

### 3. 时间推进

在每次 swipe 前检查并推进模拟器时间：

```
_advance_for:
  cook          → 不推进（start_cooking 自己设 done_at）
  move_to_assembly → 推进到 cooker.done_at（如果烹饪未完成）
  serve         → 推进到 _animation_until（如果在动画窗口）
```

swipe 执行后，推进 `swipe.duration`（0.1s 或 0.2s）。

### 4. 规则验证

调用 env_simulator 的操作方法，返回成功/失败。失败时记录违规：

```
bridge.violations = [
    "Invalid swipe: move_to_assembly cooker:grill -> assembly",
    "Invalid swipe: cook ingredient:shrimp -> cooker:skillet",
]
```

## 接口

```python
class EnvBridge:
    def __init__(self, simulator, raw_ingredients_mapping,
                 cookers_mapping, condiments_mapping,
                 assembly_pos, stockpile_positions,
                 pickup_positions, trash_pos=(130, 560))

    # 核心：拦截 Executor 的 swipe
    async def swipe(self, start, end, duration=0.1) -> None

    # 兼容 UIOperationManager 接口
    async def execute(self, operation, *args, **kwargs) -> None

    # 时间控制
    def tick(self, dt) -> list[Event]

    # 查询
    def snapshot(self) -> dict
    def has_violations(self) -> bool
    def get_swipe_symbols(self) -> list[tuple[str, str, str]]

    # 兼容 MockUI（记录操作）
    operations: list[_SwipeOp]
    records: list[SwipeRecord]
    violations: list[str]
```

## 作为 MockUI 替代

Bridge 实现了 `UIOperationManager` 的接口，可以替代 `MockUIOperationManager`：

```python
# 之前：用 MockUI
mock_ui = MockUIOperationManager(simulate_delay=False)
executor = Executor(..., ui_manager=mock_ui, ...)

# 之后：用 Bridge
bridge = EnvBridge(simulator=sim, ...)
executor = Executor(..., ui_manager=bridge, ...)
```

## 验证流程

```
1. Executor 调用 bridge.swipe(start, end)
2. Bridge 解析坐标 → 符号名
3. Bridge 推断操作类型
4. Bridge 调用 _advance_for（推进模拟器时间）
5. Bridge 调用 _execute_sim（验证 + 更新模拟器状态）
6. 如果失败 → 记录 violation
7. Bridge 记录 swipe 到 records 和 operations
8. Bridge 推进模拟器时间（swipe.duration）
```

## 局限性

| 问题 | 说明 |
|------|------|
| 时间同步 | 模拟器时间由 bridge 管理，可能与 Executor 的实际时间不同步 |
| 并发验证 | `_cook_parallel` 的并发任务可能导致 bridge 状态不一致 |
| 未知坐标 | 坐标不匹配任何游戏元素时标记为 `unknown`，产生违规 |
| 顺序敏感 | bridge 按 swipe 顺序验证，不支持回溯或批量验证 |
