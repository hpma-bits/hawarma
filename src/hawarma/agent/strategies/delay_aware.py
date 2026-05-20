"""
DelayAwareCascadeStrategy: 贪心瀑布 - 延迟感知变体

覆写 _try_precook（更激进预烹饪：烹饪时长 > 1.0s 才预烹饪，库存上限 4）
覆写 _try_store_to_stockpile（更激进存储：烹饪完成后快速存储，释放灶台）

在显式 action_delay(300ms) + detection_delay(400ms) 条件下优化。
Benchmark (50局，带延迟)：
  1. DelayAwareCascadeStrategy  4711  ★
  2. CPMCascadeStrategy          4614  (Δ -97, n.s.)
"""

from __future__ import annotations

from hawarma.core.state import UnifiedState
from hawarma.agent.strategies.cpm import CPMCascadeStrategy


class DelayAwareCascadeStrategy(CPMCascadeStrategy):
    """贪心瀑布变体：延迟感知 - 智能预烹饪 + 快速存储"""

    MIN_PRECOOK_DURATION = 1.0
    PRECOOK_STORE_THRESHOLD = 1.0
    WARN_THRESHOLD = 3.0
    MAX_PRECOOK_STOCKPILE = 4
    PRECOOK_STOP_TIME = 15.0

    def _try_precook(self, state: UnifiedState, assembly_ings: list[str]) -> CookAction | None:
        remaining_time = state.game_duration - state.time
        if remaining_time < self.PRECOOK_STOP_TIME:
            return None

        free_cookers = [name for name, c in state.cookers.items() if not c.busy]
        if not free_cookers:
            return None

        total_in_stockpile = sum(slot.count for slot in state.stockpile.values())
        if total_in_stockpile >= self.MAX_PRECOOK_STOCKPILE:
            return None

        cooking_combos: set[tuple[str, str]] = set()
        for cooker in state.cookers.values():
            if cooker.busy:
                cooking_combos.add((cooker.item_name, cooker.cooker_type))

        active_order_slugs = {o.recipe_slug for o in state.orders if o and not o.done}

        def _try_precook_for_slugs(slugs: set[str]) -> CookAction | None:
            candidates: list[tuple[str, str, float, float]] = []
            for slug in slugs:
                ics = self._recipe_ingredient_cooker.get(slug, [])
                for ing_name, cooker, duration in ics:
                    combo = (ing_name, cooker)
                    if combo in cooking_combos:
                        continue
                    if ing_name in assembly_ings:
                        continue
                    if self._has_in_stockpile(state, ing_name, cooker):
                        continue
                    if cooker not in free_cookers:
                        continue
                    if duration < self.MIN_PRECOOK_DURATION:
                        continue
                    score = duration
                    candidates.append((ing_name, cooker, duration, score))
            if candidates:
                candidates.sort(key=lambda x: x[3], reverse=True)
                ing_name, cooker, duration, _ = candidates[0]
                order_id = self._get_order_id_for_ingredient(state, ing_name)
                return CookAction(ingredient=ing_name, cooker=cooker, duration=duration, order_id=order_id)
            return None

        result = _try_precook_for_slugs(active_order_slugs)
        if result:
            return result

        all_slugs = set(self._recipe_ingredient_cooker.keys())
        return _try_precook_for_slugs(all_slugs - active_order_slugs)

    def _try_store_to_stockpile(self, state: UnifiedState) -> MoveToStockpileAction | None:
        assembly = state.assembly
        needed = self._get_needed_ingredient_names(state)

        candidates: list[tuple[str, str, float, float]] = []
        for cooker_name, cooker in state.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            if state.time < cooker.done_at:
                continue
            ing_name = cooker.item_name
            cooker_type = cooker.cooker_type
            time_since_done = state.time - cooker.done_at

            if cooker.is_expired(state.time):
                continue

            if ing_name in needed:
                priority = 100 + time_since_done
            elif time_since_done > self.EXPIRED_THRESHOLD - 1.0:
                priority = 50 + time_since_done
            else:
                priority = time_since_done

            candidates.append((cooker_name, ing_name, cooker_type, priority))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[3], reverse=True)
        cooker_name, ing_name, cooker_type, _ = candidates[0]

        slot = self._try_increment_stockpile(state, ing_name, cooker_type)
        if slot is None:
            slot = self._find_available_slot(state, ing_name, cooker_type)
        if slot:
            return MoveToStockpileAction(cooker=cooker_name, slot=slot)

        return None


# 向后兼容别名
DelayAwareCPMStrategy = DelayAwareCascadeStrategy
