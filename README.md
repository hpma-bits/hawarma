# Project Overview

This project is a bot for a cooking game, designed to automate the process of cooking and serving dishes. It uses the `airtest` framework to interact with an Android emulator running the game. The bot is capable of detecting customer orders, managing a cooking pipeline, and strategically stockpiling ingredients to improve efficiency.

## Main Technologies

*   **Python:** The core programming language.
*   **Airtest:** A framework for UI automation of games and apps.
*   **Loguru:** A library for pleasant and powerful logging.
*   **Pydantic:** A library for data validation and settings management.
*   **Questionary:** A library for building interactive command-line prompts.

## Architecture

The application is structured into several key components:

*   **`src/hawarma/cli.py`:** The CLI entry point of the application. Handles initial setup, user input for recipe selection, and the main application loop.
*   **`src/hawarma/`:** Core application package.
*   **`src/hawarma/config.py`:** Configuration module. Loads settings from `configs/config.yaml` via Pydantic models.
*   **`src/hawarma/bridge/`:** Real-game bridge -- coordinates `Scanner` (image-based order detection), `GameEnv` (state tracking), `Operator` (swipe/touch execution), and the agent decision loop.
*   **`src/hawarma/agent/`:** Agent shell + pluggable strategy pattern. `Strategy.decide(state)` returns actions; the shell handles diagnostics and statistics.
*   **`src/hawarma/services/recipe_manager.py`:** Loads and queries recipe data from `data/recipes.json`.
*   **`src/hawarma/env_simulator.py`:** Lightweight deterministic game simulator used as the ground-truth game rules engine (shared by playground).
*   **`playground/`:** Simulation environment for benchmarking strategies without a real device.
*   **`configs/config.yaml`:** Main configuration file -- screen coordinates, matching parameters, game settings.
*   **`data/`:** Game data including `recipes.json`, `reward.csv`, and `recipe_timeout.csv`.

# Building and Running

## Prerequisites

*   Python 3.10 or higher
*   An Android emulator with the game installed. The emulator must be connected to `adb` at `127.0.0.1:16384`.

## Installation

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

This installs all dependencies including dev extras (pytest, etc.).

## Running the Application

### 命令行界面 (CLI)

```bash
python -m hawarma
```

The application will prompt you to select the recipes to use for the current session. After selection, the bot starts automatically and processes orders.

### 文本用户界面 (TUI)

```bash
python -m hawarma.tui
```

TUI 提供完整的仪表板界面，包含：
- 📋 配方选择界面
- ⚙️ 配置面板（可编辑所有配置）
- 🎮 游戏控制界面（开始、暂停、停止）
- 📊 实时日志显示

### Switching Strategies

```bash
python -m hawarma --strategy cpm
```

Available strategies: `default`, `cpm`, `preempt_score`, `visibility_aware`.

### Running Benchmarks (No Device Required)

```bash
python -m playground bench --games 50
python -m playground bench --games 100 --strategies default,cpm --csv results.csv
```

### Running Tests

```bash
python -m unittest discover tests
python -m unittest discover playground/tests
```
