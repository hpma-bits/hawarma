"""
GastronomeStrategy 的 Rush 优先级 tiebreaker 单元测试

回归 bug: 历史上 6 个 Gastronome 策略（GreedyCascade/CPMCascade/VisibilityAware/
CPMEnhanced/PreemptScore/DelayAware）共享 10 级贪心瀑布框架，但仅 3 个 CPM
变体的 _prioritized_orders 实现了 Rush tiebreaker，导致两个同 recipe 订单
（同 CP）的排序退化为稳定排序保留原 slot 顺序，Rush 未被优先。

修复：在 sort key 中追加 rush_priority（0=Rush, 1=Normal）作为
tiebreaker，确保 CP 相同时 Rush 优先。

合并后：所有变体已合并为单一 GastronomeStrategy，本文件验证此单一实现的
Rush tiebreaker 正确性（_prioritized_orders + end-to-end serve）。
"""

import unittest

from hawarma.core.state import UnifiedState
from hawarma.core.models import AssemblyState, CookerState, Order
from hawarma.agent.strategies.gastronome import GastronomeStrategy
from hawarma.recipe import Recipe, Station


def _make_recipe(slug, raw_ings, cookers, durations, condiments):
    return Recipe(
        slug=slug,
        name=slug,
        raw_ingredients=raw_ings,
        cookers=cookers,
        cookers_layout=cookers,
        cook_durations=durations,
        condiments=condiments,
        station=Station.GASTRONOME,
    )


def _make_state(recipes, **overrides):
    defaults = {
        "time": 10.0,
        "orders": (None, None, None, None),
        "cookers": {
            "oven": CookerState(cooker_type="oven"),
            "pot": CookerState(cooker_type="pot"),
        },
        "assembly": AssemblyState(),
        "stockpile": {},
        "recipes": recipes,
        "game_duration": 93.0,
        "is_in_animation_window": False,
        "total_visibility": 0.0,
    }
    defaults.update(overrides)
    return UnifiedState(**defaults)


class TestRushTiebreaker(unittest.TestCase):
    """验证 GastronomeStrategy 在同 CP 时 Rush 排在 Normal 之前"""

    def setUp(self):
        self.recipe = _make_recipe(
            "testDish",
            raw_ings=["ing_a", "ing_b"],
            cookers=["oven", "pot"],
            durations=[4.0, 2.0],
            condiments={"sauce": 1},
        )
        self.recipes = {"testDish": self.recipe}

        self.complete_assembly = AssemblyState(
            ingredients=[("ing_a", "oven", 0.0), ("ing_b", "pot", 0.0)],
            target_recipe_slug="testDish",
            owner_order_id=1,
            condiments={"sauce": 1},
        )

    def _make_orders(self, rush_slot, normal_slot):
        rush = Order(
            order_id=99,
            recipe_slug="testDish",
            is_rush=True,
            created_at=10.0,
            timeout_at=50.0,
            done=False,
        )
        normal = Order(
            order_id=1,
            recipe_slug="testDish",
            is_rush=False,
            created_at=2.0,
            timeout_at=72.0,
            done=False,
        )
        orders = [None, None, None, None]
        orders[normal_slot] = normal
        orders[rush_slot] = rush
        return tuple(orders)

    def test_rush_first_when_rush_in_higher_slot(self):
        """RUSH 在 slot 1, NORMAL 在 slot 0 — Rush 应优先"""
        strategy = GastronomeStrategy()
        strategy.on_game_start(self.recipes)
        state = _make_state(
            self.recipes,
            orders=self._make_orders(rush_slot=1, normal_slot=0),
        )
        result = list(strategy._prioritized_orders(state))
        slot_indices = [s for s, _ in result]
        self.assertEqual(slot_indices, [1, 0])

    def test_rush_first_when_rush_in_lower_slot(self):
        """RUSH 在 slot 0, NORMAL 在 slot 1 — Rush 应优先"""
        strategy = GastronomeStrategy()
        strategy.on_game_start(self.recipes)
        state = _make_state(
            self.recipes,
            orders=self._make_orders(rush_slot=0, normal_slot=1),
        )
        result = list(strategy._prioritized_orders(state))
        slot_indices = [s for s, _ in result]
        self.assertEqual(slot_indices, [0, 1])

    def test_decide_serves_rush_slot(self):
        """end-to-end: assembly 完整 + 两同 recipe 订单 → 送餐到 RUSH 槽位"""
        strategy = GastronomeStrategy()
        strategy.on_game_start(self.recipes)
        state = _make_state(
            self.recipes,
            orders=self._make_orders(rush_slot=1, normal_slot=0),
            assembly=self.complete_assembly,
        )
        action = strategy.decide(state)
        self.assertIsNotNone(action)
        self.assertEqual(action.__class__.__name__, "ServeOrderAction")
        self.assertEqual(action.slot_idx, 1)

    def test_rush_beats_normal_even_with_lower_cp(self):
        """RUSH 的 CP 应该不会被 visibility 跨越/单食材加成等干扰 normal 排名
        — 验证 rush_priority 是 sort key 的**最后**一维 tiebreaker
        """
        strategy = GastronomeStrategy()
        strategy.on_game_start(self.recipes)
        rush = Order(
            order_id=99,
            recipe_slug="testDish",
            is_rush=True,
            created_at=10.0,
            timeout_at=50.0,
            done=False,
        )
        normal = Order(
            order_id=1,
            recipe_slug="testDish",
            is_rush=False,
            created_at=2.0,
            timeout_at=72.0,
            done=False,
        )
        orders = [None, None, None, None]
        orders[0] = normal
        orders[3] = rush
        state = _make_state(
            self.recipes,
            orders=tuple(orders),
            total_visibility=39.0,
        )
        result = list(strategy._prioritized_orders(state))
        slot_indices = [s for s, _ in result]
        self.assertEqual(slot_indices[0], 3, "Rush should be first even in slot 3 (worst slot)")


if __name__ == "__main__":
    unittest.main()
