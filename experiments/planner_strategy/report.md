# planner 策略实验报告（Issue #21）

日期：2026-09-22 ｜ 代码：`src/hawarma/agent/strategies/planner.py`（注册名 `planner`）
基准：`feat/issue-21-planner-strategy` @ main `6b298f8` + 本分支提交

## 1. 结论（TL;DR）

**未达晋升门槛，保持 gastronome 默认、planner 为 opt-in。**

100 局配对基准（seeds 0-99，final_score v2 口径）：

| 策略 | Avg Reward±Std | Max | Min | served/局 | timeout/局 |
|------|---------------|-----|-----|-----------|-----------|
| gastronome | 7165.2 ± 1572.9 | 11573 | 3639 | 17.77 | 0.00 |
| planner    | 7072.4 ± 1610.7 | 11347 | 3374 | 17.72 | 0.00 |

配对统计（planner − gastronome）：**Δ = −92.9，t = −0.98，p = 0.3279，
Cohen's d = −0.10，95% CI [−280.2, +94.5]**。

Δ<0 且 p>0.05：差异不显著、点估计为负 → 按晋升规则不晋升。未做任何挑种子
操作（所有参数以 seeds 0-49 开发、seeds 50-99 out-of-sample 验证，见 §4）。

## 2. 实验设置

- 命令（worktree 根目录执行；**必须 `PYTHONPATH=src`**——共享 venv 的 editable
  安装指向主仓，不加前缀会基准到主仓代码（planner 不存在，直接报错）；
  `PYTHONHASHSEED=0` 消除 gastronome 预烹饪分支 set 迭代序的过程间抖动，
  tests/test_gastronome_golden.py 对此有明确记载）：

  ```bash
  PYTHONHASHSEED=0 PYTHONPATH=src python -m playground bench \
      --strategies planner,gastronome --games 100 \
      --csv experiments/planner_strategy/bench_v2.csv
  ```

- 统计口径：#15（final_score v2 = 逐单得分和 + 终局 visibility），配对双侧 t
  （df=99）+ 配对 Cohen's d + Δ 均值 95% CI，由 `playground/bench/stats.py` 计算。
  CRN 局限：共享 seed 只配对初始条件，策略动作使随机流发散，p 值为近似值。
- 稳健性复核：不固定 PYTHONHASHSEED 重跑一次，planner 7072.4 vs gastronome
  7091.3（该次 gastronome 自身因 hash 序抖动 −74），Δ ≈ −19～−93、
  p = 0.33～0.77 —— 结论对 hash seed 不敏感：**两者在本模拟器上统计不可区分**。

## 3. 迭代记录（design → 实现中发现并修正）

| # | 问题 | 症状（50 局开发集） | 修正 |
|---|------|---------------------|------|
| 1 | serve 死循环：变体配方（snowSkinMooncakeCocoa/Rice 等共享食材对）下，环境 `target_recipe_slug` 按首个入空站食材的 slot 序锁定，与排列头单不同 → serve 被环境拒绝并无限重试 | seed 3 单局 146 次失败 serve，-4844 | 仿真镜像环境 target 规则（move→slot 序、pull→recipes 序），首个食材入空站后按 target 切换服务对象（-338 → 稳定） |
| 2 | 逐单串行处理：只为一单预烹饪且受同灶冲突阻塞 | SrvGap ~6.9s vs gastronome ~3s，seed 7 -3386 | 深管道（为排列中所有后续订单开火）+ 保护性入库接力 5s 过期窗口 |
| 3 | serve 禁令窗口（1.5s）未建模 | 多单时间线失真 | 落地后 1.5s 禁下一次 serve（期间可做其他动作） |
| 4 | 终局预烹饪过早停止（沿用 gastronome 的 15s）且空闲回退先入库后开火 | 80-89s 桶动作数 353→268，中段也亏 | PRECOOK_STOP_TIME 15→5（终局可行性已由规划层的 game_duration 钳制处理）；先开火后入库（紧急入库除外）。两项合计 -320 → -81 |
| 5 | 终局 visibility 不参与排序贴现 | seed 49：同 serve 数 -1551（低 vis 单抢先，阈值跨越延迟） | (unit+vis) 一体贴现 |

参数终值：`TIME_DISCOUNT=0.01/s`、`ASSEMBLY_CLEAR_PENALTY=30`、
`PRECOOK_STOP_TIME=5.0`、`STORE_RISK_WINDOW=2.5`、`LOSS_PENALTY_FACTOR=1.0`、
serve 落地余量 0.45s、动作口径 0.3s（与模拟器 action_delay 一致）。

## 4. 参数调优纪律（out-of-sample 验证）

- λ ∈ {0.005, 0.01, 0.02, 0.03, 0.05}：Δ 全部落在 [-338, -249]，不敏感，取 0.01。
- PRECOOK_STOP_TIME ∈ {0..15}：≤6 显著优于 ≥8（终局空转），取 5.0。
- STORE_RISK_WINDOW：开发集（seeds 0-49）上 4.0 最好（-42 vs 2.5 的 -81），
  **但 out-of-sample（seeds 50-99）反向（-127 vs -105）→ 判定过拟合，弃用，
  保留有原理依据的 2.5（≈ 5s 过期窗口的一半）**。未用任何 seed 子集挑选结果。

## 5. 失败案例分析（script.py，100 局事件级统计）

### 每局 served/timeout 对比

- served：planner 17.72 vs gastronome 17.77（Δ = −0.05/局；
  planner 更好 33 局 / 更差 37 局 / 持平 30 局 —— 基本是抛硬币）
- rush 单服务：planner 1.83 vs gastronome 1.77（planner 略优——评分含 rush 倍率）
- timeout：**双方均 0**（deadline 违约分布：{0 次: 100 局}，两策略相同）
- 食材过期：1.34 vs 1.31/局；SrvGap 4.79s vs 4.75s；Idle% 63.8 vs 63.7

### deadline 违约分布与不可行订单

当前模拟器参数下（normal 54-105s、rush 32-63s 超时 + 10% rush 率 + ~4s 刷新），
订单 deadline **从不约束**任一策略（0 违约/100 局）——这正是 planner 的差异化
能力（读 `order.timeout_at`、排列级可行性剪枝）在本基准上无从体现的原因；
单测 `test_planner_prioritizes_deadline_critical_order` 构造的紧截止场景
（9s 内可完成的低分单 vs 高分余量大单）证明了该能力本身正确工作，
且 gastronome 在同状态下确实选错（先做高分单导致低分单违约）。

### 最差 5 局（planner 视角）

| seed | Δ | gastronome | planner | 主因 |
|------|-----|-----------|---------|------|
| 7 | −3071 | 8820 (s23, rush4) | 5749 (s17, rush3) | 订单流被 4×feastOfLoyalty（共用 pot/grill，5s 串行）占据：planner 服务周期 ~6.9s → 刷单慢 → 抽卡运气主导；gastronome 更快 cadence 触发更多刷新，随机流发散后抽到混合配方流 |
| 27 | −2955 | 8681 (s18) | 5726 (s14) | 同类：长烹饪配方连击，吞吐受物理灶台约束 |
| 67 | −1738 | 7324 (s18, rush2) | 5586 (s17, rush0) | 少拿 2 个 rush 单（×2.5 倍率 ≈ 700 分） |
| 37 | −1736 | 11573 (s18, rush5) | 9837 (s17, rush4) | 高倍率区间少 1 单 |
| 96 | −1719 | 10422 (s17, rush4) | 8703 (s16, rush2) | 同上 |

共性：损失集中在**吞吐（serve 数）与 rush 单命中**，而非 deadline 或过期；
根因是同灶配方连击时 planner 的服务周期略长，而服务周期又通过"场上空→立即
刷新"机制自我放大（慢 → 刷单少 → 抽卡方差大）。

## 6. 为什么 planner 没能赢（机理讨论）

1. **本模拟器是吞吐约束而非 deadline 约束**：0 超时意味着"读 deadline、排列级
   可行性推理"这一核心差异点没有用武之地；两者的差异全部落在吞吐上，而吞吐
   由"0.3s 动作串行 + 1.5s serve 禁令 + 组装站单菜"物理决定，贪心瀑布已接近
   该约束下的操作序列最优。
2. **信息优势已被 gastronome 的启发式吸收**：CPM + visibility 跨越 + rush
   tiebreaker 已经隐式近似了"先做快单/高倍单"；planner 的显式排列枚举在
   ≤4 单的规模上与贪心的近似差距小于模型误差（0.3s 动作口径 vs 实际 0.4s、
   随机流发散）。
3. **规划是模型内的最优**：前向仿真对刷单流（未知）只能用贴现近似，
   滚动重规划再好也追不上贪心对每个即时状态的零模型成本反应。

## 7. 适用性判断（planner 的预期优势场景）

以下场景未被当前基准覆盖，是 planner 设计上的优势区，留待真实端验证：

- **deadline 紧的环境**：rush 密度 >10%、或更高难度下 timeout 更短时，
  "低分临期单 vs 高分余量单"的取舍会真实出现（单测场景即为此）；
- **多配方异构灶台**：当前 4 配方常出现共用灶台的连击流，规划层对灶台冲突的
  让位（store/等过期/clear）与深管道缓冲已建模，但收益被物理串行掩盖；
- **visibility 阈值跨越敏感的局**：(unit+vis) 贴现使 planner 在阈值边缘的
  排序更稳定（rush 单服务数 1.83 vs 1.77 已有体现）。

## 8. 复现

```bash
cd <worktree>
PYTHONHASHSEED=0 PYTHONPATH=src python -m playground bench \
    --strategies planner,gastronome --games 100 \
    --csv experiments/planner_strategy/bench_v2.csv     # 主口径
PYTHONHASHSEED=0 python experiments/planner_strategy/script.py  # 事件级失败分析
```

测试：`python -m pytest tests -q`（260 passed + 2 skipped，
含 tests/test_planner_strategy.py 14 项）。

## 9. 决定

- `configs/config.yaml` 默认 `strategy: gastronome` **不变**（该文件不入库，
  实际默认值在 `src/hawarma/config.py` 的 `AppConfig.strategy`，同样保持
  `gastronome`）；planner 为 opt-in：CLI `--strategy planner` / TUI 配置面板 /
  config `strategy: planner` 均可切换。
- docs/agent_strategy.md 已记录 planner 决策逻辑一节与本实验数字。
