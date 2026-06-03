"""
CPM 系列策略的 Rush 优先级 tiebreaker 单元测试

回归 bug: cpm.py / visibility_aware.py / cpm_enhanced.py 的
_prioritized_orders 仅按 CP 排序，导致两个同 recipe 订单（同 CP）
的排序退化为稳定排序保留原 slot 顺序，Rush 未被优先。

修复：在 sort key 中追加 rush_priority（0=Rush, 1=Normal）作为
tiebreaker，确保 CP 相同时 Rush 优先。
"""

import unittest

from hawarma.core.state import UnifiedState
from hawarma.core.models import AssemblyState, CookerState, Order
from hawarma.agent.strategies.cpm import CPMCascadeStrategy
from hawarma.agent.strategies.visibility_aware import VisibilityAwareCascadeStrategy
from hawarma.agent.strategies.cpm_enhanced import CPMEnhancedCascadeStrategy
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
    """验证同 CP 时 Rush 排在 Normal 之前"""

    def setUp(self):
        # 两个食材 + 一个调料的简单 recipe
        self.recipe = _make_recipe(
            "testDish",
            raw_ings=["ing_a", "ing_b"],
            cookers=["oven", "pot"],
            durations=[4.0, 2.0],
            condiments={"sauce": 1},
        )
        self.recipes = {"testDish": self.recipe}

        # 完全组装好的 assembly：两个食材 + 调料齐全
        self.complete_assembly = AssemblyState(
            ingredients=[("ing_a", "oven", 0.0), ("ing_b", "pot", 0.0)],
            target_recipe_slug="testDish",
            owner_order_id=1,
            condiments={"sauce": 1},
        )

    def _make_orders(self, rush_slot, normal_slot):
        """生成 NORMAL 和 RUSH 两个同 recipe 订单"""
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

    # ==================================================================
    # CPMCascadeStrategy
    # ==================================================================

    def test_cpm_rush_first_when_rush_in_higher_slot(self):
        """RUSH 在 slot 1, NORMAL 在 slot 0 — Rush 应优先"""
        strategy = CPMCascadeStrategy()
        strategy.on_game_start(self.recipes)
        state = _make_state(
            self.recipes,
            orders=self._make_orders(rush_slot=1, normal_slot=0),
        )
        result = list(strategy._prioritized_orders(state))
        slot_indices = [s for s, _ in result]
        self.assertEqual(slot_indices, [1, 0])

    def test_cpm_rush_first_when_rush_in_lower_slot(self):
        """RUSH 在 slot 0, NORMAL 在 slot 1 — Rush 应优先"""
        strategy = CPMCascadeStrategy()
        strategy.on_game_start(self.recipes)
        state = _make_state(
            self.recipes,
            orders=self._make_orders(rush_slot=0, normal_slot=1),
        )
        result = list(strategy._prioritized_orders(state))
        slot_indices = [s for s, _ in result]
        self.assertEqual(slot_indices, [0, 1])

    def test_cpm_decide_serves_rush_slot(self):
        """end-to-end: assembly 完整 + 两同 recipe 订单 → 送餐到 RUSH 槽位"""
        strategy = CPMCascadeStrategy()
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

    # ==================================================================
    # VisibilityAwareCascadeStrategy (继承自 CPM)
    # ==================================================================

    def test_visibility_aware_rush_first(self):
        strategy = VisibilityAwareCascadeStrategy()
        strategy.on_game_start(self.recipes)
        state = _make_state(
            self.recipes,
            orders=self._make_orders(rush_slot=1, normal_slot=0),
        )
        result = list(strategy._prioritized_orders(state))
        slot_indices = [s for s, _ in result]
        self.assertEqual(slot_indices, [1, 0])

    def test_visibility_aware_decide_serves_rush_slot(self):
        strategy = VisibilityAwareCascadeStrategy()
        strategy.on_game_start(self.recipes)
        state = _make_state(
            self.recipes,
            orders=self._make_orders(rush_slot=1, normal_slot=0),
            assembly=self.complete_assembly,
        )
        action = strategy.decide(state)
        self.assertIsNotNone(action)
        self.assertEqual(action.slot_idx, 1)

    # ==================================================================
    # CPMEnhancedCascadeStrategy (继承自 VisibilityAware)
    # ==================================================================

    def test_cpm_enhanced_rush_first(self):
        strategy = CPMEnhancedCascadeStrategy()
        strategy.on_game_start(self.recipes)
        state = _make_state(
            self.recipes,
            orders=self._make_orders(rush_slot=1, normal_slot=0),
        )
        result = list(strategy._prioritized_orders(state))
        slot_indices = [s for s, _ in result]
        self.assertEqual(slot_indices, [1, 0])

    def test_cpm_enhanced_decide_serves_rush_slot(self):
        """这是用户场景的精确复现：gastronome 模式 = CPMEnhancedCascadeStrategy"""
        strategy = CPMEnhancedCascadeStrategy()
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


if __name__ == "__main__":
    unittest.main()
