# tests/ 目录架构

## 目录职责
测试模块，包含单元测试和集成测试，验证 Scheduler-Executor 流程的正确性和性能。

## 文件清单

| 文件名 | 状态 | 功能 |
|--------|------|------|
| `__init__.py` | ✅ | 包初始化 |
| `test_game_rules.py` | ✅ | 游戏规则验证 playground，模拟游戏环境检测规则违反 |
| `test_assembly_station_concurrency.py` | ✅ | Assembly Station 并发测试 |
| `test_capture_speed.py` | ✅ | 截图速度测试 |
| `test_game_start_detection.py` | ✅ | 游戏开始检测测试 |
| `test_rush_detection.py` | ✅ | Rush 订单检测测试 |
| `test_second_ingredient.py` | ✅ | 第二食材检测测试 |
| `mocks/` | ✅ | Mock 实现模块 |
| `fixtures/` | ✅ | 测试固件模块 |
| `testset/` | ✅ | 测试图片集 |
| `output/` | ✅ | 测试输出 |

## mocks/ 子目录

| 文件名 | 状态 | 功能 |
|--------|------|------|
| `__init__.py` | ✅ | 包初始化 |
| `mock_ui_manager.py` | ✅ | Mock UI 操作管理器，记录操作日志 |
| `mock_detection_service.py` | ✅ | Mock 订单检测服务，按时间表返回订单 |

## fixtures/ 子目录

| 文件名 | 状态 | 功能 |
|--------|------|------|
| `__init__.py` | ✅ | 包初始化 |
| `test_recipes.py` | ✅ | 测试用配方数据和订单创建函数 |

## 测试场景覆盖

1. **单订单基础流程** - 验证基本功能
2. **双订单并发** - 验证资源竞争处理
3. **Rush Order 插队** - 验证优先级机制
4. **多订单满载** - 验证高负载性能
5. **混合 Rush 订单** - 验证复杂调度

## 性能指标

- 总耗时
- 订单完成数
- 平均订单完成时间
- UI 操作数
- 动作执行数

---

⚠️ **一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**