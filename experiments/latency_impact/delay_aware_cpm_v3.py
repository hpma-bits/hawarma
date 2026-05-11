"""
DelayAwareCPMStrategyV3: 延迟感知策略 - 智能预烹饪版

基于 V2 的成功方向（激进预烹饪），增加智能选择：
- 只预烹饪烹饪时长 > 1.0s 的食材（短时食材不值得 600ms 动作开销）
- 高价值订单优先：visibility 阈值跨越的订单获得预烹饪加成
- 更智能的存储：食材烹饪完成立即存，但按紧急程度排序
"""

from __future__ import annotations

from hawarma.core.actions import CookAction, MoveToStockpileAction
from hawarma.core.state import UnifiedState
from hawarma.agent.strategies.cpm import CPMStrategy


class DelayAwareCPMStrategyV3(CPMStrategy):
    """
    延迟感知策略 V3 — 智能预烹饪版。

    核心调整：
    1. 只预烹饪烹饪时长 > 1.0s 的食材
    2. 高价值 orders (high visibility threshold crossing) 的食材有更高预烹饪优先级
    3. 更快的存储 + 更智能的存储优先级
    """

    # 预烹饪最小时长：短于这个值的食材不值得预烹饪
    MIN_PRECOOK_DURATION = 1.0

    # 存储更快：从 2.0s 降到 1.0s
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
                    # 跳过短时食材
                    if duration < self.MIN_PRECOOK_DURATION:
                        continue
                    score = duration  # 时长越长，预烹饪价值越高
                    candidates.append((ing_name, cooker, duration, score))
            if candidates:
                candidates.sort(key=lambda x: x[3], reverse=True)
                ing_name, cooker, duration, _ = candidates[0]
                order_id = self._get_order_id_for_ingredient(state, ing_name)
                return CookAction(ingredient=ing_name, cooker=cooker, duration=duration, order_id=order_id)
            return None

        # 先尝试为活跃订单预烹饪
        result = _try_precook_for_slugs(active_order_slugs)
        if result:
            return result

        # 再尝试为所有可能的配方预烹饪
        all_slugs = set(self._recipe_ingredient_cooker.keys())
        return _try_precook_for_slugs(all_slugs - active_order_slugs)

    def _try_store_to_stockpile(self, state: UnifiedState) -> MoveToStockpileAction | None:
        """更快存储 + 按需紧急度排序"""
        assembly = state.assembly
        needed = self._get_needed_ingredient_names(state)

        # 收集所有可存储的食材
        candidates: list[tuple[str, str, float, float]] = []  # (cooker_name, ing_name, cooker_type, priority)
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

            # 紧急性：需要的食材 > 快过期的食材 > 普通食材
            if ing_name in needed:
                priority = 100 + time_since_done
            elif time_since_done > self.EXPIRED_THRESHOLD - 1.0:
                priority = 50 + time_since_done
            else:
                priority = time_since_done

            candidates.append((cooker_name, ing_name, cooker_type, priority))

        if not candidates:
            return None

        # 按紧急性排序
        candidates.sort(key=lambda x: x[3], reverse=True)
        cooker_name, ing_name, cooker_type, _ = candidates[0]

        # 如果食材可以立即移到组装站且组装站空闲，让 _try_move_to_assembly 处理
        if assembly.is_free and not assembly.ingredients_cookers and ing_name not in needed:
            pass  # 由 _try_move_to_assembly 处理

        slot = self._try_increment_stockpile(state, ing_name, cooker_type)
        if slot is None:
            slot = self._find_available_slot(state, ing_name, cooker_type)
        if slot:
            return MoveToStockpileAction(cooker=cooker_name, slot=slot)

        return None
