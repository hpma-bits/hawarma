# tests/ 目录架构

## 目录职责
测试模块，包含单元测试和集成测试，验证环境模拟器、图像检测、Agent 策略等组件的正确性。

## ⚠️ 重要提示

**一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**

## 📄 文件清单

 | 文件名 | 状态 | 用例风格 | 功能 |
|--------|------|------|------|
| `__init__.py` | ✅ | - | 包初始化 |
| `conftest.py` | ✅ | pytest | 共享夹具：autouse 保存/恢复 i18n 全局语言（Issue #22，防 test_i18n 直接 set_language 的跨文件泄漏） |
| `test_action_dispatch.py` | ✅ | pytest | Action 调度表达与双端对齐测试（Ticket #11：类型/优先级/取消、共享调度、Runner 跳过取消、SimEnv 直调序列、双端回放终局一致） |
| `test_assembly_verifier.py` | ✅ | unittest | 组装站验证器测试 |
| `test_bench_stats.py` | ✅ | unittest | 基准统计单测（Issue #15：t 分布 CDF/分位数对照 t 表、配对检验 p/Cohen's d/CI、零方差退化、final_score 统一口径、MetricsCollector 首帧空闲） |
| `test_dessert_detection.py` | ✅ | unittest | 甜点订单检测测试 |
| `test_dessert_strategy.py` | ✅ | unittest | Dessert 策略测试（决策优先级） |
| `test_device_io_async.py` | ✅ | unittest | 设备 IO 异步化并发性测试（Issue #19：慢 swipe/慢 snapshot 假设备 + 心跳协程并发，断言 IO 窗口内心跳 ≥2 次；含锁串行化与计时覆盖断言） |
| `test_env_simulator.py` | ✅ | pytest | 环境模拟器测试（基础结构、时间限制、订单生成、并行烹饪、错误处理；fixture 已对齐统一 Recipe 模型，Refs #10） |
| `test_execution_timing.py` | ✅ | pytest | 执行耗时观测 + SrvGap/Idle 分布直方图测试（Ticket #9） |
| `test_execution_timing_baseline.py` | ✅ | unittest | 送餐与滑动耗时基线回归（Ticket #12） |
| `test_final_scoring.py` | ✅ | pytest | 终局计分与度量抽离测试（Ticket #8） |
| `test_final_scoring_regression.py` | ✅ | unittest | 终局结算回归护栏（Ticket #12：一次加总且幂等、同种子确定性、双端同一账本终局一致） |
| `test_gastronome_golden.py` | ✅ | unittest | Gastronome 金决策快照回归（Ticket #12：10 个固定场景决策与 `golden/gastronome_decisions.json` 快照相等） |
| `test_i18n.py` | ✅ | unittest | i18n 测试（locale 键集合一致性、UI 静态键存在性、各 locale 下 TUI 全屏导航） |
| `test_mixing_bowl.py` | ✅ | unittest | 搅拌盆相关测试 |
| `test_order_lifecycle.py` | ✅ | unittest | 订单生命周期竞态回归（Issue #18：防复活/连续 2 次未扫到才删除/同名单多单不串单/serve 按 id 结算/create_order 超时查表与 fallback；假时钟确定性构造竞态场景） |
| `test_recipe_detection.py` | ✅ | unittest | 配方检测测试 |
| `test_real_env_scoring.py` | ✅ | pytest | 真实环境得分测试（on_order_served 精确计分、spawned_at_visibility 不可变） |
| `test_rush_detection.py` | ✅ | unittest | 加急订单像素检测测试（基于红色通道阈值检测 rush 状态） |
| `test_rush_tiebreaker.py` | ✅ | unittest | Rush/visibility 跨越对订单排序影响的测试 |
| `test_sim_fidelity.py` | ✅ | unittest | 模拟器保真度测试（Issue #14：serve 食材集合校验、过期占灶、1s 新单可见性、serve 禁令/立即刷新双窗口） |
| `test_state_snapshot.py` | ✅ | unittest | 状态快照回归测试（Issue #16：各模型 snapshot() 字段拷贝与冻结字段语义、GameEnv/SimEnv get_unified_state() 深快照篡改不污染 env、性能粗测探针） |
| `test_timer_detection.py` | ✅ | unittest | Timer 图标模板匹配测试（验证 icon-timer.jpg 在截图中的检测） |
| `test_tui.py` | ✅ | unittest | TUI 测试 |
| `test_tui_order_input.py` | ✅ | unittest | TUI 订单输入测试 |
| `test_tui_vs_cli_order.py` | ✅ | unittest | TUI 与 CLI 订单构建一致性测试 |
| `test_validate_order_input.py` | ✅ | unittest | 订单输入校验测试 |
| `golden/` | ✅ | 数据 | 金决策快照数据（`gastronome_decisions.json`；再生成方式见 `test_gastronome_golden.py` 文件头注释） |
| `testset/` | ✅ | 数据 | 测试图片集（包含 normal/rush 订单截图） |

> **跑器说明（Issue #10 起统一）**：统一跑器为 **pytest**，一条命令同时收集上表两种风格的用例；
> "用例风格"列仅表示写法（unittest.TestCase 子类 / 纯 pytest 类），不代表需要分跑器运行。

## 测试覆盖

1. **基础结构测试** — 事件创建、配方创建、状态初始化
2. **游戏时间限制测试** — 90 秒游戏时长、结束条件
3. **自动订单生成测试** — 4 秒间隔、槽位填充、刷新规则
4. **并行烹饪测试** — 多灶台同时工作
5. **积分系统测试** — 得分计算
6. **错误处理测试** — 无效输入、资源冲突
7. **图像检测测试** — Timer 图标匹配、Rush 订单检测
8. **组装站验证测试** — Verifier 图像检测
9. **终局结算回归** — 一次加总、幂等、同种子双端一致（#12）
10. **耗时基线回归** — swipe 往返与送餐各分段有记录且在合理区间（#12）
11. **金决策快照回归** — Gastronome 给定状态决策与快照相等（#12）
12. **模拟器保真度测试**（#14）— serve 食材集合校验、过期食材占灶直到显式清理、新单 1s 可见性（与 detection_delay 取 max）、serve 禁令窗口与立即刷新独立
13. **基准统计测试**（#15）— t 分布分位数对照 t 表、配对 p/效应量/CI、零方差退化、统一分数口径
14. **状态快照回归**（#16）— UnifiedState 观测不可变：模型 snapshot() 深拷贝、双端 env 篡改观测不污染内部状态、快照耗时量级探针（< 0.5ms/次，实测约 0.03-0.05ms）
15. **设备 IO 并发性测试**（#19）— Operator.swipe / Runner 验证路径 / Scanner 调试保存移出事件循环后，IO 期间心跳协程照常推进（含同步阻塞反例对照）

## 运行测试

统一跑器为 **pytest**（Issue #10）：pyproject.toml 已配置 `testpaths = ["tests"]` 与 `pythonpath = ["src"]`，在仓库根目录直接运行。

```bash
# 全部测试（统一跑器，含 unittest 风格与纯 pytest 风格用例）
pytest tests

# 单个文件
pytest tests/test_sim_fidelity.py

# 详细输出
pytest tests -v

# 兼容备注：unittest 风格用例仍可用 `python -m unittest discover tests` 运行
# （仅收集 TestCase 子类，不含纯 pytest 风格文件）
```

### 风格门禁（Issue #10）

```bash
ruff check src tests playground     # 语法错误/未定义名等低级问题，合入前必须通过
mypy                                # 类型检查，告警模式（输出现状报告，暂不卡合入）
```
