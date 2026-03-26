# Environment Simulator Implementation Document

## 1. Overview

The Game Environment Simulator is a lightweight, deterministic state machine that simulates the cooking game without UI automation. It serves as the "source of truth" for game rules - if the simulator rejects an action, it violates game rules.

### Key Principles
- **Pure state machine**: No side effects, no UI automation
- **Deterministic**: Same actions always produce same results
- **Validating**: Enforces all game rules strictly
- **Observable**: Exposes full state for agent perception

## 2. Architecture

### 2.1 Core Components

```
GameSimulator
├── State (current snapshot)
│   ├── orders: List[Optional[Order]]     # 4 slots
│   ├── cookers: Dict[str, CookerState]   # 4 cookers
│   ├── assembly: AssemblyState          # 1 station
│   ├── stockpile: Dict[str, StockpileSlot]# 3 slots
│   └── time: float                        # sim clock
├── Configuration
│   ├── recipes: Dict[str, Recipe]        # all recipes
│   └── constants: GameConstants
└── History (for debugging)
    ├── events: List[Event]
    └── actions: List[ActionRecord]
```

### 2.2 Data Structures

#### Order
```python
@dataclass
class Order:
    order_id: int
    recipe: Recipe              # What needs to be cooked
    is_rush: bool               # True for rush orders
    created_at: float           # When order appeared
    timeout_at: float           # When order expires (created_at + 40s or 70s)
    served_at: Optional[float]  # When order was completed
    condiments_applied: Dict[str, int]  # Track what condiments were added
```

**Note**: No OrderStage! The environment doesn't track "heating", "seasoning", etc. That's agent-side logic.

#### CookerState
```python
@dataclass
class CookerState:
    busy: bool = False
    ingredient_name: Optional[str] = None
    cooker_type: Optional[str] = None  # grill, oven, etc.
    started_at: Optional[float] = None
    done_at: Optional[float] = None      # When cooking completes
    expired_at: Optional[float] = None   # When ingredient goes bad (done_at + 5s)
    
    @property
    def is_done(self) -> bool:
        return self.done_at is not None and time >= self.done_at
    
    @property
    def is_expired(self) -> bool:
        return self.expired_at is not None and time >= self.expired_at
```

#### AssemblyState
```python
@dataclass
class AssemblyState:
    # The recipe this assembly is building toward
    target_recipe: Optional[Recipe] = None
    
    # Ingredients currently on assembly
    # Each entry: (ingredient_name, cooker_used, added_at)
    ingredients: List[Tuple[str, str, float]] = field(default_factory=list)
    
    # Condiments applied (type -> count)
    condiments: Dict[str, int] = field(default_factory=dict)
    
    @property
    def is_complete(self) -> bool:
        """Check if all required ingredients are present"""
        if not self.target_recipe:
            return False
        required = {ing.name for ing in self.target_recipe.ingredients}
        present = {ing[0] for ing in self.ingredients}
        return required == present
    
    @property
    def can_add_ingredient(self, ing_name: str, cooker: str) -> bool:
        """Check if ingredient is compatible with current assembly"""
        if not self.ingredients:
            # Empty assembly - can add any ingredient
            return True
        
        # Check if ingredient belongs to same recipe
        if not self.target_recipe:
            return False
        
        # Ingredient must be in target recipe and not already present
        recipe_ing_names = {ing.name for ing in self.target_recipe.ingredients}
        present_ing_names = {ing[0] for ing in self.ingredients}
        
        return ing_name in recipe_ing_names and ing_name not in present_ing_names
```

**Key Design**: Assembly station tracks which recipe it's building toward (determined by first ingredient added). Incompatible ingredients are rejected.

#### StockpileSlot
```python
@dataclass  
class StockpileSlot:
    # What ingredient is stored here
    ingredient_name: Optional[str] = None
    # Which cooker was used
    cooker_type: Optional[str] = None
    # How many units (max 5)
    count: int = 0
    
    def can_add(self, ing_name: str, cooker: str) -> bool:
        """Check if ingredient is compatible with slot contents"""
        if self.count == 0:
            return True
        return self.ingredient_name == ing_name and self.cooker_type == cooker
    
    def add(self, ing_name: str, cooker: str) -> bool:
        """Add ingredient to slot. Returns False if incompatible or full."""
        if not self.can_add(ing_name, cooker) or self.count >= 5:
            return False
        self.ingredient_name = ing_name
        self.cooker_type = cooker
        self.count += 1
        return True
```

### 2.3 Event System

Events record what happened for agent learning and debugging:

```python
@dataclass
class Event:
    timestamp: float
    event_type: EventType
    details: Dict[str, Any]

class EventType(Enum):
    # Order lifecycle
    ORDER_APPEARED = auto()
    ORDER_TIMEOUT = auto()
    ORDER_SERVED = auto()
    
    # Cooking
    COOKING_STARTED = auto()
    COOKING_COMPLETED = auto()
    INGREDIENT_EXPIRED = auto()
    
    # Assembly
    INGREDIENT_ADDED_TO_ASSEMBLY = auto()
    CONDIMENT_ADDED = auto()
    ASSEMBLY_COMPLETED = auto()
    
    # Movement
    INGREDIENT_MOVED_TO_STOCKPILE = auto()
    INGREDIENT_MOVED_TO_TRASH = auto()
    
    # Slot changes
    SLOTS_ADVANCED = auto()
```

## 3. Core Operations

### 3.1 Cooking Operations

#### `start_cooking(ingredient: str, cooker: str) -> Result`

**Preconditions:**
- Cooker exists
- Cooker is not busy
- Ingredient + cooker combination exists in at least one recipe (optional but recommended)

**Effects:**
- Cooker becomes busy
- Ingredient assigned to cooker
- Cooking completes at `current_time + duration` (duration from recipe data)
- Event: `COOKING_STARTED`

**Returns:**
- `Success` with estimated completion time
- `Failure` with reason (cooker busy, invalid ingredient, etc.)

#### `move_to_assembly(cooker: str) -> Result`

**Preconditions:**
- Cooker has ingredient
- Cooking is done (not expired)
- Ingredient is compatible with current assembly (if assembly not empty)

**Effects:**
- Ingredient removed from cooker
- Cooker becomes free
- Ingredient added to assembly
- If assembly was empty, target recipe is set based on this ingredient
- Event: `INGREDIENT_ADDED_TO_ASSEMBLY`

**Returns:**
- `Success` with updated assembly state
- `Failure` with reason (ingredient not done, incompatible with assembly, etc.)

### 3.2 Order Operations

#### `serve_order(slot_idx: int) -> Result`

**Preconditions:**
- Slot has active order
- Assembly is complete (all required ingredients present)
- Assembly target recipe matches order's recipe
- Not in animation window (1.5s after previous serve/timeout)

**Effects:**
- Order marked as served
- Score calculated (base - time penalty + condiment bonus)
- Slot cleared
- Assembly cleared
- All orders to the right shift left
- Animation window activated (1.5s)
- Events: `ORDER_SERVED`, `SLOTS_ADVANCED`

**Returns:**
- `Success` with score earned
- `Failure` with reason (recipe mismatch, animation window, etc.)

### 3.3 Time Management

#### `tick(dt: float) -> List[Event]`

Advances simulation time and triggers automatic events:

1. **Check order timeouts**: For each order, if `current_time > timeout_at`, trigger `ORDER_TIMEOUT` and slot advancement
2. **Check cooker completion**: For each busy cooker, if `current_time > done_at`, mark as done and emit `COOKING_COMPLETED`
3. **Check cooker expiration**: For each done cooker, if `current_time > expired_at`, mark as expired and emit `INGREDIENT_EXPIRED`
4. **Check animation window**: If in animation window and `current_time > animation_end`, clear animation flag

## 4. Validation & Error Handling

### 4.1 Validation Rules

The simulator enforces these rules strictly:

**Cooking Phase:**
- Cannot start cooking on busy cooker
- Cannot move undercooked ingredient to assembly
- Cannot move expired ingredient to assembly (must trash)

**Assembly Phase:**
- Cannot add incompatible ingredient to assembly (wrong recipe)
- Cannot add condiment before all ingredients present
- Cannot add 4th+ condiment (ignored but not error)

**Serving Phase:**
- Cannot serve during animation window
- Cannot serve if recipe doesn't match order
- Cannot serve if ingredients missing

**Stockpile:**
- Cannot mix different ingredients in same slot
- Cannot mix same ingredient from different cookers
- Cannot exceed 5 units per slot

### 4.2 Error Handling Strategy

**Decision**: Use dataclass with type hints (Option B) for ActionResult.

```python
from dataclasses import dataclass
from typing import List, Optional, Any

@dataclass
class ActionResult:
    success: bool
    events: List['Event']
    new_state: 'GameState'
    error_message: Optional[str] = None
    
    @property
    def is_success(self) -> bool:
        """Helper property for cleaner code"""
        return self.success
        
    def get_error(self) -> str:
        """Get error message or default"""
        return self.error_message or "Unknown error"
        
    def __bool__(self) -> bool:
        """Allow using `if result:` syntax"""
        return self.success

# All actions return ActionResult
# On failure: success=False, error_message explains why
# On success: success=True, events list what happened, new_state shows result
```

**Rationale**: Dataclass provides type safety, IDE autocomplete, and clean API while remaining lightweight.

## 5. Implementation Guidelines

### 5.1 Performance Considerations

**Decision**: Use immutable state (functional style) despite slight performance cost, prioritizing debugging and correctness.

- **State immutability**: Return new state on each action (functional style) for easy undo/debugging
  - All state modifications return a new `GameState` object
  - Old states are preserved in history for replay
  - Slightly slower but much better for debugging and testing
- **Event batching**: Group events by time tick for efficient processing
- **Lazy evaluation**: Compute derived state (like assembly completeness) on demand

**Rationale**: The simulator is not performance-critical (not real-time), and the benefits of immutability (debugging, testing, replay) far outweigh the small performance cost.

### 5.2 Testing Strategy

```python
# Example test structure
def test_cooking_workflow():
    sim = GameSimulator()
    sim.setup_cookers(['grill', 'oven'])
    
    # Start cooking
    result = sim.start_cooking('beef', 'grill')
    assert result.success
    
    # Fast forward
    sim.tick(5.0)  # Cooking done
    
    # Move to assembly
    result = sim.move_to_assembly('grill')
    assert result.success
    assert len(sim.assembly.ingredients) == 1
```

## 6. Time Management and Order Generation

### 6.1 Game Duration

**Total Game Time**: 90 seconds
- Game starts at `time = 0.0`
- Game ends when `time >= 90.0`
- No additional orders appear after game ends
- Goal: Complete as many orders as possible within 90 seconds

### 6.2 Order Generation

**Automatic Order Generation**:
- Orders appear automatically every 4 seconds
- First order appears at `time = 4.0`
- Orders continue until game ends (90 seconds) or all 4 slots are full
- Orders fill the leftmost empty slot
- If all 4 slots are full, new orders are queued until a slot becomes available

**Order Sequence**:
```
time=0.0s:  Game starts, orders=[None, None, None, None]
time=4.0s:  Order 1 appears at slot 0, orders=[Order1, None, None, None]
time=8.0s:  Order 2 appears at slot 1, orders=[Order1, Order2, None, None]
time=12.0s: Order 3 appears at slot 2, orders=[Order1, Order2, Order3, None]
time=16.0s: Order 4 appears at slot 3, orders=[Order1, Order2, Order3, Order4]
... (if Order1 served, new order fills slot 0 at next 4s interval)
```

### 6.3 Parallel Cooking

**Multiple Cookers Support**:
- All cookers can operate independently and in parallel
- Each cooker maintains its own timer (started_at, done_at, expired_at)
- `tick(dt)` checks all cookers simultaneously
- No limit on how many cookers can be active at once (except total number of cookers)

**Example of Parallel Cooking**:
```
time=0.0s: start_cooking('beef', 'grill'), start_cooking('fish', 'oven')
time=3.0s: grill done (beef cooked for 3s)
time=4.0s: oven done (fish cooked for 4s)
Both cookers operated in parallel with different durations
```

## 6. Next Steps

1. **Implement core data structures** (Order, CookerState, AssemblyState, etc.) ✅
2. **Write comprehensive tests first (TDD)** - test 90s game time, parallel cooking, auto-order generation
3. **Implement GameSimulator class** with all operations
4. **Create debugging/visualization tools** for state inspection
5. **Implement agent interface** for perception and action execution

---

## 7. Design Decisions Summary

This section summarizes all key design decisions made during the specification phase:

### 7.1 Implementation Choices

| Decision | Selected Option | Rationale |
|----------|----------------|-----------|
| **ActionResult Type** | Dataclass with type hints | Type safety, IDE support, clean API, lightweight |
| **State Management** | Immutable state (functional style) | Better debugging, testing, replay capability |
| **Recipe Loading** | From `data/recipes.json` | Flexible, easy to modify without code changes |
| **Ingredient Tracking** | Track both ingredient name and cooker type | Required for accurate recipe validation |
| **4th Condiment Behavior** | `success=False` with error message | Clear agent feedback, better learning |
| **Visual Debugging** | Simple text-based visualization first | Easy to implement, refactor later if needed |
| **Event History** | Full event history | Complete replay capability for debugging |
| **Thread Safety** | Single-threaded for now | Simpler implementation, can add later |

### 7.2 Key Architectural Principles

1. **Validation Over Performance**: Strict rule enforcement is more important than speed
2. **Debuggability First**: All design choices prioritize ease of debugging and testing
3. **Functional Core**: Core state management uses functional programming principles
4. **Observable State**: Full state visibility for agent perception and debugging
5. **Reversible Actions**: Immutable state allows replay and undo

### 7.3 Out of Scope (Future Work)

The following features are intentionally deferred for future iterations:

- Multi-threading support
- Advanced visualization (GUI, 3D, etc.)
- Network multiplayer
- Performance optimizations (caching, pooling)
- Machine learning integration
- Real-time constraints

---

**Document Version**: 1.0
**Status**: ✅ **READY FOR IMPLEMENTATION**
**Last Updated**: After complete design specification
**Next Steps**: 
1. Implement data structures (Order, CookerState, etc.)
2. Implement GameSimulator class
3. Write comprehensive tests
4. Create basic visualization

**Ready to begin implementation!**
