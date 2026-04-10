# tests/ 目录架构

## 目录职责
测试模块，包含单元测试和集成测试，验证环境模拟器、图像检测、Agent 策略等组件的正确性。

## ⚠️ 重要提示

**一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**

## 📄 文件清单

| 文件名 | 状态 | 功能 |
|--------|------|------|
| `__init__.py` | ✅ | 包初始化 |
| `test_env_simulator.py` | ✅ | 环境模拟器测试（基础结构、时间限制、订单生成、并行烹饪、积分系统） |
| `test_simulator_environment.py` | ✅ | SimulatorEnvironment 适配器测试（验证 BaseEnvironment 接口实现） |
| `test_capture_speed.py` | ✅ | 截图速度测试（测量 `device.snapshot()` 平均耗时） |
| `test_timer_detection.py` | ✅ | Timer 图标模板匹配测试（验证 icon-timer.jpg 在截图中的检测） |
| `test_rush_detection.py` | ✅ | 加急订单像素检测测试（基于红色通道阈值检测 rush 状态） |
| `test_device_methods.py` | ✅ | 设备截图和触控方法检测测试 |
| `testset/` | ✅ | 测试图片集（包含 normal/rush 订单截图） |

## 测试覆盖

1. **基础结构测试** — 事件创建、配方创建、状态初始化
2. **游戏时间限制测试** — 90 秒游戏时长、结束条件
3. **自动订单生成测试** — 4 秒间隔、槽位填充、刷新规则
4. **并行烹饪测试** — 多灶台同时工作
5. **积分系统测试** — 得分计算
6. **错误处理测试** — 无效输入、资源冲突
7. **模拟器适配器测试** — SimulatorEnvironment 接口兼容性
8. **性能测试** — 截图速度测量
9. **图像检测测试** — Timer 图标匹配、Rush 订单检测

## 运行测试

```bash
# 全部测试
python -m unittest discover tests

# 单个文件
python -m unittest tests.test_capture_speed

# 详细输出
python -m unittest discover -v tests
```
