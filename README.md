# Hawarma - 烹饪游戏自动化 Agent

自动识别订单、管理烹饪流水线、最优策略配菜的自动化机器人。

[![中文](https://img.shields.io/badge/lang-中文-red.svg)](README.md)
[![English](https://img.shields.io/badge/lang-English-blue.svg)](README.en.md)

## 快速开始

### 1. 安装 Git

下载并安装 **Git**：https://git-scm.com/downloads

> Windows 安装时保持默认选项即可。Mac 可用 `brew install git`，Linux 可用 `apt install git`。

### 2. 安装 Python

下载并安装 **Python 3.10+**：https://www.python.org/downloads/

> Windows 安装时请勾选 **"Add Python to PATH"**

### 3. 下载项目

```bash
git clone https://github.com/hpma-bits/hawarma.git
cd hawarma
```

### 4. 一键安装

**Windows:**
```bash
setup.bat
```

**Mac/Linux:**
```bash
chmod +x setup.sh
./setup.sh
```

> **一键安装失败？** 可按以下步骤手动安装：
>
> ```bash
> # 1. 创建虚拟环境
> python -m venv .venv
>
> # 2. 激活虚拟环境
> # Windows:
> .venv\Scripts\activate
> # Mac/Linux:
> source .venv/bin/activate
>
> # 3. 安装依赖（推荐使用 uv，更快）
> pip install uv
> uv pip install -e .
> # 如果 uv 安装失败，直接使用 pip：
> pip install -e .
> ```

### 5. 启动

**方式一：双击脚本（推荐）**
- Windows: `run.bat`
- Mac/Linux: `./run.sh`

**方式二：命令行**
```bash
# TUI 图形界面（与 run.bat 相同）
python -m hawarma.tui

# CLI 命令行界面
python -m hawarma
```

## 前置要求

- **Python 3.10+**
- **Git**
- **Android 模拟器**（如 MuMu、雷电、夜神）
- 模拟器分辨率必须设为 **1920×1080**
- 模拟器需开启 ADB 调试
- 游戏已安装在模拟器中

> ⚠️ **分辨率是硬性要求**：模板图片和所有屏幕坐标都按 1920×1080 校准。其他分辨率不会报错，但识别会静默失败、点击位置错乱。

### ADB 连接地址

程序启动时会自动 `adb connect` 配置的地址（`configs/config.yaml` 中的 `adb_address`）。常见模拟器的默认端口：

| 模拟器 | 默认 ADB 地址 |
|--------|---------------|
| MuMu 12 | `127.0.0.1:16384`（默认值） |
| 雷电 | `127.0.0.1:5555` |
| 夜神 | `127.0.0.1:62001` |

> 以模拟器设置中"ADB 调试"页面显示的端口为准，不同的端口号请修改配置文件中的 `adb_address`。

## 使用方式

### TUI 仪表板（推荐）

```bash
python -m hawarma.tui
```

提供完整的图形界面：
- 配方选择
- 配置面板
- 游戏控制（开始/暂停/停止）
- 实时日志

### CLI 命令行

```bash
python -m hawarma                     # 默认策略 gastronome
python -m hawarma --strategy planner  # 指定策略
python -m hawarma --station dessert   # 甜点站
```

### 策略列表

| 策略名 | 说明 |
|--------|------|
| `gastronome` | 美食站 CPM 增强瀑布策略（默认，推荐） |
| `planner` | 美食站 deadline 感知滚动时域调度（实验性） |
| `dessert` | 甜点站策略（需配合 `--station dessert`） |

## 配置

`configs/config.yaml` **不需要手动创建**：首次运行时会自动生成一份默认配置。之后编辑它可修改：

- `adb_address` — ADB 连接地址（大多数用户唯一需要确认的项）
- 匹配阈值、策略参数等（默认已按 1920×1080 校准，除非更改分辨率否则无需调整）

> 请始终从项目根目录启动程序，配置和数据文件都按项目根目录解析。

## 常见问题

**启动时报 "no device online" / 连接不上模拟器**
- 检查模拟器设置中 ADB 调试是否已开启
- 检查 `configs/config.yaml` 的 `adb_address` 是否与模拟器端口一致（见上方端口表）

**游戏识别全部失败 / 角色乱点**
- 检查模拟器分辨率是否为 **1920×1080**（最常见的失败原因，且不会报错）

**提示找不到 configs/config.yaml**
- 属正常现象：首次运行会自动生成。请确认是在项目根目录下启动。

## 项目结构

```
hawarma/
├── configs/               # 配置目录（config.yaml 首次运行自动生成）
├── data/                  # 游戏数据（配方、分数表）
├── static/img/            # 模板图片（按 1920×1080 校准）
├── src/hawarma/           # 核心代码
│   ├── cli.py             # CLI 入口
│   ├── tui.py             # TUI 入口
│   ├── config.py          # 配置管理
│   ├── paths.py           # 路径解析
│   ├── agent/             # 策略引擎
│   ├── game/              # 游戏桥接（扫描、操作、验证）
│   ├── core/              # 数据模型
│   └── services/          # 配方管理等
├── playground/            # 模拟器基准测试
├── tests/                 # 单元测试
└── setup.bat / setup.sh   # 一键安装脚本
```

## 开发与测试（可选）

日常使用无需本节内容，仅修改代码时需要。

```bash
# 激活虚拟环境后安装开发依赖（pytest、ruff、mypy）
uv pip install -e . --group dev

pytest tests                        # 全部测试（统一跑器）
ruff check src tests playground     # 风格门禁
```

无设备模拟基准测试：

```bash
python -m playground run --seed 42
python -m playground bench --games 50 --strategies gastronome,dessert
```

开发规范与架构文档见 [`AGENTS.md`](AGENTS.md) 及各级 `ARCHITECTURE.md`。

## 许可证

MIT License
