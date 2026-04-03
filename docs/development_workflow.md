# Development Workflow (Genesis Branch)

## Philosophy

TDD-first, simulation-before-agent. Build a complete, testable game environment before touching any AI/automation code.

## Phases

### Phase 1: Game Environment Simulator ✅ DONE
**Goal**: Pure Python state machine that implements all game rules deterministically.

**Components**:
- `hawarma/env_simulator_types.py` (336 lines) - Data structures (EventType, Event, Recipe, Order, CookerState, AssemblyState, StockpileSlot, GameState, GameConfig)
- `hawarma/env_simulator.py` (1479 lines) - GameSimulator class with all operations
- `data/recipes.json` - Recipe data (14 recipes)

**Operations**:
- [x] `load_recipes()` - Load from JSON (supports both formats)
- [x] `setup_cookers()` / `setup_stockpile()` - Initialize
- [x] `start_cooking()` - Begin cooking on a cooker (+ validation)
- [x] `move_to_assembly()` - Move cooked ingredient to assembly
- [x] `serve_order()` - Complete and serve an order (with condiment validation & scoring)
- [x] `tick()` - Advance time, trigger auto-events (90s game limit)
- [x] `inject_order()` - Manual order injection for testing
- [x] `add_condiment()` - Add condiment with full validation (max 3, recipe match)
- [x] `move_to_stockpile()` - Store cooked ingredient
- [x] `pull_from_stockpile()` - Retrieve from stockpile
- [x] `move_to_trash()` - Discard ingredient
- [x] `clear_cooker()` - Clean expired ingredient
- [x] `select_recipes()` - Select 4 recipes from all available
- [x] `setup_from_recipes()` - Auto-configure game based on selected recipes

**Tests**: `tests/test_env_simulator.py` - **20 passed, 2 skipped**

---

### Phase 2: Interactive Agent ✅ DONE
**Goal**: Agent that can perceive simulator state and execute actions.

**Components**:
- `hawarma/agent/agent.py` (732 lines) - `CookingAgent` class with 7-level priority greedy strategy
- `hawarma/agent/__init__.py` - Exports all Action types and `CookingAgent`

**Action Types**:
- `CookAction` - Start cooking on a cooker
- `MoveToAssemblyAction` - Move finished ingredient to assembly station
- `MoveToStockpileAction` - Move finished ingredient to stockpile
- `PullFromStockpileAction` - Pull ingredient from stockpile to assembly
- `AddCondimentAction` - Add condiment to assembly
- `ServeOrderAction` - Serve completed dish to order slot
- `ClearCookerAction` - Clear expired ingredient from cooker

**Strategy** (Cooking First - verified 30局 average):
| 指标 | 值 |
|------|-----|
| 完成订单 | 14.1个 |
| 超时率 | 2.3% |
| 平均得分 | 2492分 |
| 效率 | 78% |

**Priority Order**:
1. Serve order (release assembly)
2. Move completed ingredients to assembly (release cookers)
3. Start cooking (let cookers work asynchronously ASAP)
4. Add condiments
5. Store to stockpile
6. Pull from stockpile
7. Clear expired ingredients

**Benchmark Scripts**:
- `scripts/benchmark_agent.py` (874 lines) - Full benchmark suite with 5 strategies
- `scripts/base_strategies.py` (252 lines) - Reusable strategy functions (naive, parallel)
- `scripts/benchmark_utils.py` (269 lines) - Shared utilities (GameMetrics, run_single_game, run_benchmark)
- `scripts/simulate_game.py` (87 lines) - Standalone game simulation runner

**Experiments**:
- `experiments/parallel_strategy/` - Parallel cooking strategy design and report
- `experiments/quick_serve/` - Quick serve strategy design and script

---

### Phase 3: Real Game Bridge ✅ DONE
**Goal**: Adapt agent to interact with actual game via UI automation.

**Components**:
- `hawarma/bridge/base_environment.py` (271 lines) - `BaseEnvironment` (ABC) + data classes (CookerState, AssemblyState, StockpileSlot, OrderInfo)
- `hawarma/bridge/environment.py` (335 lines) - `GameEnvironment(BaseEnvironment)` - real-game state tracker
- `hawarma/bridge/scanner.py` (205 lines) - `OrderScanner`, `DetectedOrder` - image-based order detection
- `hawarma/bridge/ui_runner.py` (279 lines) - `UIRunner` - swipe coordinate mapping and execution
- `hawarma/bridge/bridge.py` (245 lines) - `RealGameBridge` - coordinates all components, 3 parallel loops

**RealGameBridge Architecture** (3 parallel asyncio loops):
- **scan_loop** (0.5s interval): `OrderScanner.scan_new_orders()` → `GameEnvironment.add_order()`
- **timeout_loop** (0.3s interval): `GameEnvironment.check_and_remove_timed_out_orders()`
- **agent_loop** (0.1s interval): `CookingAgent.step()` → `_execute_action()`

**Supporting Modules**:
- `hawarma/config.py` (60 lines) - `AppConfig` (Pydantic), `load_config()` for YAML config
- `hawarma/models.py` (70 lines) - `Recipe`, `OrderStage`, `Order`
- `hawarma/services/recipe_manager.py` (90 lines) - `RecipeManager` - JSON recipe loading and lookup
- `hawarma/utils/image_utils.py` (49 lines) - `local_match()` - template matching in ROI regions
- `hawarma/logging_setup.py` (50 lines) - loguru terminal + file logging
- `hawarma/monkey_patches.py` (27 lines) - Airtest `Template._cv_match` patch

**Entry Point**:
- `main.py` (130 lines) - Interactive recipe selection → `RealGameBridge` + `CookingAgent` → `bridge.run()`

---

### Phase 4: SimulatorEnvironment Adapter 🚧 IN PROGRESS
**Goal**: Create adapter to let `CookingAgent` run seamlessly in both simulator and real game.

**Components**:
- `hawarma/bridge/simulator_environment.py` (新建) - `SimulatorEnvironment` adapter implementing `BaseEnvironment`

**Architecture**:
```
CookingAgent
    ├── Uses BaseEnvironment interface
    ├── 通过 env.time, env.orders, env.cookers 访问状态
    └── 返回 Action 对象

BaseEnvironment (ABC)
    ├── GameEnvironment (真实游戏)
    │   ├── time = time.time() - start_time
    │   └── 自动时间流逝
    │
    └── SimulatorEnvironment (模拟器适配器)
        ├── 包装 GameSimulator
        ├── time = sim.time (内部时间)
        └── tick(dt) 手动推进时间
```

**Key Features**:
- **State Conversion**: Convert `GameSimulator` internal data to unified `BaseEnvironment` structures
- **Operation Forwarding**: Call simulator methods, return `bool` (simulator returns `ActionResult`)
- **Time Model Abstraction**: Manual `tick(dt)` for simulator vs automatic time flow for real game

**Usage**:
```python
# Simulator benchmarking
sim = GameSimulator()
sim.load_recipes("data/recipes.json")
sim.setup_from_recipes(sim.select_recipes(count=4))

env = SimulatorEnvironment(sim)  # 包装模拟器
agent = CookingAgent(env, recipes)

while not sim.is_game_over():
    action = agent.step()
    if action:
        _execute_action(env, action)
    env.tick(0.1)  # 手动推进时间

# Real game (same agent!)
real_env = GameEnvironment(cooker_names=["grill", "oven", "pot", "skillet"])
agent = CookingAgent(real_env, recipes)

while not real_env.is_game_over():
    action = agent.step()
    if action:
        _execute_action(real_env, action)
    # 时间自动流逝
```

**Benefits**:
- Agent can switch between environments seamlessly
- Fast strategy testing in simulator without running real game
- Eliminate duplicate data structures and adapter code
- Clear separation of concerns

---

## Current Status

| Component | Status | File | Notes |
|-----------|--------|------|-------|
| **Core Infrastructure** | | | |
| Config | ✅ Complete | `hawarma/config.py` | Pydantic models, YAML loading |
| Models | ✅ Complete | `hawarma/models.py` | Recipe, Order, OrderStage |
| Logging | ✅ Complete | `hawarma/logging_setup.py` | loguru terminal + file |
| Monkey Patches | ✅ Complete | `hawarma/monkey_patches.py` | Airtest compatibility |
| Image Utils | ✅ Complete | `hawarma/utils/image_utils.py` | local_match() for ROI |
| Recipe Manager | ✅ Complete | `hawarma/services/recipe_manager.py` | JSON loading, slug lookup |
| **Simulator** | | | |
| Types | ✅ Complete | `hawarma/env_simulator_types.py` | 9 data classes |
| GameSimulator | ✅ Complete | `hawarma/env_simulator.py` | Full state machine (1479 lines) |
| Tests | ✅ Complete | `tests/test_env_simulator.py` | 20 passed, 2 skipped |
| **Agent** | | | |
| CookingAgent | ✅ Complete | `hawarma/agent/agent.py` | 7-level priority greedy |
| Action Types | ✅ Complete | `hawarma/agent/__init__.py` | 7 action dataclasses |
| **Bridge** | | | |
| BaseEnvironment | ✅ Complete | `hawarma/bridge/base_environment.py` | ABC + data classes |
| GameEnvironment | ✅ Complete | `hawarma/bridge/environment.py` | Real-game state tracker |
| SimulatorEnvironment | ✅ Complete | `hawarma/bridge/simulator_environment.py` | GameSimulator adapter |
| OrderScanner | ✅ Complete | `hawarma/bridge/scanner.py` | Image-based detection |
| UIRunner | ✅ Complete | `hawarma/bridge/ui_runner.py` | Swipe execution |
| RealGameBridge | ✅ Complete | `hawarma/bridge/bridge.py` | 3-loop coordinator |
| **Scripts** | | | |
| Benchmark | ✅ Complete | `scripts/benchmark_agent.py` | 5 strategies, CLI |
| Base Strategies | ✅ Complete | `scripts/base_strategies.py` | naive, parallel |
| Benchmark Utils | ✅ Complete | `scripts/benchmark_utils.py` | Metrics, runners |
| Simulate Game | ✅ Complete | `scripts/simulate_game.py` | Standalone runner |
| Simulate Full Game | ✅ Complete | `scripts/simulate_full_game.py` | Full game with agent |
| **Tests** | | | |
| Simulator | ✅ Complete | `tests/test_env_simulator.py` | Structure, time, orders, cooking |
| SimulatorEnvironment | ✅ Complete | `tests/test_simulator_environment.py` | Adapter tests |
| Rush Detection | ✅ Complete | `tests/test_rush_detection.py` | Pixel-based red channel |
| Timer Detection | ✅ Complete | `tests/test_timer_detection.py` | OpenCV template matching |
| Capture Speed | ✅ Complete | `tests/test_capture_speed.py` | Airtest screenshot speed |

## Key Design Decisions

1. **选菜单机制**: 每局游戏从14个菜谱中选4个，决定可用灶台/食材/调料
2. **库存区初始为空**: Agent 自己决定存什么
3. **Animation windows**: 1.5s for slot shifts, 1s for new orders
4. **Immediate refresh**: When all slots empty after serve, new order appears immediately
5. **90-second game**: Orders stop generating at 90s
6. **4-second interval**: Orders appear at 4s, 8s, 12s, etc.
7. **Cooking First**: 灶台是异步的，尽早开始烹饪是关键（+10.8% vs naive）
8. **按需响应**: 只烹饪当前订单需要的食材，避免预烹饪（-30% penalty）
9. **3-loop architecture**: scan/timeout/agent 并行，各自独立间隔
10. **统一环境接口**: BaseEnvironment 抽象接口 + SimulatorEnvironment 适配器实现

## Running the Application

```bash
python main.py
```

## Running Tests

```bash
# Run all tests
python -m unittest discover tests

# Run a single test file
python -m unittest tests.test_env_simulator

# Run SimulatorEnvironment tests
python -m unittest tests.test_simulator_environment

# Run with verbose output
python -m unittest discover -v tests
```

## Running Simulations

```bash
# Run a single simulation with agent
python scripts/simulate_full_game.py --seed 42

# Run multiple seeds
for seed in 0 1 2 3 4; do
    python scripts/simulate_full_game.py --seed $seed
done
```

## Running Benchmarks

```bash
python scripts/benchmark_agent.py --seeds 20
```
