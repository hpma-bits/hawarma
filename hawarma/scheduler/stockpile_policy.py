"""
Stockpile Policy

地位：管理stockpile槽位分配和补货策略。

输入：GameState、SessionState
输出：Stockpile相关的决策

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

import itertools
from collections import Counter

from hawarma.state import GameState, SessionState
from hawarma.actions import Action, CookIngredient


class StockpilePolicy:
    """
    Decides which ingredients deserve stockpile slots and when to refill.
    
    This is policy, not execution. It returns CookIngredient actions;
    the Executor performs them.
    
    Design:
    - Session-level: which 3 ingredients get stockpile slots (decided at init)
    - Tick-level: should we cook to stockpile now?
    
    The 3 stockpile slots are a scarce strategic cache. We cannot
    represent all possible ingredients, so assignment is selective.
    """
    
    def __init__(self, session: SessionState):
        self.session = session
        self.stockpile_assignments: list[str] = []
        self._assign_slots()
    
    def _assign_slots(self) -> None:
        """
        Score all ingredients and assign top 3 to stockpile slots.
        
        Scoring factors (from current codebase):
        1. Usage frequency across recipes
        2. Cooker contention (heavily-used cookers = more valuable to pre-cook)
        3. Cook time (longer cooking = more worth hoarding)
        
        Formula: score = freq + cooker_usage*0.5 + duration*0.2
        """
        all_ingredients = [
            ing for recipe in self.session.ordered_recipes
            for ing in recipe.raw_ingredients
        ]
        
        cooker_usage = Counter(
            itertools.chain.from_iterable(r.cookers for r in self.session.ordered_recipes)
        )
        
        ingredient_scores: dict[str, float] = {}
        
        for ingredient in set(all_ingredients):
            score = 0.0
            
            freq = all_ingredients.count(ingredient)
            score += freq
            
            for recipe in self.session.ordered_recipes:
                if ingredient not in recipe.raw_ingredients:
                    continue
                
                idx = recipe.raw_ingredients.index(ingredient)
                cooker = recipe.cookers[idx]
                duration = recipe.cook_durations[idx]
                
                score += cooker_usage[cooker] * 0.5
                score += duration * 0.2
            
            ingredient_scores[ingredient] = score * 10
        
        sorted_ingredients = sorted(
            ingredient_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        self.stockpile_assignments = [ing for ing, _ in sorted_ingredients[:3]]
        self.session.stockpile_assignments = self.stockpile_assignments
    
    def is_stockpile_ingredient(self, ingredient: str) -> bool:
        """Check if an ingredient has a stockpile slot assigned."""
        return ingredient in self.stockpile_assignments
    
    def get_stockpile_slot_for(self, ingredient: str) -> int | None:
        """Get the stockpile slot index for an ingredient. Returns None if not assigned."""
        try:
            return self.stockpile_assignments.index(ingredient)
        except ValueError:
            return None
    
    def should_use_stockpile(
        self,
        ingredient: str,
        state: GameState,
    ) -> bool:
        """
        Decide whether to use stockpile or cook fresh for an ingredient.
        
        Use stockpile if:
        1. Ingredient has a stockpile assignment
        2. Stockpile count > 0
        
        Args:
            ingredient: The ingredient needed
            state: Current game state
            
        Returns:
            True if should pull from stockpile, False to cook fresh
        """
        if not self.is_stockpile_ingredient(ingredient):
            return False
        return state.get_stock_count(ingredient) > 0
    
    def get_stockpile_refill_actions(
        self,
        state: GameState,
    ) -> list[CookIngredient]:
        """
        Decide whether to trigger stockpile refill.
        
        Refill triggers when:
        1. Cooker is free
        2. No urgent order is blocked by needing a different action
        3. Stockpile slot is not at capacity (max 5)
        4. Ingredient has a stockpile assignment
        
        We don't proactively refill unless a cooker is idle.
        
        Args:
            state: Current game state
            
        Returns:
            List of CookIngredient actions to refill stockpile
        """
        actions: list[CookIngredient] = []
        
        for slot_idx, ingredient in enumerate(self.stockpile_assignments):
            current = state.get_stock_count(ingredient)
            
            if current >= 5:
                continue
            
            cooker = self._get_free_cooker_for(ingredient, state)
            if cooker is None:
                continue
            
            actions.append(CookIngredient(
                order_id=None,
                ingredient_name=ingredient,
                cooker_name=cooker,
                destination="stockpile",
                stockpile_slot=slot_idx,
            ))
        
        return actions
    
    def get_stockpile_info(self) -> dict[str, dict]:
        """Get current stockpile assignment and status info."""
        return {
            "assignments": self.stockpile_assignments,
        }
    
    def _get_free_cooker_for(self, ingredient: str, state: GameState) -> str | None:
        """
        Find a free cooker for an ingredient across all recipes that use it.
        
        Returns the first free cooker found, or None if all are busy.
        """
        for recipe in self.session.ordered_recipes:
            if ingredient not in recipe.raw_ingredients:
                continue
            cooker = self.session.get_cooker_for(ingredient, recipe)
            if cooker and state.is_cooker_free(cooker):
                return cooker
        return None
