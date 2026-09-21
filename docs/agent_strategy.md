# Agent 核心算法与策略文档

## 1. 概述

本文档描述 Hawarma 烹饪游戏 Agent 的核心算法设计、策略分析和基准测试结果。

### 1.1 问题定义

- **目标**：在 90 秒内最大化完成订单数和得分
- **约束**：
  - 最多 4 个灶台同时烹饪
  - 食材烹饪完成后 5 秒内必须移走，否则过期
  - 订单有超时时间（普通订单 55-75 秒，Rush 订单 30-45 秒，基于配方总烹饪时长动态计算）
  - 调料必须在食材齐全后才能添加

## 2. 架构

### 2.1 三层架构

```
core/       Strategy 的唯一输入，数据契约
agent/      Strategy 纯决策单元
game/       Env 状态管理 + Runner 编排 + Operator 执行
```

- **Strategy**：`decide(state) -> Action`，纯决策函数，不接触环境
- **Env**：状态管理 + `get_unified_state()` + 统计追踪
- **Runner**：编排扫描循环、超时循环、决策循环，执行 Action

### 2.2 数据流

```
Scanner/Timeout → Env.get_unified_state() → Strategy.decide(state) → Action → Runner.execute(action) → Operator.swipe() + Env.update()
```

### 2.3 动作类型

Actions 定义在 `src/hawarma/core/actions.py`，按 station 分组：

| 类别 | Action | 说明 |
|------|--------|------|
| 基础 | AddCondimentAction | 调味 |
| 基础 | ClearCookerAction | 清理灶台 |
| Gastronome | CookAction | 食材区→灶台 |
| Gastronome | MoveToAssemblyAction | 灶台→组装站 |
| Gastronome | ServeOrderAction | 组装站→取餐台 |
| Gastronome | MoveToStockpileAction | 灶台→库存 |
| Gastronome | PullFromStockpileAction | 库存→组装站 |
| Dessert | *(预留)* | 待开发 |

## 3. 策略

每个 station 只有一个策略（合并后无变体）：

| 注册名 | 类名 | Station | 特点 |
|--------|------|---------|------|
| `gastronome` | `GastronomeStrategy` | 美食站 | 10 级贪心瀑布 + CPM + visibility 阈值跨越 + 单食材优先 + 延迟感知（**默认**） |
| `planner` | `PlannerStrategy` | 美食站 | deadline 感知的滚动时域调度：排列枚举 + 确定性前向仿真（opt-in，Issue #21） |
| `dessert` | `DessertStrategy` | 甜点站 | 搅拌盆流水线决策 |

### 3.1 性能基准

`GastronomeStrategy` 是 6 个历史变体（`GreedyCascade` / `CPMCascade` / `VisibilityAwareCascade` / `CPMEnhancedCascade` / `PreemptScoreCascade` / `DelayAwareCascade`）的最优特性合并结果。合并前 100 局配对 benchmark（vs `GreedyCascadeStrategy` 基线 3736）：

| 变体 | Avg Reward | vs baseline | 合并状态 |
|------|-----------|------------|----------|
| `CPMEnhancedCascadeStrategy` | 3934 | +5.3% ★ | 全部并入 |
| `VisibilityAwareCascadeStrategy` | 3923 | +5.0% | 阈值跨越 `CROSSING_BONUS=5.0` |
| `CPMCascadeStrategy` | 3878 | +3.8% | CPM 评分、assembly 抢占 |
| `DelayAwareCascadeStrategy` | 4711（带 300+400ms 延迟） | +2.1% vs 同延迟基线 | 激进预烹饪/存储阈值 |
| `PreemptScoreCascadeStrategy` | 3793 | +1.5% | 已被 CPM 涵盖，未并入 |
| `GreedyCascadeStrategy` | 3736 | — | 10 级瀑布框架基类 |

> ⚠️ 上表为**口径 v1**（#14 保真度修复前）的历史数据，与当前口径的绝对值不可直接比较。

### 3.1.1 口径 v2（含 #14 保真度修复，2026-09-22）

模拟器修复 4 项与 `docs/game_rules.md` 的机制偏差后，基准绝对值发生变化（**口径 v2**）：

1. `serve_order` 校验组装站食材 (name, cooker_type) 集合与 recipe 完全一致（规则 3.5）
2. 过期食材留在灶台直到显式 `ClearCookerAction`（规则 4.2/9.1，清理按一次操作计 0.3s action_delay）
3. SimEnv 观测路径统一走 1s 新单隐藏（规则 3.4.2，与 `detection_delay` 取 max）
4. serve 禁令窗口（slot 位移 1.5s）与新单可见性窗口（1s）拆分；提交后场上无单立即刷新（规则 3.4.1）

50 局配对 benchmark（seeds 0-49，`python -m playground bench --strategies gastronome --games 50`）：

| 口径 | Avg Reward | Std | Max | Min | Expired/局 | SrvGap | Actions/局 |
|------|-----------|-----|-----|-----|-----------|--------|-----------|
| v1（修复前） | 3703.3 | 862.2 | 5934 | 1823 | 1.6 | 5.1s | 119.4 |
| **v2（修复后，当前）** | 3936.9 | 963.3 | 6868 | 1968 | 1.0 | 4.7s | 127.8 |

解读（v2 相对 v1）：
- **+6.3%**：主要来自"提交后场上无单立即刷新"（旧口径等 1.5s serve 禁令窗口结束才刷单，SrvGap 5.1s→4.7s）
- Expired 1.6→1.0：GastronomeStrategy 的 `_try_clear_expired` 真正生效（旧口径过期即免费自动释放，灶台不会被糊料卡死）
- Actions +8.4/局：清理过期灶台成为真实操作成本（每清 0.3s）
- 10 局抽查 192 次 serve、0 次被新校验拒绝——策略组装流程本身产出完整食材集合，serve 校验不损伤有效路径

### 3.1.2 planner vs gastronome（Issue #21，2026-09-22，不晋升）

`PlannerStrategy`（deadline 感知滚动时域调度，决策逻辑见第 8 节）100 局配对基准
（seeds 0-99，v2 口径，`PYTHONHASHSEED=0`；完整分析见
`experiments/planner_strategy/report.md`）：

| 策略 | Avg Score±Std | served/局 | rush/局 | timeout/局 |
|------|---------------|-----------|---------|-----------|
| gastronome | 7165.2 ± 1572.9 | 17.77 | 1.77 | 0.00 |
| planner    | 7072.4 ± 1610.7 | 17.72 | 1.83 | 0.00 |

配对统计（planner − gastronome）：**Δ = −92.9，t = −0.98，p = 0.3279，
Cohen's d = −0.10，95% CI [−280.2, +94.5]**——统计不可区分，点估计为负。

**结论：未达晋升门槛（需 p<0.05 且 Δ>0），保持 gastronome 默认，planner 为
opt-in**（CLI `--strategy planner` / TUI 配置面板 / config `strategy: planner`）。

要点：
- 当前模拟器参数下（normal 54-105s / rush 32-63s 超时 + 10% rush 率）订单
  deadline 从不约束任一策略（双方 100 局 0 超时），planner 的差异化能力
  （读 `order.timeout_at`、排列级可行性推理）无从体现；差异全部落在吞吐上，
  而吞吐由 0.3s 动作串行 + 1.5s serve 禁令 + 组装站单菜物理决定。
- planner 的 rush 单命中略高（1.83 vs 1.77），单测证明紧截止场景下 planner
  先做低分临期单而 gastronome 选错（tests/test_planner_strategy.py）。
- 实现过程中修正的三个关键点：变体配方共享食材对时环境 `target_recipe_slug`
  锁定规则的镜像（否则 serve 死循环）、深管道预烹饪 + 保护性入库、
  serve 禁令窗口建模——对后续策略开发有复用价值。

### 3.2 策略切换

```bash
# CLI
python -m playground run --strategy gastronome
python -m playground bench --strategies gastronome,planner

# 代码
from hawarma.agent.registry import get_strategy
strategy = get_strategy("gastronome")
```

## 4. 核心优化总结（GastronomeStrategy）

| 优化 | 说明 | 来源 |
|------|------|------|
| SPT 排序 | 最短处理时间优先（关键路径法） | `CPMCascadeStrategy` |
| visibility 阈值 | 跨越阈值订单 CP -5s 加成 | `VisibilityAwareCascadeStrategy` |
| 单食材优先 | 1-ingredient 订单 CP -0.3s | `CPMEnhancedCascadeStrategy` |
| Rush tiebreaker | 同 CP 时 Rush 优先 | 修复后所有变体共有 |
| 调料优先 | 食材齐全时先加调料再烹饪 | `GreedyCascadeStrategy` |
| 最长烹饪优先 | 同订单内先煮最慢的食材 | `GreedyCascadeStrategy` |
| 主动预烹饪 | 灶台空闲时预烹饪（仅 stop_time=15s 前） | `GreedyCascadeStrategy` + `DelayAwareCascadeStrategy` 阈值 |
| 智能存储 | 紧急度排序（needed > near-expired > normal） | `DelayAwareCascadeStrategy` |
| 动画期间烹饪 | 送餐动画不阻塞烹饪 | `GreedyCascadeStrategy` |
| 落地安全窗口 | `_try_move_to_assembly` / `_try_store_to_stockpile` 用 `MOVE_SAFETY_MARGIN=0.5s` 提前收紧过期判定，覆盖 dispatch + swipe + 落地动画的尾段延迟 | 真实游戏观测修复 |

## 5. 效率指标说明

Playground 基准测试输出以下效率指标：

| 指标 | Gastronome（参考值） | 说明 |
|------|---------------------|------|
| Idle% | 60.1% | 灶台空闲时间比例 |
| Expired | 1.2 | 每局食材过期数 |
| ClrAsm | 1.4 | 清空组装站次数（抢占） |
| SrvGap | 4.5s | 两次 serve 平均间隔 |
| None% | 84.8% | 策略返回 None 的步数比 |
| StkIn/Out | 11/10 | 库存进出次数 |
| StkMax | 3.0 | 库存峰值 |

## 6. 运行基准测试

```bash
# 完整基准测试
python -m playground bench --games 100 --strategies gastronome

# 导出 CSV
python -m playground bench --games 100 --csv results.csv

# 单局
python -m playground run --seed 42 --strategy gastronome
```

## 7. 甜点策略

### 7.1 概述

甜点策略（DessertStrategy）是甜点模式的专用策略，采用流水线决策逻辑。与 Gastronome 策略不同，甜点策略专注于搅拌盆和灶台的协同工作。

### 7.2 甜点流程

```
食材区 → 搅拌盆 → 调味 → 搅拌 → 灶台烹饪 → 取餐台
```

### 7.3 决策优先级

甜点策略的决策优先级如下：

| 优先级 | 操作 | 条件 |
|--------|------|------|
| 1 | 送餐（灶台→取餐台） | 灶台完成 + 有匹配订单 |
| 2 | 清理过期灶台 | 灶台过期 |
| 3 | 移动搅拌盆到灶台 | 搅拌完成 + 灶台空闲 |
| 4 | 搅拌 | 食材齐全 + 调料齐全 + 未搅拌 |
| 5 | 添加调料 | 食材齐全 + 调料未齐全 |
| 6 | 添加食材到搅拌盆 | 搅拌盆未满 |
| 7 | 清理搅拌盆 | 无匹配订单 |

### 7.4 流水线决策

甜点策略采用流水线决策逻辑：

- 当当前订单在烹饪时，开始下一个订单的食材收集和搅拌
- 一般同时处理 2 个订单
- rush 订单优先处理，然后先进先出

### 7.5 资源管理

| 资源 | 约束 | 说明 |
|------|------|------|
| 搅拌盆 | 一次只能处理一个订单 | 搅拌盆是共享资源 |
| cooker | 一次只能烹饪一个甜点 | cooker 是共享资源 |

### 7.6 订单优先级

甜点订单的优先级排序：

1. **rush 订单优先**：rush 订单始终最高优先级
2. **先进先出**：相同优先级的订单按到达顺序处理
3. **超时时间**：即将超时的订单优先处理

### 7.7 状态追踪

甜点策略使用隐式状态追踪：

- **MixingBowlState**：追踪搅拌盆状态（食材、调味品、是否搅拌完成）
- **CookerState**：追踪 cooker 状态（复用现有）

### 7.8 错误处理

甜点策略的错误处理策略：

- 操作失败时记录日志
- 不实现重试机制
- 假设所有操作都成功
- 关注游戏逻辑的正确性

### 7.9 配置

甜点策略的配置在 `configs/config.yaml` 的 `stations.dessert` 节：

```yaml
stations:
  dessert:
    enabled: true
    # 搅拌参数（distance/duration/steps）使用 StirAction 默认值（400/1.5/10），
    # Issue #22 移除从未被消费的死配置 StirConfig
    mixing_bowl_position:  # 搅拌盆屏幕坐标
      - 1245
      - 870
    cookers_positions:     # 甜点灶台固定坐标
      dessert_oven:
        - 715
        - 615
      cooling_plate:
        - 1260
        - 590
    cooker_retention: 5.0  # 甜点灶台食材停留时间
```

### 7.10 使用方法

```bash
# CLI（station 模式默认为 gastronome）
python -m hawarma --station dessert --strategy dessert

# TUI
python -m hawarma.tui  # 在配置面板中选择 station 和 strategy

# 代码
from hawarma.agent.registry import get_strategy
strategy = get_strategy("dessert")
```

### 7.11 未来扩展

甜点策略支持未来扩展：

- 支持更多甜点类型：只需在 `recipes.json` 中添加新的甜点菜谱
- 可配置参数：搅拌参数、位置参数、超时参数都可配置
- 架构易于扩展：策略设计支持未来添加新的决策逻辑

## 8. Planner 策略（deadline 感知的滚动时域调度，Issue #21）

### 8.1 概述

`PlannerStrategy`（注册名 `planner`，`src/hawarma/agent/strategies/planner.py`）
与 gastronome 的单动作贪心瀑布互补：每个决策周期对当前活跃订单（≤4）枚举完成
顺序（排列 ≤24），对每个排列做**确定性前向仿真**，输出最优排列的首个原子动作，
下周期滚动重规划。GastronomeStrategy 类零改动（独立实现同型辅助）。

### 8.2 决策流程

```
decide(state)
  1. 反应式安全层（语义与 gastronome 顶层一致）
     a. 组装站齐料齐调料 → ServeOrderAction（动画窗口内禁；同配方多单选 unit 最高）
     b. 灶台过期 → ClearCookerAction
     c. 组装站食材齐 + 目标配方有活跃订单 → 补第一味缺失调料
  2. 规划层：排列枚举 + 前向仿真（纯 Python 世界模型，非 GameSimulator）
  3. 空闲回退（trace 无立即动作时，gastronome 同型启发式）
     a. 紧急入库（剩余窗口 < 2.5s 的无主 done 食材）
     b. 预烹饪（先活跃配方后全部配方，最长 duration 优先；终局可行性已由规划层处理）
     c. 非紧急入库
```

### 8.3 前向仿真（执行器规则）

时间口径沿用 gastronome 的 0.3s/动作（与模拟器 action_delay=0.3 一致）；
cook 落地 p+0.3 起算 done/expired（5s 窗口）；move/pull 落地需 0.5s 安全余量；
serve 落地需 0.45s 余量且在 min(timeout_at, game_duration-0.3) 前；
serve 落地后 1.5s 禁令窗口禁下一次 serve（期间可做其他动作）。

对排列中第 k 个订单按序取第一个可用动作：

| 优先级 | 动作 | 条件 |
|--------|------|------|
| 0 | clear assembly | 组装站食材对本单非子集，或 target_recipe_slug 锁定其他配方 |
| 剪枝 | 跳过记违约 | 最早完成时间下界 ≥ 截止（deadline 已过的不进排列） |
| 1 | move（EDF） | 缺失对在绑定灶上已 done 且落地安全 |
| 2 | cook / evict | 缺失对需新烹饪（duration 降序）；绑定灶被占：过期→clear、可收→store、否则等过期 |
| 3 | pull | 缺失对在库存 |
| 4 | 深管道 cook | 为排列中后续订单开火（绑定灶空闲 + 该单截止可达）；过期窗口不限制深度，由规则 5 入库接力 |
| 5 | 保护性 store | 后续订单需要、撑不到其估计使用时刻的 done 食材 → 入库 |
| 6 | wait | 推进到最近烹饪完成/过期事件 |
| 尾 | 调料→serve | 齐料后按配方补调料，serve（前 ≤1 次为后续订单开火） |

**target_recipe_slug 感知**（关键正确性点）：变体配方共享食材对
（如 snowSkinMooncakeCocoa/Rice）时，环境的 target 由首个入空站食材按 slot 序
锁定，可能与排列头单不同而使 serve 被拒。仿真镜像该规则并在不一致时切换服务
对象，保证与真实 serve 校验一致。

### 8.4 排列评分

```
score = Σ_served (unit + vis) · exp(-0.01 · (t_serve - t_now))   # 早送贴现（vis 同贴现：早跨阈值）
      - Σ_lost   unit                                            # deadline 违约按超时损失计
      - 30 · [需先清空当前非空组装站]                              # 滚动重规划滞回
```

unit = (base_with_cond + vis_with_cond) × multiplier(订单生成时锁定的
spawned_at_visibility, is_rush)，由 RecipeRewardLookup 查表。同分取枚举序首个，
确定性。

### 8.5 复杂度与契约

24 排列 × ≤4 订单 × ≤8 食材 × O(灶数) 集合运算，实测单次 decide() ~1-3ms
（< 100ms 预算，tests/test_planner_strategy.py 断言）。只读 UnifiedState
（recipes 直读 `state.recipes`），产出 core/actions.py 现有 Action 类型；
decide() 不修改 state（含嵌套对象，#16）。

### 8.6 基准结果

见 3.1.2：与 gastronome 统计不可区分（p = 0.33），不晋升、保持 opt-in；
设计文档与完整失败案例分析见 `experiments/planner_strategy/`。
