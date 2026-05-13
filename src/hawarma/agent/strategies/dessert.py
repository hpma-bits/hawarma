"""
DessertStrategy: 甜点策略

甜点流程：
1. 食材A → 搅拌盆
2. 食材B → 搅拌盆
3. 调味（搅拌盆）
4. 搅拌（搅拌盆内单次左滑 swipe）
5. 搅拌盆 → 灶台烹饪
6. 烹饪完成 → 取餐台（直接从灶台）

决策优先级：
1. 送餐（灶台→取餐台）
2. 清理过期灶台
3. 移动搅拌盆到灶台（搅拌完成 + 灶台空闲）
4. 搅拌（食材齐全 + 未搅拌）
5. 添加调料（食材齐全 + 未调味）
6. 添加食材到搅拌盆
7. 清理搅拌盆（无匹配订单）
"""

from __future__ import annotations

from loguru import logger

from hawarma.core.actions import (
    Action,
    AddCondimentToMixingBowlAction,
    ClearCookerAction,
    ClearMixingBowlAction,
    MoveToMixingBowlAction,
    ServeFromCookerAction,
    StirAction,
    MoveMixingBowlToCookerAction,
)
from hawarma.core.state import UnifiedState
from hawarma.agent.strategy import Strategy
from hawarma.recipe import Station


class DessertStrategy(Strategy):
    """甜点策略：搅拌盆流水线"""

    def __init__(self):
        self._recipe_by_slug: dict[str, object] = {}
        self._recipe_condiments: dict[str, dict[str, int]] = {}
        self._dessert_recipes: dict[str, object] = {}

    def on_game_start(self, recipes: dict[str, object]) -> None:
        self._recipe_by_slug = recipes
        self._recipe_condiments = {}
        self._dessert_recipes = {}

        for slug, recipe in recipes.items():
            station = getattr(recipe, "station", Station.GASTRONOME)
            if station == Station.DESSERT:
                self._dessert_recipes[slug] = recipe

            condiments = getattr(recipe, "condiments", [])
            if isinstance(condiments, list):
                self._recipe_condiments[slug] = {c: 1 for c in condiments}
            elif isinstance(condiments, dict):
                self._recipe_condiments[slug] = dict(condiments)
            else:
                self._recipe_condiments[slug] = {}

    def decide(self, state: UnifiedState) -> Action | None:
        """甜点决策流水线"""

        if action := self._try_serve_from_cooker(state):
            return action

        if action := self._try_clear_expired(state):
            return action

        if action := self._try_move_mixing_bowl_to_cooker(state):
            return action

        if action := self._try_stir(state):
            return action

        if action := self._try_add_condiment(state):
            return action

        if action := self._try_add_to_mixing_bowl(state):
            return action

        if action := self._try_clear_mixing_bowl(state):
            return action

        return None

    # ====================================================================
    # 送餐（灶台→取餐台）
    # ====================================================================

    def _try_serve_from_cooker(self, state: UnifiedState) -> ServeFromCookerAction | None:
        if state.is_in_animation_window:
            return None

        for cooker_name, cooker in state.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            if state.time < cooker.done_at:
                continue
            if cooker.is_expired(state.time):
                continue

            recipe_slug = cooker.item_name
            for slot_idx, order in enumerate(state.orders):
                if order and not order.done and order.recipe_slug == recipe_slug:
                    return ServeFromCookerAction(cooker=cooker_name, slot_idx=slot_idx)

        return None

    # ====================================================================
    # 清理过期灶台
    # ====================================================================

    def _try_clear_expired(self, state: UnifiedState) -> ClearCookerAction | None:
        for cooker_name, cooker in state.cookers.items():
            if cooker.busy and cooker.is_expired(state.time):
                return ClearCookerAction(cooker=cooker_name)
        return None

    # ====================================================================
    # 移动搅拌盆到灶台
    # ====================================================================

    def _try_move_mixing_bowl_to_cooker(self, state: UnifiedState) -> MoveMixingBowlToCookerAction | None:
        mixing_bowl = state.mixing_bowl
        if not mixing_bowl.is_ready_to_cook:
            return None

        recipe_slug = mixing_bowl.target_recipe_slug
        if not recipe_slug:
            return None

        recipe = state.recipes.get(recipe_slug)
        if not recipe:
            return None

        cookers = getattr(recipe, "cookers", [])
        if not cookers:
            return None

        cooker_type = cookers[0]
        cooker_state = state.cookers.get(cooker_type)
        if cooker_state and not cooker_state.busy:
            return MoveMixingBowlToCookerAction(cooker=cooker_type)

        return None

    # ====================================================================
    # 搅拌
    # ====================================================================

    def _try_stir(self, state: UnifiedState) -> StirAction | None:
        mixing_bowl = state.mixing_bowl
        if mixing_bowl.is_empty:
            return None
        if mixing_bowl.is_stirred:
            return None
        if len(mixing_bowl.ingredients) < 2:
            return None

        recipe_slug = mixing_bowl.target_recipe_slug
        if recipe_slug:
            condiments_needed = self._recipe_condiments.get(recipe_slug, {})
            if condiments_needed:
                for condiment, count in condiments_needed.items():
                    if mixing_bowl.condiments.get(condiment, 0) < count:
                        return None

        return StirAction()

    # ====================================================================
    # 添加调料
    # ====================================================================

    def _try_add_condiment(self, state: UnifiedState) -> AddCondimentToMixingBowlAction | None:
        mixing_bowl = state.mixing_bowl
        if mixing_bowl.is_empty:
            return None
        if mixing_bowl.is_stirred:
            return None

        recipe_slug = mixing_bowl.target_recipe_slug
        if not recipe_slug:
            return None

        # 所有食材齐全后才能调味
        recipe = state.recipes.get(recipe_slug)
        if recipe:
            raw_ings = getattr(recipe, "raw_ingredients", [])
            if not all(ing in mixing_bowl.ingredients for ing in raw_ings):
                return None

        condiments_needed = self._recipe_condiments.get(recipe_slug, {})
        if not condiments_needed:
            return None

        for condiment, count in condiments_needed.items():
            current = mixing_bowl.condiments.get(condiment, 0)
            if current < count:
                return AddCondimentToMixingBowlAction(condiment=condiment)

        return None

    # ====================================================================
    # 添加食材到搅拌盆
    # ====================================================================

    def _try_add_to_mixing_bowl(self, state: UnifiedState) -> MoveToMixingBowlAction | None:
        mixing_bowl = state.mixing_bowl
        if len(mixing_bowl.ingredients) >= 2:
            return None

        # 如果搅拌盆已有目标配方，检查是否有活跃订单匹配
        if mixing_bowl.target_recipe_slug:
            has_active = any(
                o and not o.done and o.recipe_slug == mixing_bowl.target_recipe_slug
                for o in state.orders
            )
            if not has_active:
                # 无匹配订单，让 clear 优先级处理
                return None
        
        # 如果搅拌盆已有目标配方，只添加该配方所需的食材
        if mixing_bowl.target_recipe_slug:
            recipe = state.recipes.get(mixing_bowl.target_recipe_slug)
            if recipe:
                raw_ings = getattr(recipe, "raw_ingredients", [])
                for ing in raw_ings:
                    if ing not in mixing_bowl.ingredients:
                        return MoveToMixingBowlAction(ingredient=ing)
            return None

        # 搅拌盆空闲：按优先级取第一个甜点订单的第一个食材
        # 收集已在途的 recipe slug（灶台上正在烹饪的），每个在途批次可"覆盖"一个同名订单
        in_progress_slugs: list[str] = []
        for c in state.cookers.values():
            if c.busy and c.item_name:
                in_progress_slugs.append(c.item_name)

        for _, order in self._prioritized_dessert_orders(state):
            recipe = state.recipes.get(order.recipe_slug)
            if not recipe:
                continue
            raw_ings = getattr(recipe, "raw_ingredients", [])
            if not raw_ings:
                continue
            if order.recipe_slug in in_progress_slugs:
                in_progress_slugs.remove(order.recipe_slug)
                continue
            return MoveToMixingBowlAction(ingredient=raw_ings[0])

        return None

    # ====================================================================
    # 清理搅拌盆
    # ====================================================================

    def _try_clear_mixing_bowl(self, state: UnifiedState) -> ClearMixingBowlAction | None:
        mixing_bowl = state.mixing_bowl
        if mixing_bowl.is_empty:
            return None

        recipe_slug = mixing_bowl.target_recipe_slug
        if recipe_slug:
            has_active = any(
                o and not o.done and o.recipe_slug == recipe_slug
                for o in state.orders
            )
            if has_active:
                return None

        return ClearMixingBowlAction()

    # ====================================================================
    # 辅助方法
    # ====================================================================

    def _prioritized_dessert_orders(self, state: UnifiedState) -> list[tuple[int, object]]:
        """按优先级排序甜点订单（rush 优先，然后先进先出）"""
        orders_with_idx = []
        for i, order in enumerate(state.orders):
            if order is not None and not order.done:
                recipe = state.recipes.get(order.recipe_slug)
                if recipe:
                    station = getattr(recipe, "station", Station.GASTRONOME)
                    if station == Station.DESSERT:
                        orders_with_idx.append((i, order))

        def sort_key(item):
            _, order = item
            rush_priority = 0 if order.is_rush else 1
            timeout_remaining = order.timeout_at - state.time
            return (rush_priority, timeout_remaining)

        orders_with_idx.sort(key=sort_key)
        return orders_with_idx
