# Development Workflow (Genesis Branch)

## Philosophy

TDD-first, simulation-before-agent. Build a complete, testable game environment before touching any AI/automation code.

## Phases

### Phase 1: Game Environment Simulator ✅ DONE
**Goal**: Pure Python state machine that implements all game rules deterministically.

**Components**:
- `env_simulator_types.py` - Data structures (Order, CookerState, AssemblyState, Recipe, GameConfig)
- `env_simulator.py` - GameSimulator class with all operations
- `data/recipes.json` - Recipe data

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

### Phase 2: Interactive Agent (Next Step)
**Goal**: Agent that can perceive simulator state and execute actions.

**Components to build**:
- Agent perception layer (read simulator state + game_config)
- Action space definition (valid actions at each state)
- Simple rule-based agent (heuristics)
- Training infrastructure (if ML-based)

**Key Design**:
- Agent interacts with simulator, not real game
- Same interface will be reused for real game
- Can run thousands of episodes quickly

---

### Phase 3: Real Game Bridge (Future)
**Goal**: Adapt agent to interact with actual game via UI automation.

**Components**:
- `env_bridge.py` - Translate simulator actions to UI swipes
- Perception: Screenshot → State extraction
- Action: State decision → Airtest swipe

**Key Design**:
- Same agent interface, different backend
- Simulator becomes validation tool
- Can compare simulator vs real behavior

---

## Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| Types/Data | ✅ Complete | Order, CookerState, AssemblyState, GameConfig |
| Recipes | ✅ Complete | 14 recipes, supports JSON formats |
| select_recipes() | ✅ Complete | Random select 4 recipes with seed |
| setup_from_recipes() | ✅ Complete | Auto-configure cookers/ingredients/condiments |
| start_cooking | ✅ Complete | + game config validation |
| move_to_assembly | ✅ Complete | Validates cooking done, assembly compat |
| serve_order | ✅ Complete | Condiment validation, scoring system |
| tick | ✅ Complete | 90s limit, auto order generation (4s interval) |
| add_condiment | ✅ Complete | + game config validation |
| move_to_stockpile | ✅ Complete | Compatibility check, max 5 per slot |
| pull_from_stockpile | ✅ Complete | Assembly compatibility |
| move_to_trash | ✅ Complete | Supports cooker/stockpile/assembly |
| clear_cooker | ✅ Complete | Expired ingredient cleanup |

## Key Design Decisions

1. **选菜单机制**: 每局游戏从14个菜谱中选4个，决定可用灶台/食材/调料
2. **库存区初始为空**: Agent 自己决定存什么
3. **Animation windows**: 1.5s for slot shifts, 1s for new orders
4. **Immediate refresh**: When all slots empty after serve, new order appears immediately
5. **90-second game**: Orders stop generating at 90s
6. **4-second interval**: Orders appear at 4s, 8s, 12s, etc.
