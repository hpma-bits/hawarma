# AGENTS.md

## Overview
This is a Python-based automation bot for a cooking game. The project uses asyncio for concurrent processing, Pydantic for data validation, and Airtest for UI automation.

## ⚠️ 重要原则

### 文档优先原则

**必须把 `docs/` 作为真实信息源**：
- 所有游戏规则、算法设计、策略分析都以 `docs/` 中的文档为准
- 思考问题时，**从文档出发**，而不是从代码出发
- 代码要与文档保持一致，如果代码与文档冲突，以文档为准

**关键文档**：
- `docs/game_rules.md` - 游戏规则（唯一依据）
- `docs/agent_strategy.md` - Agent策略和实验结果
- `docs/agent_architecture.md` - Agent架构设计

### 模拟器局限性

- 模拟器可能不能完全反映真实游戏的行为（如并行性）
- 重要结论需要在真实环境中验证
- 不要过度依赖模拟器的测试结果

### 实验验证

- 重要结论需要多局测试验证（建议30局以上）
- 考虑不同recipes组合的差异
- 从文档中的游戏规则出发分析问题

## Build/Test Commands

### Running the Application
```bash
python main.py
```

### Running Tests
Tests use Python's `unittest` framework:

```bash
# Run all tests
python -m unittest discover tests

# Run a single test file
python -m unittest tests.test_capture_speed

# Run a single test method
python -m unittest tests.test_capture_speed.TestCaptureSpeed.test_detection_speed

# Run with verbose output
python -m unittest discover -v tests
```

### Environment Setup
```bash
# Create virtual environment and install dependencies
uv pip install -r requirements.txt  # or: python -m uv pip install .
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows
```

### Type Checking (Manual)
Note: No type checker is currently configured. Run `mypy` manually if needed:
```bash
python -m mypy hawarma/**/*.py
```

### Code Formatting (Manual)
No auto-formatter is configured. Follow PEP 8 style guidelines.

## Code Style Guidelines

### Import Organization
Order imports in this sequence:
1. Standard library imports
2. Third-party imports (loguru, pydantic, airtest, etc.)
3. Local imports (hawarma package)
4. Relative imports within packages

```python
# Standard library
import asyncio
import time
from pathlib import Path
from typing import Dict, List, Tuple

# Third-party
from loguru import logger
from pydantic import BaseModel, field_validator

# Local
from hawarma.config import AppConfig
from hawarma.models import Recipe, Order
```

Use `from ... import ...` for commonly used modules. Avoid `from module import *`.

### Type Annotations
- Use Python 3.10+ lowercase generic types: `list[str]`, `dict[str, int]`, not `List[str]`, `Dict[str, int]`
- Use the `|` union operator: `Order | None`, not `Optional[Order]`
- All public functions/methods must have type hints
- Return type `None` is required for functions that don't return

```python
# Good
def get_recipe_by_slug(self, slug: str) -> Recipe | None:
    ...

def load_recipes(self) -> None:
    ...
```

### Naming Conventions
- **Variables/Functions**: `snake_case` - `order_slots`, `get_recipe_by_slug()`
- **Classes**: `PascalCase` - `CookingBotApp`, `DetectionService`
- **Constants**: `UPPER_SNAKE_CASE` - `MAX_SLOTS`, `RECIPE_CONFIDENCE_THRESHOLD`
- **Private methods**: `_leading_underscore` - `_detect_recipe()`, `_cook_on_single_cooker()`

### File Documentation Headers
All module files must have a header comment in Chinese with the following structure:

```python
"""
模块名称

地位：简要描述模块在系统中的职责和位置

输入：模块接收的数据/参数
输出：模块返回的数据/结果

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""
```

Example from `app.py`:
```python
"""
核心应用类

地位：协调整个烹饪流程，管理订单队列、处理管道、库存管理和原料囤积策略

输入：配置对象、配方列表
输出：应用运行状态、订单完成统计

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""
```

### Documentation Strings
Public classes and methods must have docstrings. Use the following format:
- **Classes**: Describe purpose and main functionality
- **Methods**: Describe args and returns values
- Use present tense: "Loads recipes" not "Load recipes"

```python
class RecipeManager:
    """
    Handles loading, accessing, and managing recipe data from a JSON file.
    """

    def get_recipe_by_slug(self, slug: str) -> Recipe | None:
        """
        Finds a recipe by its unique slug.

        Args:
            slug: The slug of the recipe to find.

        Returns:
            The Recipe object if found, otherwise None.
        """
```

### Error Handling
- Use structured logging with `loguru` for all errors
- Provide context in error messages
- Catch specific exceptions (`FileNotFoundError`, `ValueError`) before generic `Exception`
- Always log errors before re-raising if appropriate

```python
try:
    with open(self._recipes_path, "r", encoding="utf-8") as f:
        recipes_data = json.load(f)
except FileNotFoundError:
    logger.error(f"Recipe file not found at: {self._recipes_path}")
    raise
except json.JSONDecodeError as e:
    logger.error(f"Error decoding JSON from recipe file: {self._recipes_path}")
    raise
```

### Logging
- Use `loguru.logger` for all logging
- Log levels: `DEBUG`, `INFO`, `SUCCESS`, `WARNING`, `ERROR`
- Include context and variable values
- Use f-strings for formatting

```python
logger.info(f"Application setup complete.")
logger.debug(f"Checking slot {slot_idx} for new orders")
logger.error(f"Failed to initialize Airtest device: {e}")
```

### Concurrency and Async
- Use `asyncio` for concurrent operations
- Use `asyncio.Lock()` for thread-safe access to shared resources
- Create tasks with `asyncio.create_task()` and track them for cleanup
- Group concurrent operations with `asyncio.gather()`

```python
# Lock usage
async with self.order_slots_lock:
    self.order_slots[slot_idx] = new_order

# Task management
tasks = []
for cooker_name, ingredients in cooker_schedule.items():
    task = self._cook_on_single_cooker(cooker_name, ingredients, destination)
    tasks.append(task)

await asyncio.gather(*tasks)
```

### Pydantic Models
- Use Pydantic `BaseModel` for data validation
- Use `@field_validator` for custom validation
- Define all required fields without default values

```python
class Recipe(BaseModel):
    """Represents a cooking recipe."""

    slug: str
    name: str
    raw_ingredients: list[str]
    cookers: list[str]
    cook_durations: list[float]

    @field_validator("cook_durations")
    def check_durations_length(cls, v, values):
        if "cookers" in values.data and len(v) != len(values.data["cookers"]):
            raise ValueError("cook_durations length must match cookers length")
        return v
```

### Code Organization
- **Core application**: `hawarma/app.py` - main `CookingBotApp` class
- **Services**: `hawarma/services/` - business logic (`detection_service.py`, `cooking_service.py`, `recipe_manager.py`)
- **Models**: `hawarma/models.py` - data structures using Pydantic
- **Utils**: `hawarma/utils/` - utility functions (`image_utils.py`)
- **Config**: `hawarma/config.py` - YAML-based configuration with Pydantic validation

### Directory Architecture
Each directory must contain an `ARCHITECTURE.md` file documenting:
- Directory purpose
- All files with their status/role and functionality
- Input/output for each file
- Warning: "⚠️ 一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！"

### Configuration
- All configuration in `configs/config.yaml`
- Load with `AppConfig.model_validate()` through `load_config()` function
- Access configuration attributes: `config.screen.resolution`, `config.matching.ingredients_threshold`

### Airtest/Screenshot Handling
- Use `G.DEVICE.snapshot()` to capture screen
- Use `local_match()` from `image_utils.py` for template matching in specific regions
- Template images stored in `static/img/` directory with pattern: `ingredient-{name}.jpg`, `icon-{name}.jpg`

### Chinese Language Guidelines
- Module headers and architecture docs use Chinese
- Function docstrings and code comments can be English or Chinese
- Keep technical terms in English: "订单" = "order", "配方" = "recipe", "检测" = "detection"

### Must-Do Rules (from README.md)
1. Any architectural changes must update relevant directory documentation after completion
2. Every explicit directory must have a concise architecture `ARCHITECTURE.md` file including file names, status, and functionality. File header must declare: "一旦我所属的目录有变化，请更新我"
3. Every module must have header comments indicating input/output and system role, with declaration: "一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md"
4. Maintain project fractal structure throughout development

### Anti-Patterns to Avoid
- Don't use `List[Type]` - use `list[Type]` (Python 3.10+)
- Don't use `Optional[Type]` - use `Type | None`
- Don't use bare `except:` - catch specific exceptions
- Don't use `asyncio.get_event_loop().time()` multiple times - cache the result
- Don't create untracked asyncio tasks - use task tracking sets for cleanup
- Don't import from private Airtest methods (`_cv_match`) - prefer public APIs
