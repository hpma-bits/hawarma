# 实验：planner 策略（deadline 感知的滚动时域调度，Issue #21）

## 目的

GastronomeStrategy 是单动作贪心瀑布：每步只问"现在哪个动作优先级最高"，从不读
`order.timeout_at`，不推理"哪些订单子集能在各自截止前完成"，也不规划多订单间的
灶台/组装站/库存资源分配。本实验构建 `PlannerStrategy`（注册名 `planner`）——
在相同决策预算（单次 decide() < 100ms）内做**序列级规划**，并在 100 局配对基准上
与 gastronome 比较终局分（final_score，v2 口径）。

## 假设

在订单 deadline 异质（rush 30-45s / normal 55-75s、随配方变化）的场景下，
显式的完成顺序规划能减少"追高分配方导致低分临期订单超时"的损失，并通过对
后续订单的管道式预烹饪维持灶台利用率，从而提高平均终局分。

## 策略设计（src/hawarma/agent/strategies/planner.py）

### 1. 反应式安全层（语义与 gastronome 顶层一致，独立实现）

规划无收益、正确性关键的动作直接同型处理，优先于规划层：

1. **送餐**：组装站食材 (name, cooker) 集合与某活跃订单配方完全一致且调料齐
   → ServeOrderAction（`is_in_animation_window` 期间不发；同配方多单时选
   unit score 最高者，倍率按订单生成时锁定的 `spawned_at_visibility`）。
2. **清过期灶台**：`cooker.is_expired(state.time)` → ClearCookerAction。
3. **调料补齐**：组装站食材齐且目标配方（target_slug 或精确推断）仍有活跃订单
   → 补第一味缺失调料。

GastronomeStrategy 类本身零改动（不继承、不提取公共基类，planner 独立实现同型
辅助，选侵入最小的方案）。

### 2. 规划层：排列枚举 + 确定性前向仿真

- 活跃订单（≤4，slot 可见且未 done）枚举完成顺序，≤24 个排列；deadline 已过的
  订单不进排列（其损失对一切排列为常数）。
- 每个排列在**纯 Python 世界模型**（dict/tuple/Counter，不复用 GameSimulator）
  上做事件驱动的确定性前向仿真，产出动作轨迹 trace = [(emit_time, action), ...]。
- 时间口径：每个动作（cook/move/pull/condiment/serve/store/clear）耗时 0.3s，
  与模拟器 action_delay=0.3 一致；cook 落地时刻 p+0.3 起算
  done_at = p+0.3+duration，expired_at = done_at+5.0；move/pull 落地要求
  p+0.3+0.5 < expired_at（沿用 gastronome 落地安全窗口）；serve 落地要求
  p+0.3+0.45 < min(timeout_at, game_duration-0.3)（0.45 覆盖模拟器每步额外的
  0.1s tick 粒度）；serve 落地后 1.5s slot 位移动画期间禁下一次 serve
  （期间可烹饪/移动/调味——与规则 8 一致）。

**执行器规则**（处理排列中第 k 个订单时，按序取第一个可用动作）：

1. 组装站归属：组装站非空且（食材对不是第 k 单配方的子集，**或
   `target_recipe_slug` 锁定为其他配方**）→ 先 ClearAssembly。
2. 下界剪枝：最早可完成时间下界（串行动作数 + 最长剩余烹饪 + 调料 + serve）
   ≥ 截止 → 该单在本排列下记为违约（损失 = unit score），跳过不追。
3. 取料动作优先级：
   a. **move**：缺失食材对恰在其绑定灶上且已 done 且落地安全 → 移入组装站
      （EDF：先移最早过期者）；
   b. **cook/evict**：需新烹饪的缺失对按 duration 降序开火；绑定灶被占时：
      占位者过期 → clear，可入库 → store，否则等待其过期；
   c. **pull**：缺失对在库存 → 取出；
   d. **深管道预烹饪**：为排列中**所有后续订单**开火（绑定灶空闲 + 该单截止
      仍可达）；过期窗口不限制深度——撑不到直接使用的食材由保护性入库接力
      （store→pull 共 0.6s，库存不过期），这正是库存对 5s 窗口的扩展作用；
   e. **保护性入库**：后续订单需要、但撑不到其估计使用时刻的 done 食材 → 入库；
   f. **wait**：推进到最近的烹饪完成/过期事件（超过该单截止则记违约跳过）。
4. 食材齐 → 按配方补缺失调料 → serve（serve 前 ≤1 次为后续订单开火：0.3s 顺延
   换 5s 级烹饪提前启动，截止余量足够才做）。

**target_recipe_slug 感知**（关键正确性点）：变体配方共享食材对
（snowSkinMooncakeCocoa/Rice、mooncake 系）时，环境的 target 由**首个入空站的
食材**按 slot 序锁定，可能与排列头单不同，serve 会被环境
`target == order.recipe` 校验拒绝。仿真镜像该环境规则：首个食材入空站时按
slot 序（move 路径）/recipes 迭代序（pull 路径）推定 target，若指向其他活跃
订单则切换当前服务对象，保证仿真与真实 serve 校验一致，避免 serve 死循环。

### 3. 排列评分

```
score(perm) = Σ_served  (unit_i + vis_i) · exp(-λ · (t_serve_i - t_now))
             - Σ_lost    LOSS_FACTOR · unit_i                       # deadline 违约 = 超时损失
             - CLEAR_PENALTY  [若该排列要先清空当前非空组装站]        # 滚动重规划滞回，防抖
```

- `unit_i = (base_with_cond + vis_with_cond) × multiplier(spawned_at_visibility_i,
  is_rush_i)`，由 RecipeRewardLookup 查表（加成按订单生成时锁定的区间，与
  core/reward.py 的加成表一致）；
- `vis_i = visibility_with_cond`（planner 总是补齐调料），与 unit 一体贴现：
  早送高 vis 单更早跨 visibility 阈值，放大后续新单倍率；
- 贴现率 λ（TIME_DISCOUNT，默认 0.01/s）是主要可调参数：早送 → 场上空 → 新单
  早刷新（#14 后"提交后场上无单立即刷新"已生效）；
- 同分取枚举序（订单按 order_id 排序后 itertools.permutations）首个，保证确定性。

### 4. 执行与滚动

输出最优排列 trace 中第一个 `emit_time ≤ now` 的动作（无则进入空闲回退）；
下一决策周期对新订单/新状态滚动重规划。

### 5. 空闲回退（规划层不好表达的部分，gastronome 同型启发式）

trace 无立即动作（全部在等烹饪）时，按序：

1. **紧急入库**：灶上 done、不被任何活跃订单需要、剩余窗口 < 2.5s（STORE_RISK_WINDOW）
   且库存可收 → MoveToStockpile；
2. **预烹饪**（先于非紧急入库——5s 级烹饪早 0.3s 启动的价值 > 入库提前）：
   剩余游戏时间 > 5s（终局可行性已由规划层的 game_duration 钳制处理，空闲回退
   只需保持忙碌到最后一轮可落地烹饪）、有空闲灶、库存总量 < 4 → 先活跃订单配方、
   后全部配方，最长 duration 优先开火；
3. **非紧急入库**：无可预烹饪时回收 done 的多余食材。

### 6. 数据契约

只读 UnifiedState（recipes 直读 `state.recipes`），产出 core/actions.py 现有
Action 类型；真实端不会比模拟器多任何信息。decide() 不修改 state（含嵌套对象）。

## 复杂度预算

24 排列 × ≤4 订单 × ≤8 食材 × 每步 O(灶数) 集合运算，实测单次 decide() ~1-3ms
（断言 < 100ms，见 tests/test_planner_strategy.py 性能用例）。

## 实验方法

- 命令（注意必须 `PYTHONPATH=src`：共享 venv 的 editable 安装指向主仓，
  不加前缀会基准到主仓代码；`PYTHONHASHSEED=0` 消除 gastronome 预烹饪
  set 迭代序的过程间抖动，见 report.md）：
  `PYTHONHASHSEED=0 PYTHONPATH=src python -m playground bench --strategies planner,gastronome --games 100 --csv experiments/planner_strategy/bench_v2.csv`
- 配对统计（#15 口径）：Δ 均值、双侧配对 t（df=n-1）、Cohen's d、95% CI，
  由 playground/bench/stats.py 计算；script.py 复跑并附加每局 served/timeout
  对比与失败案例分析（不可行订单、deadline 违约分布）。
- **晋升规则**：p < 0.05 且 Δ > 0 → configs 默认 strategy 改 planner 并同步
  AGENTS.md 与 docs/agent_strategy.md；否则保持 gastronome 默认、planner 为
  opt-in。两种结果都在 docs/agent_strategy.md 写实验结论与数字。
- 参数调优纪律：所有参数对比以 50 局（seeds 0-49）开发集筛选、**seeds 50-99
  out-of-sample 验证**，禁止挑种子凑显著（一次 4.0s 入库窗口的"最优"在
  out-of-sample 上反向，已弃用，见 report.md）。

## 迭代记录（design → 实现中发现并修正）

1. serve 死循环（变体配方 target 失配）→ 第 2 节 target 感知仿真；
2. 逐单串行处理导致灶台利用率不足 → 深管道（规则 3d）+ 保护性入库（3e）；
3. serve 禁令窗口（1.5s）未建模 → 多单时间线失真 → 已补；
4. 终局预烹饪过早停止（15s）导致末段 34s 空转 → PRECOOK_STOP_TIME 15→5s
   （规划层已按 game_duration 钳制终局可行性，空闲层无需重复保守）；
5. 空闲回退先入库后开火 → 烹饪启动被 0.3s 顺延 → 改为先开火（紧急入库除外）。

## 预期结果

planner 在 rush 单密集的局中减少临期订单超时（orders_timeout 下降）、
SrvGap 持平或略降；平均终局分 Δ > 0。风险：贴现/清站罚参数失当时，
清站-重建抖动或过度保守会吃掉收益。
