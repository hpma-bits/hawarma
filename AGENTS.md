# AGENTS.md

> **上下文索引**：本文档是项目的入口索引。需要深入了解任何模块时，请先阅读对应的 `ARCHITECTURE.md` 文件获取完整上下文。

## 🗺️ 上下文地图

### 项目概览
这是一个 Python 烹饪游戏自动化机器人，使用 asyncio 并发处理、Pydantic 数据验证和 Airtest UI 自动化。

| 上下文 | 文件 | 何时阅读 |
|--------|------|----------|
| **项目总览** | [`ARCHITECTURE.md`](ARCHITECTURE.md) | 了解整体目录结构和模块关系 |
| **核心代码** | [`hawarma/ARCHITECTURE.md`](hawarma/ARCHITECTURE.md) | 修改核心逻辑、理解数据流和架构 |
| **Agent 决策** | [`hawarma/agent/ARCHITECTURE.md`](hawarma/agent/ARCHITECTURE.md) | 修改 Agent 策略、动作类型、优先级 |
| **桥接层** | [`hawarma/bridge/ARCHITECTURE.md`](hawarma/bridge/ARCHITECTURE.md) | 修改 UI 操作、状态追踪、扫描器、双循环架构 |
| **服务层** | [`hawarma/services/ARCHITECTURE.md`](hawarma/services/ARCHITECTURE.md) | 修改配方管理等服务组件 |
| **工具函数** | [`hawarma/utils/ARCHITECTURE.md`](hawarma/utils/ARCHITECTURE.md) | 修改图像处理工具 |
| **文档** | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 查找游戏规则、设计文档、模拟器文档 |
| **测试** | [`tests/ARCHITECTURE.md`](tests/ARCHITECTURE.md) | 添加或修改测试 |
| **实验** | [`experiments/ARCHITECTURE.md`](experiments/ARCHITECTURE.md) | 运行基准测试、查看实验记录 |

### 快速导航：按任务选择上下文

| 任务 | 阅读顺序 |
|------|----------|
| 修改 Agent 策略 | `docs/game_rules.md` → `hawarma/agent/ARCHITECTURE.md` → `hawarma/ARCHITECTURE.md` |
| 修改 UI 操作 | `hawarma/bridge/ARCHITECTURE.md` → `hawarma/ARCHITECTURE.md` |
| 修改订单检测 | `hawarma/bridge/ARCHITECTURE.md` (scanner) → `docs/game_rules.md` |
| 添加新测试 | `tests/ARCHITECTURE.md` → 对应模块的 ARCHITECTURE.md |
| 运行基准测试 | `experiments/ARCHITECTURE.md` → `scripts/` 目录 |
| 修改配置 | `configs/config.yaml` → `hawarma/config.py` |

---

## ⚠️ 重要原则

### 文档优先原则

**必须把 `docs/` 作为真实信息源**：
- 所有游戏规则、算法设计、策略分析都以 `docs/` 中的文档为准
- 思考问题时，**从文档出发**，而不是从代码出发
- 代码要与文档保持一致，如果代码与文档冲突，以文档为准

**关键文档**：
- [`docs/game_rules.md`](docs/game_rules.md) - 游戏规则（唯一依据）
- [`docs/agent_strategy.md`](docs/agent_strategy.md) - Agent策略和实验结果
- [`docs/agent_architecture.md`](docs/agent_architecture.md) - Agent架构设计

### 模拟器局限性

- 模拟器可能不能完全反映真实游戏的行为（如并行性）
- 重要结论需要在真实环境中验证
- 不要过度依赖模拟器的测试结果

### 实验验证

- 重要结论需要多局测试验证（建议30局以上）
- 考虑不同recipes组合的差异
- 从文档中的游戏规则出发分析问题

---

## 🏗️ Harness 实践

### 上下文加载策略

1. **默认只加载 AGENTS.md**：本文档包含足够的规则和索引
2. **按需深入**：根据任务类型，从上表的"快速导航"中选择对应的 ARCHITECTURE.md
3. **逐层展开**：从根 `ARCHITECTURE.md` → 子目录 `ARCHITECTURE.md` → 具体源文件

### 上下文完整性

每个 `ARCHITECTURE.md` 文件包含：
- 目录目的和文件列表
- 输入/输出定义
- 模块间关系和数据流
- 关键设计决策和原理

### 维护规则

1. 任何架构变更必须更新相关的 `ARCHITECTURE.md`
2. 每个目录必须有 `ARCHITECTURE.md`
3. 文件头必须声明：`一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md`

---

## 🔧 常用命令

### 运行应用
```bash
.venv\Scripts\activate
python main.py
```

### 运行测试
```bash
.venv\Scripts\activate
python -m unittest discover tests        # 全部测试
python -m unittest tests.test_capture_speed  # 单个文件
python -m unittest discover -v tests     # 详细输出
```

### 运行模拟
```bash
.venv\Scripts\activate
python scripts/simulate_full_game.py --seed 42
python scripts/benchmark_agent.py --seeds 10
```

### 环境设置
```bash
uv pip install -r requirements.txt
python -m venv .venv
.venv\Scripts\activate
```

---

## 📝 代码规范

### 类型注解
- Python 3.10+ 小写泛型：`list[str]`、`dict[str, int]`
- 使用 `|` 联合运算符：`Order | None`
- 所有公共函数/方法必须有类型提示

### 命名约定
- **变量/函数**：`snake_case`
- **类**：`PascalCase`
- **常量**：`UPPER_SNAKE_CASE`
- **私有方法**：`_leading_underscore`

### 导入顺序
1. 标准库
2. 第三方库
3. 本地导入
4. 相对导入

### 并发
- 使用 `asyncio` 和 `asyncio.Lock()`
- 使用 `asyncio.create_task()` 并跟踪任务
- 使用 `asyncio.gather()` 分组并发操作

### 错误处理
- 使用 `loguru` 结构化日志
- 捕获具体异常而非裸 `except:`
- 记录错误后再 re-raise

### 反模式
- 不使用 `List[Type]` → 用 `list[Type]`
- 不使用 `Optional[Type]` → 用 `Type | None`
- 不使用裸 `except:` → 捕获具体异常
- 不重复调用 `asyncio.get_event_loop().time()` → 缓存结果
- 不创建未跟踪的 asyncio 任务 → 使用任务跟踪集合
- 不导入 Airtest 私有方法 → 使用公共 API
