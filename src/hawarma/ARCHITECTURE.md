# src/hawarma Directory Architecture

## 📁 目录概述

此目录是 Hawarma 项目的核心，包含 Agent 自动化烹饪游戏的全部逻辑。

## ⚠️ 重要提示

**一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**

## 📄 文件列表

### `__init__.py`
- **地位**: 包初始化文件

### `config.py`
- **地位**: 配置管理模块
- **功能**: 从 YAML 文件加载配置，Pydantic 验证

### `logging_setup.py`
- **地位**: 日志配置模块
- **功能**: 使用 loguru 配置终端 + 文件日志

### `models.py`
- **地位**: 数据模型定义模块
- **功能**: Recipe、Order、OrderStage 等数据结构

### `monkey_patches.py`
- **地位**: 兼容性补丁模块
- **功能**: 修复 airtest 框架的兼容性问题

### `env_simulator.py`
- **地位**: 游戏环境模拟器（用于测试和调试）
- **功能**: 轻量级状态机，模拟游戏规则

### `env_simulator_types.py`
- **地位**: 模拟器数据类型定义
- **功能**: Event、EventType、Recipe、Order 等类型

### `agent/` 子目录
- **地位**: Agent Shell + Action 类型定义
- **功能**: 封装环境状态、注入 Strategy、输出 Action
- **文件**:
  - `agent.py`: CookingAgent Shell（默认注入 `DefaultStrategy`），Action 类型定义
- **注意**: 决策逻辑已迁移到 `playground/strategies/default.py`

### `bridge/` 子目录
- **地位**: Agent 与真实游戏的桥接层
- **功能**: 扫描、状态追踪、UI 执行、生命周期管理
- **文件**:
  - `bridge.py`: RealGameBridge，三循环并行架构
  - `environment.py`: GameEnvironment，程序逻辑追踪状态
  - `scanner.py`: OrderScanner，图像检测订单
  - `ui_runner.py`: UIRunner，swipe 坐标执行

### `services/` 子目录
- **地位**: 服务层
- **文件**:
  - `recipe_manager.py`: 从 JSON 加载配方数据

### `utils/` 子目录
- **功能**: 图像处理工具
- **文件**:
  - `image_utils.py`: 模板匹配

---

## 🔗 架构

```
main.py
  ↓
RealGameBridge (bridge/bridge.py)
  │
  ├─ 三个并行循环:
  │   ├─ scan_loop (0.5s)    → OrderScanner → GameEnvironment.add_order()
  │   ├─ timeout_loop (0.3s) → GameEnvironment.check_and_remove_timed_out_orders()
  │   └─ agent_loop (0.1s)   → CookingAgent.step() → _execute_action()
  │
  ├─ GameEnvironment (bridge/environment.py)
  │     └─ 程序逻辑追踪: 灶台、组装站、库存、订单、调料
  │
  ├─ OrderScanner (bridge/scanner.py)
  │     └─ Airtest 图像检测: 只检测订单
  │
  ├─ UIRunner (bridge/ui_runner.py)
  │     └─ swipe 坐标映射和执行
  │
  └─ CookingAgent (agent/agent.py)
        └─ 7 级优先级贪心策略
```

### Agent 决策优先级

```
1. 送餐 (ServeOrderAction)        ← 组装完成立即送
2. 移到组装站 (MoveToAssemblyAction) ← 完成烹饪尽快移走
3. 开始烹饪 (CookAction)          ← 尽早开始，让灶台异步工作
4. 添加调料 (AddCondimentAction)   ← 可在烹饪期间进行
5. 从库存取用 (PullFromStockpileAction) ← 库存有则直接用
6. 清理过期 (ClearCookerAction)    ← 5s 未取走则清理
7. 存入库存 (MoveToStockpileAction) ← 多余食材缓冲
```

### 数据流

```
屏幕截图
  ↓
OrderScanner.scan_new_orders()
  ↓
GameEnvironment.add_order()
  ↓
CookingAgent.step()  ← 按优先级选最优动作
  ↓
Action
  ↓
RealGameBridge._execute_action()
  ├─→ UIRunner.swipe()        ← 执行 UI 操作
  └─→ GameEnvironment.*()      ← 更新内部状态
```

---

## 🚀 运行

```bash
python main.py
```

选择配方后自动运行游戏，结束后显示统计。
日志输出到 `logs/game_YYYYMMDD_HHmmss.log`。
