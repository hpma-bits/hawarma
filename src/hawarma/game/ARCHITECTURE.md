# src/hawarma/game 目录架构

## 📁 目录概述

此目录包含真实游戏环境的状态追踪和管理层。

## ⚠️ 重要提示

**一旦本目录有变化（新增/删除/重命名文件），务必对开头注释进行相应的必要更新，同时更新所属目录的md**

## 📄 文件列表

### `__init__.py`
- **地位**: 包初始化文件
- **功能**: 导出所有游戏组件
- **导出**: `GameEnv`, `Scanner`, `Operator`, `Runner`, `CookerState`, `AssemblyState`, `StockpileSlot`, `Order`, `MixingBowlState`

### `env.py`
- **地位**: 模块文档（不再定义 ABC）
- **功能**: 说明真实环境和模拟环境通过 UnifiedState + Action 共享数据契约，不定义行为接口

### `game_env.py`
- **地位**: 真实游戏状态追踪器 + 订单生命周期唯一入口（Issue #18）
- **功能**:
  - 独立类（不继承 ABC），追踪灶台、组装站、搅拌盆、库存、订单、调料
  - 时钟注入（#17）：构造函数接受 `clock: Callable[[], float]`（默认 `time.monotonic`）；env.time/订单时间戳为局内相对秒数，动画窗口等墙钟测量同走此 clock，不再使用 epoch `time.time()`
  - 订单生命周期原子公共 API（Issue #18）：
    - `create_order(recipe_slug, is_rush) -> Order`：订单创建唯一入口。timeout 从 `RecipeTimeoutLookup` 查表（构造注入 `timeout_lookup` 或懒加载，与 #22 reward_lookup 模式一致），查不到 fallback 类常量 `DEFAULT_NORMAL_TIMEOUT/DEFAULT_RUSH_TIMEOUT`（原 70/40 行为）；锁定 `spawned_at_visibility`；`_next_order_id` 自增；只构造对象不落槽位
    - `apply_scan_result(scanned, recently_served, now_wall)`：扫描结果的原子同步方法（同步、无 await）——匹配（同位优先 + 位移）/serve ghost 过滤/防复活校验/新建/延迟删除全部在 env 内完成（详见「订单生命周期与竞态防护」一节）
    - `serve_order_by_id(order_id) -> Order | None`：按 serve 前锁定的 order_id 结算；找不到（验证窗口内被 timeout 删）warning + 不计分，绝不结算到错单
    - `add_order` 保留为 `create_order` 的薄别名（最左空槽落位，旧返回契约），供既有调用方兼容
  - 通过 `get_unified_state()` 产出 `UnifiedState` 供 Strategy 决策
  - `get_unified_state()` 返回全量深快照（#16）：orders/cookers/assembly/stockpile/mixing_bowl 均为各模型 `snapshot()` 字段级拷贝，与内部状态无共享可变对象；recipes 只读共享
  - 得分查表 `RecipeRewardLookup` 支持构造注入共享实例；未注入时首次 `on_order_served` 前懒加载（Issue #22）
  - 异步环境：状态由 Scanner/Runner 外部更新，不实现 `step()`
- **输入**: UI操作结果、订单检测结果
- **输出**: `UnifiedState` 快照供 Strategy 决策
- **关键类**: `GameEnv`

### `scanner.py`
- **地位**: 订单扫描器
- **状态**: ✅ 完成（异步化 snapshot）
- **功能**:
  - 检测屏幕上的订单
  - 识别配方和加急状态
  - 检测游戏开始（timer图标）
  - **异步截图**：`detect_timer()`, `scan_orders()`, `scan_new_orders()` 均为 async 方法，使用 `asyncio.to_thread()` 避免阻塞事件循环
  - **调试保存异步化（Issue #19）**：`_save_screenshot`（二次截图 + `cv2.imwrite` 磁盘 IO）由 `scan_orders` 经 `asyncio.to_thread` 放入 worker 线程，不阻塞扫描关键路径；方法本身保持同步签名
  - **Rush 检测 config 单源（Issue #22）**：`_detect_rush` 的检测点位/红色阈值只读 `config.game.rush_detection_positions` / `rush_red_threshold`（默认值即原类常量值），空列表 = 关闭 rush 检测，不再静默回落硬编码；配方 slug 查询统一走 `RecipeManager`（Scanner 不再自带 `get_recipe_by_slug`）
- **输入**: 屏幕截图、配置对象
- **输出**: 检测到的订单信息
- **关键类**: `Scanner`, `DetectedOrder`

### `verifier.py`
- **地位**: 组装站提交验证器（可插拔组件）
- **状态**: ✅ 新增
- **功能**:
  - 通过模板匹配检测组装站区域是否为空
  - 验证送餐操作是否成功提交菜品
  - **保持同步签名（Issue #19）**：`is_assembly_empty()` 内部的 snapshot+模板匹配由调用方（Runner `_verify_with_multi_snapshot`）经 `asyncio.to_thread` 线程化，函数签名不泄漏 async
  - ROI: `(1150, 720, 1600, 1030)`
  - 模板: `static/img/empty_assembly.jpg`
- **输入**: 配置对象
- **输出**: 验证结果（成功/失败）
- **关键类**: `Verifier`
- **关键方法**: `is_assembly_empty()` — 返回 True 表示提交成功

### `operator.py`
- **地位**: UI操作执行器
- **状态**: ✅ 完成（设备 IO 已异步化，Issue #19）
- **功能**:
  - 封装所有swipe操作
  - 从config.yaml读取坐标配置
  - 提供异步执行接口
  - **设备 IO 异步化（Issue #19）**：`swipe()` 内部 airtest 调用经 `asyncio.to_thread` 在 worker 线程执行，事件循环在设备往返期间不停摆；串行化语义由协程层 `asyncio.Lock` 保证（`async with lock` → `await to_thread(...)`）；`timing.swipe` 打点仍覆盖真实设备往返耗时。节拍收益待真机验证
  - **动态坐标映射**：根据菜谱选择顺序确定元素位置
  - 使用 Airtest 内置的 minitouch 触摸方法
  - **垃圾桶坐标配置化**：`clear_cooker()` 和 `clear_assembly()` 使用 `config.screen.trash_position`
  - **clear_assembly 增强**：使用 `duration=0.4, steps=8` 确保拖拽动作被游戏识别
- **输入**: 符号化操作（食材名、灶台名等）
- **输出**: swipe操作执行结果
- **关键类**: `Operator`

#### 坐标映射规则

Operator根据菜谱选择顺序动态确定各元素坐标：

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

### `runner.py`
- **地位**: 真实游戏桥接器
- **状态**: ✅ 完成（三循环并行 + 事件驱动决策 + 送餐验证重试 + 耗时观测）
- **功能**:
  - 协调 Agent、环境、扫描器和 UI 执行器
  - 管理游戏生命周期
  - 运行三个并行循环（scan / timeout / agent）并执行 Agent 动作
  - **事件驱动决策**：`_agent_loop()` 由 `_agent_wakeup` 事件唤醒，空闲时 0.5s 兜底
  - **订单生命周期零越权（Issue #18）**：Runner 不再读写 `env._orders` / `env._next_order_id` / `env._scoring`——`_sync_orders_from_scan()` 只做扫描 + 动画窗口防护，然后把扫描条目交给 `env.apply_scan_result`（原子同步）并透传 `_last_served` 幽灵窗口记录；订单创建/超时查表全部走 `env.create_order`
  - **送餐按 id 结算（Issue #18）**：`_serve_with_verify()` 在每次尝试 swipe 前锁定该槽当前 order_id，验证成功后经 `env.serve_order_by_id` 结算——验证窗口内订单被 timeout 移位/删除时绝不结算到错单
  - **送餐验证重试**：`_serve_with_verify()` 带分段耗时打点（验证等待 / 截图 / 重试 / 清理）；动画渲染等待时长读 `config.game.serve_verify_wait`（构造参数注入，默认 0.2，Issue #22 接线）
  - **验证路径设备 IO 异步化（Issue #19）**：`_verify_with_multi_snapshot()` 的预热 snapshot ×3 与 `verifier.is_assembly_empty()`（snapshot+模板匹配）均经 `asyncio.to_thread` 执行，验证期间三循环照常推进。节拍收益待真机验证
  - **Action 调度**：`dispatch_batch()` 经共享 `schedule_actions` 排序/过滤后逐个 `_execute_action()`；
    已取消动作直接跳过（Ticket #11 / Spec #7 S3），与 SimEnv 回放语义一致
  - **时基（#17）**：构造函数接受 `clock`（默认 `time.monotonic`）透传墙钟测量；ghost 窗口/扫描计时走 monotonic clock，`asyncio.get_event_loop().time()` 已移除
  - **异步扫描**：`_sync_orders_from_scan()` 为 async 方法，await scanner 的异步截图
- **输入**: 配置对象、配方列表
- **输出**: 游戏统计结果（含 scoring 统计与 execution timing）
- **关键类**: `Runner`

### `timing.py`
- **地位**: 执行耗时观测模块（Ticket #9 / Spec #7 S2）
- **功能**:
  - `SegmentTiming` / `ExecutionTiming`：分段耗时聚合（count / total / avg / max）
  - `Timer`：拉起即计时、record 落账的上下文助手
  - 只观测不改行为；供 Runner 送餐验证路径与 Operator 滑动往返打点

## 🔗 模块间关系

```
Runner (主控制器)
    ├── GameEnv (状态追踪)
    ├── Scanner (订单检测)
    ├── Operator (UI操作)
    └── Runner (决策逻辑)
```

## 数据流

```
Scanner.scan_orders()
    ↓
DetectedOrder
    ↓
Runner._sync_orders_from_scan()（收集条目 + 动画窗口防护）
    ↓
GameEnv.apply_scan_result()（原子同步：匹配/ghost 过滤/防复活/新建/延迟删除，
                            新建走 create_order —— timeout 查表 + visibility 锁定）
    ↓
Runner.step()
    ↓
Action
    ↓
Runner._execute_action()（已取消直接跳过，无 UI 调用、无状态变化）
    ↓
Operator.swipe()
    ↓
GameEnv状态更新（serve 结算走 serve_order_by_id，按 serve 前锁定的 order_id）
    ↓
Verifier.is_assembly_empty() (仅送餐后)
```

### 送餐验证流程（Issue #18：按 order_id 结算）

`_exec_serve_order()` 使用 `_serve_with_verify()` 执行带验证的送餐：

```
1. 锁定目标槽位当前 order_id（swipe 前的安全锚点）
2. 执行 UI 送餐操作（await —— 验证窗口从此开始，timeout 循环可能移位/删除订单）
3. 等待动画 + 多点 snapshot 验证
   ├── 为空 → 成功 → env.serve_order_by_id(order_id)
   │     ├── 订单仍活跃（可能已移位）→ 正确结算该订单，调用方按返回值计分
   │     └── 订单已被 timeout 删 → warning + 不计分（绝不结算到错单）
   └── 不为空 → 警告 → 重新锁定相邻左侧 slot 的 order_id 并重试（最多 2 次）
       └── 全部失败 → 清理组装站，继续游戏
```

**设计原则**：
- 结算以 serve 前（该次尝试 swipe 前）锁定的 order_id 为准：验证窗口 ≥0.25s，
  期间 timeout 移位/删除不会导致按旧 slot 结算到错单
- 最多重试 2 次，避免无限循环；重试前重新锁定该槽当前订单 id
- `env.serve_order_by_id()` 只在验证成功后调用，保证环境状态一致性
- 最终失败时清理组装站，防止卡死

### ⚠️ 订单同步动画窗口保护（2026-06-03 修复）

**问题**：`_sync_orders_from_scan()` 在动画窗口期间可能捕获到送餐前的旧帧（视觉上 slot 0 还能看到刚送走的订单，slot 1 是 RUSH），导致 ghost 防护失效或订单被错位放置。

**修复**：在 `_sync_orders_from_scan()` 开头和 `await scanner.scan_new_orders()` 之后双重检查 `is_in_animation_window()`，处于动画期则跳过本次 sync。

**设计权衡**：
- 动画期（1.5s）不 sync → env 保持 `_shift_orders_left` 后的内部状态
- 策略在此期间看到 env 内部状态（可能与屏幕视觉差 1.5s）
- 动画结束后下次 sync 重新对齐视觉与 env

**影响范围**：
- 动画期可能延迟发现 1 个新订单（最坏 1.5s 滞后）
- 消除了视觉/env 错位导致的 strategy 误判

## 🔄 订单生命周期与竞态防护（Issue #18）

订单的创建/同步/结算收敛为 GameEnv 的原子公共 API；Runner 只做扫描/执行，
不再触碰 env 私有状态（`env._orders` / `env._next_order_id` / `env._scoring`）。

### 竞态根源与修复

单线程事件循环下每个 env 变更点本身是原子的，竞态源于 **await 点之间的
"旧快照数据"**——扫描/验证协程挂起期间，timeout/serve 循环推进了 env 状态。
修复方式：把「外部观测结果 → 变更决策」整体放进 env 的同步方法（无 await）。

| 竞态 | 旧实现 | Issue #18 修复 |
|------|--------|----------------|
| 扫描旧帧覆盖 | `_sync_orders_from_scan` 在 await 扫描后用旧帧 `[None]*4` 全量覆盖 `env._orders`，serve/timeout 已发生的删除被复活 | `apply_scan_result` 增量同步 + 防复活记忆窗口 |
| serve 验证窗口错单 | `_serve_with_verify` ≥0.25s 后按 serve 前 slot_idx 取 `env.orders[slot]` 结算，timeout 移位后给错单打分 | swipe 前锁定 order_id，`serve_order_by_id` 按 id 结算，找不到则不计分 |
| 订单创建双实现 | runner sync 复制 `add_order` 语义（硬编码 40/70 + visibility 锁定），`add_order` 生产路径无人调用 | `create_order` 唯一入口，runner 经 `apply_scan_result` 间接调用 |
| 超时口径分裂 | 模拟器走 `recipe_timeout.csv`，真实 env 硬编码 40/70 | 两端统一走 `RecipeTimeoutLookup`（真实端 fallback 类常量） |

### GameEnv 公共 API

| API | 职责 |
|-----|------|
| `create_order(recipe_slug, is_rush) -> Order` | 订单创建唯一入口：timeout 查表（`RecipeTimeoutLookup` 构造注入或懒加载，与 #22 reward_lookup 模式一致）+ fallback `DEFAULT_NORMAL_TIMEOUT/DEFAULT_RUSH_TIMEOUT`；锁定 `spawned_at_visibility`；`_next_order_id` 自增；不落槽位 |
| `apply_scan_result(scanned, recently_served, now_wall) -> dict` | 原子同步（无 await）：匹配/ghost 过滤/防复活/新建/延迟删除，返回同步统计 |
| `serve_order_by_id(order_id) -> Order \| None` | 按 serve 前锁定的 id 结算；找不到（被 timeout 删）warning + 不计分 |
| `add_order` | `create_order` 薄别名（最左空槽落位），保留旧调用兼容 |

### apply_scan_result 增量语义

1. **匹配**：扫描条目按 `(recipe_slug, is_rush)` 匹配现有**活跃**订单（同位
   优先，再其他位——订单位移），复用 order_id/created_at/timeout_at，
   放置到扫描位置（反映屏幕真实布局）
2. **serve ghost 过滤**：`recently_served`（Runner `_last_served`，墙钟）内
   `SERVE_GHOST_WINDOW`(1.5s) 刚 serve 过该类型且 env 无活跃同名单 → 跳过
   （防扫描图像延迟，与防复活互补）
3. **防复活**：无匹配但命中已删除订单记忆（`_recently_removed`，
   `REMOVED_ORDER_MEMORY_WINDOW`(1.5s) 墙钟窗口内 serve/timeout 删除的同名单）
   → 视为旧扫描帧幽灵，不重建订单
4. **新建**：其余未匹配条目经 `create_order` 创建
5. **延迟删除**：现有订单连续 `SCAN_MISS_DELETE_THRESHOLD`(2) 次扫描未出现才
   删除；未达阈值的存活单追加到尾部空位（miss 计数扫到即清零）

`serve_order` / `serve_from_cooker` / `check_and_remove_timed_out_orders`
移除订单时自动写入 `_recently_removed` 记忆。

**设计权衡**：
- 记忆窗口内同名单的合法新单最多被延迟 ~1.5s 发现（与既有 serve ghost
  窗口的代价一致；扫描间隔 0.4-0.5s，旧帧最多存活一个扫描周期，1.5s 保守）
- 延迟删除使消失订单在 env 内多存活一个扫描周期（~0.5s），换取单次漏检
  不误删（timeout 循环仍即时删除真正超时的订单，不受影响）

## 得分系统（与模拟器对齐）

真实环境与模拟器使用**同一套** `RecipeRewardLookup` 计算得分，公式见 `docs/game_rules.md:194-226`：

```
order_score = (base_points + visibility) * multiplier(spawned_at_visibility, is_rush)
```

关键约束：**`spawned_at_visibility` 必须在订单生成瞬间锁定**（不是 serve 瞬间），因为倍率依赖该值，订单一旦生成其倍率就不再变化。

### 实现机制

1. **`Order.spawned_at_visibility`** (`core/models.py:Order`)：新增字段，`immutable since creation` —— 通过 `__setattr__` 重写阻止二次赋值，确保域语义「生成瞬间快照」不被破坏。
2. **`GameEnv.create_order()`**（Issue #18 唯一创建入口；`add_order` 为其薄别名）：每次新增订单时，把当前 `_scoring.total_visibility` 写入 `order.spawned_at_visibility`。
3. **`ScoringContext`** (`core/scoring.py`，S1 抽离)：统计查询、总分、终局结算的唯一持有者。`GameEnv` 直接读写 `_scoring`（Issue #22 已删除过渡期兼容 property），改计分只碰此处。
4. **`GameEnv.on_order_served(order, has_condiments)`**：
   - `score = RecipeRewardLookup.get_score(order.recipe_slug, has_condiments, order.is_rush, total_visibility=order.spawned_at_visibility)`
   - `_scoring.record_serve(score, get_visibility(...))`
5. **`GameEnv.finalize()`**（幂等）：`final_score = total_score + total_visibility`；`get_stats()` 同时返回 `total_score`（逐单和）、`total_visibility`、`final_score`、`scoring_version`。
6. **`Runner._exec_serve_order()` / `_exec_serve_from_cooker()`**：在结算清空 assembly 之前用 `env.assembly.condiments` 读取 `has_condiments`，然后调用 `env.on_order_served(order, has_condiments)`（Issue #18：`_exec_serve_order` 经 `env.serve_order_by_id` 拿到被结算订单后再计分）。甜点单食材直送（`serve_from_cooker`）时 `has_condiments=False`。
7. **`Runner._sync_orders_from_scan()`**：扫描新建订单走 `env.apply_scan_result` → `env.create_order`，同样锁定 `spawned_at_visibility=_scoring.total_visibility`（与 `create_order` 同语义）；`run()` 返回前先 `finalize()`。

### 与模拟器的差异

| 方面 | 模拟器 | 真实环境 |
|------|--------|----------|
| spawned_at_visibility 存储 | `order.spawned_at_visibility`（域字段为准，`_order_visibility` 字典仅兼容回退） | `order.spawned_at_visibility`（域字段） |
| total_visibility 累加 | `state.total_visibility`（+ `_total_score` 逐单和） | `ScoringContext.total_visibility`（+ `total_score` 逐单和） |
| 终局 total_visibility 加分 | `finalize()` 幂等：`_total_score + state.total_visibility`（v2） | `finalize()` 幂等：`total_score + total_visibility`（v2） |

终局口径 `v2 = 逐单和 + 总 visibility`（`docs/game_rules.md:226`），`scoring_version` 随 Episode/基准 CSV/JSON 隔离展示（v1=历史逐单和口径）。

## 与模拟器的区别

| 方面 | 模拟器 (GameSimulator) | 真实环境 (GameEnv) |
|------|------------------------|---------------------------|
| 状态追踪 | 内置状态机 | 程序逻辑追踪 |
| 时间推进 | tick()方法 | 真实时间 |
| 操作执行 | 符号操作 | UI swipe操作 |
| 订单生成 | 随机生成 | 屏幕检测 |
| 订单超时口径 | `RecipeTimeoutLookup` 查 `recipe_timeout.csv` | 同左（Issue #18 收敛单源；查不到 fallback `DEFAULT_*_TIMEOUT` 类常量） |
| 食材过期 | expired_at 字段，强制阻止 | expired_at 字段，move_to_assembly/stockpile 拒绝过期 |
| 配方校验 | 模拟器内部校验 | add_to_assembly/add_condiment 校验目标配方 |
| 用途 | 测试、算法优化 | 实际游戏 |

---

## 🔄 三循环并行架构详解

### 架构概述

Runner 采用 **三循环并行架构**，通过 `asyncio.gather()` 同时运行三个独立的异步循环：
扫描循环、超时循环、决策循环。

```python
async def run(self) -> dict:
    # 1. 等待游戏开始
    await self._wait_for_game_start()

    # 2. 启动三个并行循环
    self._running = True
    try:
        await asyncio.gather(
            self._scan_loop(),      # 订单扫描循环
            self._timeout_loop(),   # 订单超时检测循环
            self._agent_loop(),     # Agent 决策循环（事件驱动）
        )
    except asyncio.CancelledError:
        pass
    finally:
        self._running = False

    # 3. 终局结算（幂等）后返回统计（含 total_score / total_visibility /
    #    final_score / scoring_version / timing）
    self.env.finalize()
    return self.env.get_stats()
```

### 扫描循环 (_scan_loop)

**职责**：检测屏幕上的订单，把扫描条目交给 env 原子同步（Issue #18：
匹配/ghost 过滤/防复活/新建/延迟删除在 `GameEnv.apply_scan_result` 内完成，
详见「订单生命周期与竞态防护」一节）

**频率**：自适应（0.4s / 0.5s），动画窗口期间暂停

```python
async def _scan_loop(self) -> None:
    """订单扫描循环（自适应频率），动画窗口期间暂停"""
    while self._running and not self.env.is_game_over():
        if self.env.is_in_animation_window():
            remaining = self.env.animation_window_remaining()
            if remaining > 0:
                await asyncio.sleep(remaining + 0.1)
            self._agent_wakeup.set()
            continue

        await self._sync_orders_from_scan()
        self._agent_wakeup.set()
        interval = self._compute_scan_interval()
        await asyncio.sleep(interval)
```

**自适应频率策略**（`_compute_scan_interval()`，实码为准）：

| 游戏状态 | 扫描间隔 | 原因 |
|----------|----------|------|
| 有活跃订单 + 有灶台空闲 | 0.4s | 快速发现新订单，立即启动烹饪 |
| 无活跃订单 | 0.5s | 中速等待新订单出现 |
| 所有灶台都在忙 | 0.5s | 等烹饪完成再处理 |

**关键点**：
- 使用 `Scanner` 进行图像检测
- 只检测订单，其他状态通过程序逻辑维护
- 在动画窗口期暂停扫描，睡到窗口结束后唤醒 agent
- **`_sync_orders_from_scan()` 是 async 方法**，内部 `await self.scanner.scan_new_orders()`
- **`G.DEVICE.snapshot()` 通过 `asyncio.to_thread()` 异步执行**，不阻塞 agent_loop
- **扫描不会重叠**：每次扫描完成后才计算间隔并 sleep

### 超时循环 (_timeout_loop)

**职责**：检查并移除超时订单，有变化时唤醒 agent

**频率**：每 0.3 秒

```python
async def _timeout_loop(self) -> None:
    """订单超时检测循环（每 0.3s），有变化时唤醒 agent"""
    while self._running and not self.env.is_game_over():
        timed_out = self.env.check_and_remove_timed_out_orders()
        if timed_out:
            for order_id in timed_out:
                self.env.on_order_timeout(order_id)
            self._agent_wakeup.set()
        await asyncio.sleep(0.3)
```

### 决策循环 (_agent_loop)

**职责**：调用 Strategy 决策，执行 Action，跳过动画窗口期间的送餐

**频率**：事件驱动（`_agent_wakeup` 事件唤醒；空闲时 0.5s 被动兜底检查）

```python
async def _agent_loop(self) -> None:
    """Agent 决策循环（事件驱动），只在有信息变化时唤醒"""
    while self._running and not self.env.is_game_over():
        if self._executing_action:
            await asyncio.wait_for(self._agent_wakeup.wait(), timeout=2.0)
            self._agent_wakeup.clear()
            continue

        try:
            await asyncio.wait_for(self._agent_wakeup.wait(), timeout=0.5)
            self._agent_wakeup.clear()
        except asyncio.TimeoutError:
            pass  # 0.5s 无事件：被动兜底唤醒，防止死锁

        in_animation = self.env.is_in_animation_window()
        action = self.strategy.decide(self.env.get_unified_state())
        if action:
            action_type = type(action).__name__
            if in_animation and action_type in (
                "ServeOrderAction", "ServeFromCookerAction"
            ):
                continue  # 动画窗口期间跳过送餐，允许烹饪继续

            self.env.on_action_taken()
            self._executing_action = True
            await self._execute_action(action)
            self._executing_action = False
            self._agent_wakeup.set()
```

**醒来事件**：扫描完成 / 动作执行完成 / 动画结束 / 订单超时 / 0.5s 兜底定时器，任一触发都会 `_agent_wakeup.set()`。

### 为什么采用三循环？

| 设计选择 | 原因 |
|----------|------|
| 扫描与决策分离 | 图像检测较慢（~100ms），不应阻塞决策 |
| 超时独立循环 | 超时判定是高频时间敏感项，独立 0.3s 轮询不干扰其他循环 |
| 决策事件驱动 | 只在状态变化时决策，避免空转浪费；兜底 0.5s 防止死锁 |
| 异步并发 | 避免 I/O 阻塞，最大化利用等待时间 |
| 动画窗口检查 | 扫描与决策各自检查动画窗口，双重保护防止冲突 |

### 设备 IO 已移出事件循环（Issue #19）

三循环的节拍假设（timeout 0.3s / agent 兜底 0.5s / 扫描 0.4-0.5s）此前会被
同步设备 IO 整段打断：每次 swipe（0.1-0.4s，叠加 maxtouch patch 的两个
0.1s SleepEvent）、验证 snapshot、调试写盘期间事件循环停摆，三个循环全部停顿。

现在所有设备 IO 均经 `asyncio.to_thread` 在 worker 线程执行，事件循环在
IO 期间照常推进，节拍假设恢复成立：

| 阻塞点 | 异步化方式 |
|--------|-----------|
| `Operator.swipe` 的 airtest swipe | `asyncio.to_thread(swipe, ...)`，锁在协程层持有 |
| Runner `_verify_with_multi_snapshot` 的预热 snapshot ×3 | `asyncio.to_thread(G.DEVICE.snapshot)` 逐次 |
| Verifier `is_assembly_empty`（snapshot+模板匹配） | 调用方（Runner）`await asyncio.to_thread(...)`，同步签名不变 |
| Scanner `_save_screenshot`（二次截图+`cv2.imwrite`） | 调用方（`scan_orders`）`asyncio.to_thread(...)`，同步签名不变 |

设计约束：
- **锁语义**：`asyncio.Lock` 在协程层持有（`async with lock` → `await to_thread(...)`），
  不在线程内抢 asyncio 锁，UI 操作串行化语义不变
- **计时不受影响**：`ExecutionTiming` 打点仍覆盖 to_thread 内的真实设备耗时
  （`t0` → `await to_thread(...)` → record）
- **节拍收益待真机验证**：模拟器/单测只能证明事件循环不停摆，真实设备上
  swipe/snapshot 时长分布与三循环节拍稳定性需 30 局以上真机测试确认

---

## ⏱️ 时间推进机制

### 统一时基（Issue #17）

GameEnv 构造函数支持注入 `clock: Callable[[], float]`（默认 `time.monotonic`），
Runner 同样接受 `clock` 参数用于自身墙钟测量。两个时间概念严格分离：

| 概念 | 时基 | 载体 |
|------|------|------|
| **游戏内时间** | 局内相对秒数（游戏开始 = 0.0，`clock() - game_start`） | `env.time`、`Order.created_at/timeout_at/served_at`、`CookerState.started_at/done_at/expired_at`、`UnifiedState.time` |
| **真实耗时测量**（墙钟） | monotonic 绝对时刻 / 差值 | 动画窗口（`_animation_until`）、Runner ghost 窗口（`_last_served`）、扫描计时（scan_duration）、timing.py 打点（perf_counter） |

设计动机：
- epoch 墙钟（time.time()）受 NTP 校时/系统睡眠影响，会让订单集体误判超时；
  monotonic 单调递增，不受校时回拨影响
- 真实端订单时间戳此前用 epoch，与 `env.time`（相对）两种时基并存，
  dessert 策略 `timeout_at - state.time` 混减出无意义的巨大值；统一为
  相对秒数后与模拟器端（`state.time` tick）同基，双端 Order 构造点语义一致
- 测试可注入假时钟（`tests/test_time_base.py`）确定性驱动订单超时/动画窗口

### 实时时间计算

GameEnv 使用 **注入时钟（默认 monotonic）** 计算游戏时间，而非模拟 tick：

```python
@property
def time(self) -> float:
    """当前游戏时间（秒，局内相对：clock() - game_start 起点时刻）"""
    if self._game_start_time is None:
        return 0.0
    return self._clock() - self._game_start_time
```

### 游戏生命周期

```python
def start_game(self) -> None:
    """开始游戏计时（记录 clock 起点，env.time 从 0 起算）"""
    self._game_start_time = self._clock()
    logger.info("Game started!")

def is_game_over(self) -> bool:
    """游戏是否结束"""
    if self._game_start_time is None:
        return False
    return self.time >= self._game_duration  # 默认90秒
```

订单生命周期同基：`create_order`（Issue #18 唯一创建入口）用 `now = self.time`
写 `created_at/timeout_at`（timeout 走 `RecipeTimeoutLookup` 查表 + fallback）；
`check_and_remove_timed_out_orders` 用 `now = self.time` 判超时；
`apply_scan_result` 在 env 内同步应用扫描结果（新建走 `create_order`，同样取
`env.time` 相对秒数）；Runner 的 ghost 窗口与扫描计时走注入的墙钟 clock。

### 与模拟器 tick 的对比

| 方面 | 真实环境 (GameEnv) | 模拟器 (GameSimulator) |
|------|---------------------------|------------------------|
| 时间源 | 注入 clock（默认 `time.monotonic`） | `self._state.time` 模拟时间 |
| 推进方式 | 自动流逝 | 显式调用 `tick(dt)` |
| 精度 | 毫秒级 | 取决于 tick 间隔 |
| 确定性 | 非确定性（真实时钟）/ 确定性（注入假时钟） | 完全确定性 |
| 订单时间戳 | 局内相对秒数（env.time） | 局内相对秒数（state.time） |
| 适用场景 | 真实游戏 | 测试和算法优化 |

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
    return self._clock() < self._animation_until

def set_animation_window(self, duration: float = 1.5) -> None:
    """设置动画窗口"""
    self._animation_until = self._clock() + duration
```

动画窗口是**真实耗时测量**（墙钟语义），走注入 clock（默认 monotonic），
不与局内相对时间混算。

### 触发时机

`GameEnv.serve_order()` / `serve_from_cooker()` 内部调用 `set_animation_window(1.5)`；
Runner 的 `_exec_serve_from_cooker` / `_exec_serve_order`（`_serve_with_verify`）执行送餐后，
由 `env.serve_order()` 设置动画窗口。

### 保护范围

1. **扫描循环**：动画期间不检测新订单（防止捕获未刷新的屏幕），睡到窗口结束后唤醒 agent
2. **决策循环**（2026-04-19 优化）：动画期间**允许烹饪**，只**禁止送餐**
3. **Agent 决策**：`_agent_loop` 在动画窗口期间跳过 `ServeOrderAction` / `ServeFromCookerAction`

```python
# runner.py _agent_loop() 中的动画窗口保护
in_animation = self.env.is_in_animation_window()
action = self.strategy.decide(self.env.get_unified_state())
if action:
    action_type = type(action).__name__
    if in_animation and action_type in ("ServeOrderAction", "ServeFromCookerAction"):
        continue  # 跳过送餐，其他动作（烹饪/移动）正常执行
    # ... 执行动作
```

**优化原理**：根据 game_rules.md 规则，动画窗口期间"其他操作不受限"，烹饪是异步的可以让灶台提前工作。

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
    item_name: Optional[str] = None
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

`target_recipe_slug` 是组装站的"灵魂"字段，缺失会导致 Agent 决策链完全瘫痪。以下方法会自动推断配方：

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
    item_name: Optional[str] = None
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

Operator 使用异步锁确保 UI 操作的原子性。锁在**协程层**持有，设备调用在
锁内经 `asyncio.to_thread` 进入 worker 线程（Issue #19 落地后的实际实现；
不在线程内抢 asyncio 锁）：

```python
class Operator:
    def __init__(self, ...):
        self._lock = asyncio.Lock()
    
    async def swipe(self, start, end, duration=0.1) -> None:
        async with self._lock:
            # 执行 swipe 操作（worker 线程，事件循环不停摆）
            await asyncio.to_thread(swipe, start, end, duration=duration)
            await asyncio.sleep(0.01)  # 操作间隔
```

**作用**：
- 防止多个 swipe 操作同时执行
- 避免 UI 冲突和混乱
- swipe 期间 timeout/scan/agent 循环照常推进（锁只串行化 swipe，不冻结循环）

### 频率选择依据

| 循环 | 频率 | 依据 |
|------|------|------|
| 扫描循环 | 0.4s / 0.5s 自适应 | 订单变化较慢，图像检测开销大 |
| 超时循环 | 0.3s | 超时判定时间敏感，独立轮询 |
| 决策循环 | 事件驱动（0.5s 兜底） | 只在状态变化时决策，避免空转 |
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
   ├── 创建 Runner
   ├── 初始化 GameEnv, Scanner, Operator
   └── 创建 Runner 并注入 env

2. 等待游戏开始
   ├── Scanner.detect_timer() 循环检测
   ├── 检测到 timer 图标后等待 3 秒
   └── 调用 env.start_game() 开始计时

3. 游戏运行阶段（三循环并行）
   ├── 扫描循环 (0.4s/0.5s 自适应)
   │   ├── 检查动画窗口（暂停到窗口结束）
   │   ├── Scanner.scan_new_orders()
   │   └── GameEnv.apply_scan_result()（原子同步，新建走 create_order）
   │
   ├── 超时循环 (0.3s)
   │   └── GameEnv.check_and_remove_timed_out_orders()
   │
   └── 决策循环 (事件驱动)
       ├── 等待 _agent_wakeup 事件
       ├── Strategy.decide() → Action
       └── Runner._execute_action()
           ├── UI 操作 (Operator.swipe)
           └── 状态更新 (GameEnv)

4. 游戏结束
   ├── env.is_game_over() 返回 True
   ├── 三循环自动退出
   └── 终局结算 + 返回统计（含 scoring 与 timing）
```
