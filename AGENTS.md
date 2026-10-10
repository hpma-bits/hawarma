# AGENTS.md

> **上下文索引**：本文档是项目的入口索引。需要深入了解任何模块时，请先阅读对应的 `ARCHITECTURE.md` 文件获取完整上下文。

## 🗺️ 上下文地图

### 项目概览
这是一个 Python 烹饪游戏自动化机器人，使用 asyncio 并发处理、Pydantic 数据验证和 Airtest UI 自动化。

| 上下文 | 文件 | 何时阅读 |
|--------|------|----------|
| **项目总览** | [`ARCHITECTURE.md`](ARCHITECTURE.md) | 了解整体目录结构和模块关系 |
| **核心代码** | [`src/hawarma/ARCHITECTURE.md`](src/hawarma/ARCHITECTURE.md) | 修改核心逻辑、理解数据流和架构 |
| **Agent 决策** | [`src/hawarma/agent/ARCHITECTURE.md`](src/hawarma/agent/ARCHITECTURE.md) | 修改 Agent 策略、动作类型、优先级 |
| **桥接层** | [`src/hawarma/game/ARCHITECTURE.md`](src/hawarma/game/ARCHITECTURE.md) | 修改 UI 操作、状态追踪、扫描器、三循环架构 |
| **服务层** | [`src/hawarma/services/ARCHITECTURE.md`](src/hawarma/services/ARCHITECTURE.md) | 修改配方管理等服务组件 |
| **工具函数** | [`src/hawarma/utils/ARCHITECTURE.md`](src/hawarma/utils/ARCHITECTURE.md) | 修改图像处理工具 |
| **多语言** | [`src/hawarma/i18n/ARCHITECTURE.md`](src/hawarma/i18n/ARCHITECTURE.md) | 修改界面文案、新增/调整语言 |
| **文档** | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 游戏规则、Agent策略、架构设计 |
| **测试** | [`tests/ARCHITECTURE.md`](tests/ARCHITECTURE.md) | 添加或修改测试 |
| **实验** | [`experiments/ARCHITECTURE.md`](experiments/ARCHITECTURE.md) | 运行基准测试、查看实验记录 |

### 快速导航：按任务选择上下文

| 任务 | 阅读顺序 |
|------|----------|
| 修改 Agent 策略 | `docs/game_rules.md` → `src/hawarma/agent/ARCHITECTURE.md` → `src/hawarma/ARCHITECTURE.md` |
| 修改 UI 操作 | `src/hawarma/game/ARCHITECTURE.md` → `src/hawarma/ARCHITECTURE.md` |
| 修改订单检测 | `src/hawarma/game/ARCHITECTURE.md` (scanner) → `docs/game_rules.md` |
| 添加新测试 | `tests/ARCHITECTURE.md` → 对应模块的 ARCHITECTURE.md |
| 运行基准测试 | `experiments/ARCHITECTURE.md` → `playground/` 目录 |
| 修改配置 | `configs/config.yaml` → `src/hawarma/config.py` |

---

## ⚠️ 重要原则

### 文档优先原则

**必须把 `docs/` 作为真实信息源**：
- 所有游戏规则、算法设计、策略分析都以 `docs/` 中的文档为准
- 思考问题时，**从文档出发**，而不是从代码出发
- 代码要与文档保持一致，如果代码与文档冲突，以文档为准

**真实游戏相关文档**（仅保留这些）：
- [`docs/game_rules.md`](docs/game_rules.md) - 游戏规则（唯一依据）
- [`docs/agent_strategy.md`](docs/agent_strategy.md) - Agent策略和实验结果
- [`docs/real_game_implementation.md`](docs/real_game_implementation.md) - 真实游戏实现

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
4. 目录内容变化（新增/删除/重命名文件）必须同步更新所属目录 `ARCHITECTURE.md` 的文件清单（来源 Issue #10，已纳入下方核对项）

### Code Review 核对项（来源 Issue #10）

- [ ] `pytest tests` 全绿（统一跑器，同时收集 unittest 风格与纯 pytest 风格用例）
- [ ] `ruff check src tests playground` 通过（风格门禁）
- [ ] mypy 输出相对基线无新增错误（告警模式，不卡合入）
- [ ] 若目录内容有变化（新增/删除/重命名文件），所属 `ARCHITECTURE.md` 的文件清单已同步更新

---

## 🔧 常用命令

### 运行应用（真实游戏）

默认使用 **`gastronome`** 策略（10 级贪心瀑布 + CPM + visibility 阈值跨越 + 单食材优先 + 延迟感知）。

> ⚠️ 模拟器分辨率必须为 **1920×1080**（模板图片与屏幕坐标均按此校准，其他分辨率会静默失败不报错）。程序启动时自动 `adb connect` 配置的 `adb_address`（默认 MuMu 12 端口 16384，其他模拟器端口不同需改配置）。

#### 命令行界面 (CLI)
```bash
.venv\Scripts\activate
python -m hawarma
```

#### 文本用户界面 (TUI)
```bash
.venv\Scripts\activate
python -m hawarma.tui
```

TUI 提供完整的仪表板界面，包括：
- 📋 配方选择界面
- ⚙️ 配置面板（可编辑所有配置）
- 🎮 游戏控制界面（开始、暂停、停止）
- 📊 实时日志显示

#### 切换策略

策略通过配置文件或命令行参数切换，无需修改代码。详见 [`docs/agent_strategy.md`](docs/agent_strategy.md)。

```bash
# 配置文件: configs/config.yaml
strategy: "gastronome"      # CPM enhanced cascade (默认)；可选 "planner"（实验性）或 "dessert"
language: "zh-CN"           # 界面语言: zh-CN (默认) 或 en-US；TUI 主菜单可按 L 键运行时切换

# 命令行覆盖
python -m hawarma --strategy gastronome
python -m playground bench --games 50 --strategies gastronome,dessert
```

### 运行测试

统一跑器为 **pytest**（Issue #10）：一条命令同时收集 unittest 风格与纯 pytest 风格用例，pyproject 已配置 `testpaths`/`pythonpath`，在仓库根目录直接运行。

```bash
.venv\Scripts\activate
pytest tests                        # 全部测试（统一跑器）
pytest tests/test_sim_fidelity.py   # 单个文件
pytest tests -v                     # 详细输出
# 兼容备注：unittest 风格用例仍可用 `python -m unittest discover tests` 运行
# （仅收集 TestCase 子类，不含纯 pytest 风格文件）
```

### 风格门禁（Issue #10）

```bash
ruff check src tests playground     # 风格门禁：语法错误/未定义名等低级问题，合入前必须通过
mypy                                # 类型检查：告警模式（输出现状报告，暂不卡合入）
```

- ruff 起步规则集为保守的 `E9/F63/F7/F82`（配置见 `pyproject.toml`），存量豁免已在 `per-file-ignores` 登记
- mypy 检查范围 `src/hawarma`（配置见 `pyproject.toml`），输出仅作现状报告，退出码不作为门禁

### 运行模拟（Playground）
```bash
.venv\Scripts\activate
python -m playground run --seed 42                    # 运行单局
python -m playground bench --games 50                 # 运行基准测试
python -m playground bench --games 100 --csv out.csv  # 导出 CSV
python -m playground replay replay.json               # 回放记录
```

### 环境设置

先创建 venv 再装依赖；pytest/ruff/mypy 在 dev 依赖组中，跑测试前需要安装：

```bash
python -m venv .venv
.venv\Scripts\activate             # Mac/Linux: source .venv/bin/activate
uv pip install -e .                # 运行时依赖（用户部署只需这一步）
uv pip install -e . --group dev    # 开发/测试依赖（pytest、ruff、mypy）
```

> `configs/config.yaml` 不入库（已 gitignore），首次运行时自动生成默认配置；请从项目根目录运行程序。

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

---
## Behavioral guidelines

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```



Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

------

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
