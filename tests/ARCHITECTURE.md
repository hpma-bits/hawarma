# tests/ 目录架构

## 目录职责
测试模块，包含单元测试和集成测试，验证环境模拟器、图像检测、Agent 策略等组件的正确性。

## ⚠️ 重要提示

**一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**

## 📄 文件清单

 | 文件名 | 状态 | 跑器 | 功能 |
|--------|------|------|------|
| `__init__.py` | ✅ | - | 包初始化 |
| `test_action_dispatch.py` | ✅ | pytest | Action 调度表达与双端对齐测试（Ticket #11：类型/优先级/取消、共享调度、Runner 跳过取消、SimEnv 直调序列、双端回放终局一致） |
| `test_assembly_verifier.py` | ✅ | unittest | 组装站验证器测试 |
| `test_dessert_detection.py` | ✅ | unittest | 甜点订单检测测试 |
| `test_dessert_strategy.py` | ✅ | unittest | Dessert 策略测试（决策优先级） |
| `test_env_simulator.py` | ✅ | pytest | 环境模拟器测试（基础结构、时间限制、订单生成、并行烹饪、积分系统） |
| `test_execution_timing.py` | ✅ | pytest | 执行耗时观测 + SrvGap/Idle 分布直方图测试（Ticket #9：分段耗时聚合、动画窗口剩余、SrvGap/Idle 分桶守恒） |
| `test_execution_timing_baseline.py` | ✅ | unittest | 送餐与滑动耗时基线回归（Ticket #12：真实 Operator/Runner 路径打桩驱动，断言各分段有记录且在宽松合理区间，不设阈值） |
| `test_final_scoring.py` | ✅ | pytest | 终局计分与度量抽离测试（Ticket #8：终局含 visibility、finalize 幂等、scoring_version 隔离） |
| `test_final_scoring_regression.py` | ✅ | unittest | 终局结算回归护栏（Ticket #12：一次加总且幂等、同种子确定性、双端同一账本终局一致） |
| `test_gastronome_golden.py` | ✅ | unittest | Gastronome 金决策快照回归（Ticket #12：10 个固定场景决策与 `golden/gastronome_decisions.json` 快照相等） |
| `test_i18n.py` | ✅ | unittest | i18n 测试（locale 键集合一致性、UI 静态键存在性、各 locale 下 TUI 全屏导航） |
| `test_mixing_bowl.py` | ✅ | unittest | 搅拌盆相关测试 |
| `test_recipe_detection.py` | ✅ | unittest | 配方检测测试 |
| `test_real_env_scoring.py` | ✅ | pytest | 真实环境得分测试（on_order_served 精确计分、spawned_at_visibility 不可变） |
| `test_rush_detection.py` | ✅ | unittest | 加急订单像素检测测试（基于红色通道阈值检测 rush 状态） |
| `test_rush_tiebreaker.py` | ✅ | unittest | Rush/visibility 跨越对订单排序影响的测试 |
| `test_timer_detection.py` | ✅ | unittest | Timer 图标模板匹配测试（验证 icon-timer.jpg 在截图中的检测） |
| `test_tui.py` | ✅ | unittest | TUI 测试 |
| `test_tui_order_input.py` | ✅ | unittest | TUI 订单输入测试 |
| `test_tui_vs_cli_order.py` | ✅ | unittest | TUI 与 CLI 订单构建一致性测试 |
| `test_validate_order_input.py` | ✅ | unittest | 订单输入校验测试 |
| `golden/` | ✅ | 数据 | 金决策快照数据（`gastronome_decisions.json`；再生成方式见 `test_gastronome_golden.py` 文件头注释） |
| `testset/` | ✅ | 数据 | 测试图片集（包含 normal/rush 订单截图） |

> **跑器说明**：`python -m unittest discover tests` 只收集 unittest.TestCase 风格用例；
> 标注 `pytest` 的文件为纯类风格，需用 `pytest tests/` 运行（跑器统一见 Ticket #10）。
> Ticket #12 的三项回归护栏（`test_final_scoring_regression.py`、
> `test_execution_timing_baseline.py`、`test_gastronome_golden.py`）均为
> unittest.TestCase，一条命令即可全绿。

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

## 运行测试

```bash
# 全部测试
python -m unittest discover tests

# 单个文件
python -m unittest tests.test_capture_speed

# 详细输出
python -m unittest discover -v tests
```
