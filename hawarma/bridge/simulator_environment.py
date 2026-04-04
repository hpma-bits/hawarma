"""
Simulator environment adapter

Position: Wraps GameSimulator to implement BaseEnvironment interface
      Allows Agent to switch seamlessly between simulator and real game

Input: GameSimulator instance
Output: Unified environment interface (time, state, operations)

Key design:
1. State conversion: simulator data -> BaseEnvironment unified data structures
2. Operation forwarding: call simulator methods, return bool (simulator returns ActionResult)
3. Time model: provide tick() method for manual time advancement

Note: Update this header comment and update directory MD when file changes
"""

from __future__ import annotations

from typing import Optional

from .base_environment import (
    BaseEnvironment,
    CookerState,
    AssemblyState,
    StockpileSlot,
    OrderInfo,
)


class _RecipeAdapter:
    """Recipe adapter: converts simulator Recipe to Agent-expected format"""
    
    def __init__(self, sim_recipe):
        self._recipe = sim_recipe
    
    @property
    def slug(self) -> str:
        return self._recipe.slug
    
    @property
    def name(self) -> str:
        return self._recipe.name
    
    @property
    def raw_ingredients(self) -> list[str]:
        return [ing.name for ing in self._recipe.ingredients]
    
    @property
    def cookers(self) -> list[str]:
        return [ing.cooker_type for ing in self._recipe.ingredients]
    
    @property
    def cook_durations(self) -> list[float] | None:
        return [ing.duration for ing in self._recipe.ingredients]
    
    @property
    def condiments(self) -> dict[str, int]:
        return self._recipe.condiments


class SimulatorEnvironment(BaseEnvironment):
    """
    GameSimulator adapter implementing BaseEnvironment interface
    
    Allows Agent to switch seamlessly between simulator and real game.
    
    Core functions:
    1. State conversion: convert simulator internal data to unified data structures
    2. Operation forwarding: call simulator methods, adapt return value (ActionResult -> bool)
    3. Time advancement: provide tick() method for manual time progress (simulator-specific)
    """
    
    def __init__(self, simulator):
        """
        Initialize adapter
        """
        self._sim = simulator
        self._tick_interval = 0.1
        
        # Pre-create recipe adapters for all recipes
        self._recipe_adapters = {}
        if hasattr(simulator, "recipes"):
            for slug, recipe in simulator.recipes.items():
                self._recipe_adapters[slug] = _RecipeAdapter(recipe)
    
    @property
    def time(self) -> float:
        """Return simulator internal time"""
        return self._sim.time
    
    def tick(self, dt: float = 0.1) -> list:
        """
        Manually advance time (simulator-specific method)
        """
        return self._sim.tick(dt)
    
    @property
    def orders(self) -> list[Optional[OrderInfo]]:
        """Convert order data"""
        result = []
        for order in self._sim.state.orders:
            if order is None:
                result.append(None)
            else:
                result.append(OrderInfo(
                    order_id=order.order_id,
                    recipe_slug=order.recipe.slug,
                    is_rush=order.is_rush,
                    created_at=order.created_at,
                    timeout_at=order.timeout_at,
                    done=order.is_completed
                ))
        return result
    
    @property
    def cookers(self) -> dict[str, CookerState]:
        """Convert cooker data"""
        result = {}
        for name, sim_cooker in self._sim.state.cookers.items():
            cooker_type = sim_cooker.cooker_type if sim_cooker.cooker_type else name
            result[name] = CookerState(
                busy=sim_cooker.busy,
                ingredient_name=sim_cooker.ingredient_name,
                cooker_type=cooker_type,
                started_at=sim_cooker.started_at,
                done_at=sim_cooker.done_at
            )
        return result
    
    @property
    def assembly(self) -> AssemblyState:
        """Convert assembly data"""
        sim_assembly = self._sim.state.assembly
        ingredients = [ing[0] for ing in sim_assembly.ingredients]
        
        return AssemblyState(
            ingredients=ingredients,
            target_recipe_slug=sim_assembly.target_recipe.slug if sim_assembly.target_recipe else None,
            owner_order_id=None,
            condiments=sim_assembly.condiments.copy()
        )
    
    @property
    def stockpile(self) -> dict[str, StockpileSlot]:
        """Convert stockpile data"""
        result = {}
        for name, sim_slot in self._sim.state.stockpile.items():
            result[name] = StockpileSlot(
                ingredient_name=sim_slot.ingredient_name,
                cooker_type=sim_slot.cooker_type,
                count=sim_slot.count
            )
        return result
    
    def get_recipe_adapter(self, slug: str) -> _RecipeAdapter | None:
        """Get recipe adapter"""
        return self._recipe_adapters.get(slug)
    
    def is_in_animation_window(self) -> bool:
        """Whether in animation window"""
        return self._sim.is_in_animation_window()
    
    def start_cooking(self, ingredient: str, cooker: str, duration: float) -> bool:
        """Start cooking"""
        result = self._sim.start_cooking(ingredient, cooker)
        return result.success
    
    def move_to_assembly(self, cooker: str) -> bool:
        """Move finished ingredient to assembly"""
        result = self._sim.move_to_assembly(cooker)
        return result.success
    
    def move_to_stockpile(self, cooker: str, slot: str) -> bool:
        """Move cooked ingredient to stockpile"""
        result = self._sim.move_to_stockpile(cooker, slot)
        return result.success
    
    def pull_from_stockpile(self, slot: str) -> bool:
        """Pull ingredient from stockpile to assembly"""
        result = self._sim.pull_from_stockpile(slot)
        return result.success
    
    def add_condiment(self, condiment: str) -> bool:
        """Add condiment to assembly"""
        result = self._sim.add_condiment(condiment)
        return result.success
    
    def serve_order(self, slot_idx: int) -> bool:
        """Serve order from slot"""
        result = self._sim.serve_order(slot_idx)
        return result.success
    
    def clear_assembly(self) -> bool:
        """Clear assembly station (discard ingredients when order expires)"""
        result = self._sim.clear_assembly()
        return result.success
    
    def clear_cooker(self, cooker: str) -> bool:
        """Clear cooker (discard expired ingredient)"""
        result = self._sim.clear_cooker(cooker)
        return result.success
    
    def is_game_over(self) -> bool:
        """Whether game is over"""
        return self._sim.is_game_over()
    
    def get_condiment_count(self, condiment: str) -> int:
        """Get condiment count in assembly"""
        return self.assembly.condiments.get(condiment, 0)
