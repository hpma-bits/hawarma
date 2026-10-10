# Hawarma - Cooking Game Automation Agent

An automation bot that recognizes orders, manages cooking pipelines, and optimizes recipe strategies.

[![中文](https://img.shields.io/badge/lang-中文-red.svg)](README.md)
[![English](https://img.shields.io/badge/lang-English-blue.svg)](README.en.md)

## Quick Start

### 1. Install Git

Download and install **Git**: https://git-scm.com/downloads

> On Windows, use the default options. On Mac: `brew install git`. On Linux: `apt install git` or `yum install git`.

### 2. Install Python

Download and install **Python 3.10+**: https://www.python.org/downloads/

> On Windows, check **"Add Python to PATH"** during installation.

### 3. Clone the Project

```bash
git clone https://github.com/hpma-bits/hawarma.git
cd hawarma
```

### 4. One-Click Setup

**Windows:**
```bash
setup.bat
```

**Mac/Linux:**
```bash
chmod +x setup.sh
./setup.sh
```

> **One-click setup failed?** Follow these manual steps:
>
> ```bash
> # 1. Create virtual environment
> python -m venv .venv
>
> # 2. Activate it
> # Windows:
> .venv\Scripts\activate
> # Mac/Linux:
> source .venv/bin/activate
>
> # 3. Install dependencies (uv is faster)
> pip install uv
> uv pip install -e .
> # If uv fails, fall back to pip:
> pip install -e .
> ```

### 5. Launch

**Option 1: Double-click the script (recommended)**
- Windows: `run.bat`
- Mac/Linux: `./run.sh`

**Option 2: Command line**
```bash
# TUI dashboard (same as run.bat)
python -m hawarma.tui

# CLI
python -m hawarma
```

## Prerequisites

- **Python 3.10+**
- **Git**
- **Android Emulator** (e.g., MuMu, LDPlayer, Nox)
- Emulator resolution must be set to **1920×1080**
- ADB debugging enabled on the emulator
- Game must be installed on the emulator

> ⚠️ **Resolution is a hard requirement**: template images and all screen coordinates are calibrated for 1920×1080. Other resolutions do not raise errors — recognition silently fails and taps land in wrong places.

### ADB Connection Address

On startup the program runs `adb connect` automatically against the address configured in `configs/config.yaml` (`adb_address`). Common emulator default ports:

| Emulator | Default ADB address |
|----------|---------------------|
| MuMu 12 | `127.0.0.1:16384` (default) |
| LDPlayer | `127.0.0.1:5555` |
| Nox | `127.0.0.1:62001` |

> Always trust the port shown in your emulator's "ADB debugging" settings page; if it differs, update `adb_address` in the config file.

## Usage

### TUI Dashboard (Recommended)

```bash
python -m hawarma.tui
```

Full graphical interface:
- Recipe selection
- Configuration panel
- Game controls (Start/Pause/Stop)
- Real-time logs

### CLI

```bash
python -m hawarma                     # Default strategy: gastronome
python -m hawarma --strategy planner  # Specify strategy
python -m hawarma --station dessert   # Dessert station
```

### Strategies

| Strategy | Description |
|----------|-------------|
| `gastronome` | Gourmet station CPM enhanced cascade (default, recommended) |
| `planner` | Gourmet station deadline-aware rolling-horizon scheduling (experimental) |
| `dessert` | Dessert station strategy (use with `--station dessert`) |

## Configuration

You do **not** need to create `configs/config.yaml` manually: a default config is generated automatically on first run. Afterwards you can edit it to change:

- `adb_address` — ADB connection address (the only item most users need to check)
- Matching thresholds, strategy parameters, etc. (defaults are calibrated for 1920×1080 — no changes needed unless you use a different resolution)

> Always launch the program from the project root directory; config and data files are resolved relative to the project root.

## Troubleshooting

**"no device online" on startup / cannot connect to the emulator**
- Check that ADB debugging is enabled in the emulator settings
- Check that `adb_address` in `configs/config.yaml` matches your emulator's port (see the table above)

**Recognition fails completely / character taps wrong places**
- Check that the emulator resolution is **1920×1080** (the most common failure cause, and it raises no error)

**"configs/config.yaml not found" message**
- This is normal: it is generated automatically on first run. Make sure you launch from the project root directory.

## Project Structure

```
hawarma/
├── configs/               # Config directory (config.yaml auto-generated on first run)
├── data/                  # Game data (recipes, score tables)
├── static/img/            # Template images (calibrated for 1920×1080)
├── src/hawarma/           # Core code
│   ├── cli.py             # CLI entry
│   ├── tui.py             # TUI entry
│   ├── config.py          # Config management
│   ├── paths.py           # Path resolution
│   ├── agent/             # Strategy engine
│   ├── game/              # Game bridge (scan, action, verify)
│   ├── core/              # Data models
│   └── services/          # Recipe management, etc.
├── playground/            # Simulator benchmarks
├── tests/                 # Unit tests
└── setup.bat / setup.sh   # One-click setup
```

## Development & Testing (Optional)

Everyday usage does not require this section; it is only needed when modifying code.

```bash
# Activate the virtual environment, then install dev dependencies (pytest, ruff, mypy)
uv pip install -e . --group dev

pytest tests                        # All tests (unified runner)
ruff check src tests playground     # Style gate
```

Device-free simulated benchmarks:

```bash
python -m playground run --seed 42
python -m playground bench --games 50 --strategies gastronome,dessert
```

See [`AGENTS.md`](AGENTS.md) and the per-directory `ARCHITECTURE.md` files for development conventions and architecture docs.

## License

MIT License
