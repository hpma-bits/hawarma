"""
DessertStrategy 单元测试

基于 Design Doc 决策优先级：
1. ServeFromCooker — 灶台完成 → 送餐
2. ClearCooker — 过期清理
3. MoveMixingBowlToCooker — 搅拌完成 → 灶台
4. Stir — 食材齐全 + 调料齐全 → 搅拌
5. AddCondimentToMixingBowl — 食材齐全 → 调味
6. MoveToMixingBowl — 添加食材
7. ClearMixingBowl — 无匹配订单 → 清理
"""

import unittest

from hawarma.core.state import UnifiedState
from hawarma.core.models import CookerState, AssemblyState, MixingBowlState, Order
from hawarma.core.actions import (
    ServeFromCookerAction,
    ClearCookerAction,
    MoveMixingBowlToCookerAction,
    StirAction,
    AddCondimentToMixingBowlAction,
    MoveToMixingBowlAction,
    ClearMixingBowlAction,
)
from hawarma.agent.strategies.dessert import DessertStrategy
from hawarma.recipe import Recipe, Station


def _make_mock_recipe(slug, raw_ings, cookers, durations, condiments, station=Station.DESSERT):
    return Recipe(
        slug=slug,
        name=slug,
        raw_ingredients=raw_ings,
        cookers=cookers,
        cookers_layout=cookers,
        cook_durations=durations,
        condiments=condiments,
        station=station,
    )


class TestDessertStrategy(unittest.TestCase):

    def setUp(self):
        self.strategy = DessertStrategy()

        # Mock recipes: two dessert recipes
        self.r1 = _make_mock_recipe(
            "domeFigueMiel", ["flour", "honey"], ["dessert_oven"], [3.0], ["sugar"]
        )
        self.r2 = _make_mock_recipe(
            "velvetTiramisu", ["cream", "coffee"], ["cooling_plate"], [4.0], ["cocoa"]
        )
        self.recipes = {"domeFigueMiel": self.r1, "velvetTiramisu": self.r2}
        self.strategy.on_game_start(self.recipes)

    def _make_state(self, **overrides):
        """Helper to build a UnifiedState with sensible defaults."""
        defaults = {
            "time": 10.0,
            "orders": (
                Order(order_id=1, recipe_slug="domeFigueMiel", is_rush=False,
                          created_at=0.0, timeout_at=80.0, done=False),
                None, None, None,
            ),
            "cookers": {
                "dessert_oven": CookerState(cooker_type="dessert_oven"),
                "cooling_plate": CookerState(cooker_type="cooling_plate"),
            },
            "assembly": AssemblyState(),
            "stockpile": {},
            "recipes": self.recipes,
            "game_duration": 93.0,
            "is_in_animation_window": False,
            "total_visibility": 0.0,
            "mixing_bowl": MixingBowlState(),
        }
        defaults.update(overrides)
        return UnifiedState(**defaults)

    # ================================================================
    # Priority 7: ClearMixingBowl (earliest test — easiest to isolate)
    # ================================================================

    def test_clear_mixing_bowl_when_no_active_order(self):
        """When mixing bowl has ingredients but no matching order, clear it."""
        bowl = MixingBowlState(
            ingredients=["cream"],
            target_recipe_slug="velvetTiramisu",
        )
        state = self._make_state(mixing_bowl=bowl)
        action = self.strategy.decide(state)
        self.assertIsInstance(action, ClearMixingBowlAction)

    def test_no_clear_mixing_bowl_when_order_active(self):
        """Don't clear mixing bowl when a matching order exists."""
        bowl = MixingBowlState(
            ingredients=["flour"],
            target_recipe_slug="domeFigueMiel",
        )
        state = self._make_state(mixing_bowl=bowl)
        action = self.strategy.decide(state)
        # Should not be ClearMixingBowl; should try other priorities
        self.assertNotIsInstance(action, ClearMixingBowlAction)

    # ================================================================
    # Priority 6: MoveToMixingBowl
    # ================================================================

    def test_add_to_mixing_bowl_with_empty_bowl(self):
        """When mixing bowl is empty and a dessert order exists, add first ingredient."""
        state = self._make_state(mixing_bowl=MixingBowlState())
        action = self.strategy.decide(state)
        self.assertIsInstance(action, MoveToMixingBowlAction)
        self.assertEqual(action.ingredient, "flour")

    def test_add_second_ingredient(self):
        """When mixing bowl has one ingredient, add the second."""
        bowl = MixingBowlState(
            ingredients=["flour"],
            target_recipe_slug="domeFigueMiel",
        )
        state = self._make_state(mixing_bowl=bowl)
        action = self.strategy.decide(state)
        self.assertIsInstance(action, MoveToMixingBowlAction)
        self.assertEqual(action.ingredient, "honey")

    def test_no_add_when_bowl_full(self):
        """When mixing bowl has 2 ingredients, don't try to add more."""
        bowl = MixingBowlState(
            ingredients=["flour", "honey"],
            target_recipe_slug="domeFigueMiel",
        )
        state = self._make_state(mixing_bowl=bowl)
        action = self.strategy.decide(state)
        self.assertNotIsInstance(action, MoveToMixingBowlAction)

    # ── Duplicate batch prevention: cooker in-progress dedup ──

    def test_no_add_when_cooker_has_same_recipe_single_order(self):
        """单订单 recipe 已在灶台 → 不应重复启动新批次."""
        cookers = {
            "dessert_oven": CookerState(
                busy=True, cooker_type="dessert_oven",
                item_name="domeFigueMiel", started_at=5.0, done_at=8.0, expired_at=15.0,
            ),
            "cooling_plate": CookerState(cooker_type="cooling_plate"),
        }
        state = self._make_state(
            mixing_bowl=MixingBowlState(),
            cookers=cookers,
            time=7.0,
        )
        action = self.strategy.decide(state)
        # 烹饪进行中，无额外同名 order，不启动新批次
        self.assertNotIsInstance(action, MoveToMixingBowlAction)

    def test_add_when_cooker_has_same_recipe_two_orders(self):
        """双同名 order，灶台已有 1 份 → 跳过第一 order，为第二 order 生产."""
        orders = (
            Order(order_id=1, recipe_slug="domeFigueMiel", is_rush=False,
                      created_at=0.0, timeout_at=80.0, done=False),
            Order(order_id=2, recipe_slug="domeFigueMiel", is_rush=False,
                      created_at=1.0, timeout_at=80.0, done=False),
            None, None,
        )
        cookers = {
            "dessert_oven": CookerState(
                busy=True, cooker_type="dessert_oven",
                item_name="domeFigueMiel", started_at=5.0, done_at=8.0, expired_at=15.0,
            ),
            "cooling_plate": CookerState(cooker_type="cooling_plate"),
        }
        state = self._make_state(
            orders=orders,
            mixing_bowl=MixingBowlState(),
            cookers=cookers,
            time=7.0,
        )
        action = self.strategy.decide(state)
        self.assertIsInstance(action, MoveToMixingBowlAction)
        self.assertEqual(action.ingredient, "flour")

    def test_add_when_cooker_has_different_recipe(self):
        """灶台忙 A recipe，但是 B recipe 的 order → 正常启动 B 批次."""
        orders = (
            Order(order_id=2, recipe_slug="velvetTiramisu", is_rush=False,
                      created_at=1.0, timeout_at=80.0, done=False),
            None, None, None,
        )
        cookers = {
            "dessert_oven": CookerState(
                busy=True, cooker_type="dessert_oven",
                item_name="domeFigueMiel", started_at=5.0, done_at=8.0, expired_at=15.0,
            ),
            "cooling_plate": CookerState(cooker_type="cooling_plate"),
        }
        state = self._make_state(
            orders=orders,
            mixing_bowl=MixingBowlState(),
            cookers=cookers,
            time=7.0,
        )
        action = self.strategy.decide(state)
        self.assertIsInstance(action, MoveToMixingBowlAction)
        self.assertEqual(action.ingredient, "cream")

    def test_three_orders_two_batches_third_starts(self):
        """三同名 order，灶台 1 份 + 搅拌盆 1 份 → 第三 order 仍启动."""

        # 1. 灶台忙，搅拌盆空闲
        bowl0 = MixingBowlState()
        cookers0 = {
            "dessert_oven": CookerState(
                busy=True, cooker_type="dessert_oven",
                item_name="domeFigueMiel", started_at=5.0, done_at=8.0, expired_at=15.0,
            ),
            "cooling_plate": CookerState(cooker_type="cooling_plate"),
        }
        orders = (
            Order(order_id=1, recipe_slug="domeFigueMiel", is_rush=False,
                      created_at=0.0, timeout_at=80.0, done=False),
            Order(order_id=2, recipe_slug="domeFigueMiel", is_rush=False,
                      created_at=1.0, timeout_at=80.0, done=False),
            Order(order_id=3, recipe_slug="domeFigueMiel", is_rush=False,
                      created_at=2.0, timeout_at=80.0, done=False),
            None,
        )
        state0 = self._make_state(
            orders=orders, mixing_bowl=bowl0, cookers=cookers0, time=7.0,
        )
        action0 = self.strategy.decide(state0)
        self.assertIsInstance(action0, MoveToMixingBowlAction)
        self.assertEqual(action0.ingredient, "flour")

        # 2. 模拟：flour 已入搅拌盆, target_recipe_slug=domeFigueMiel
        bowl1 = MixingBowlState(
            ingredients=["flour"],
            target_recipe_slug="domeFigueMiel",
        )
        state1 = self._make_state(
            orders=orders, mixing_bowl=bowl1, cookers=cookers0, time=7.0,
        )
        action1 = self.strategy.decide(state1)
        self.assertIsInstance(action1, MoveToMixingBowlAction)
        self.assertEqual(action1.ingredient, "honey")

    # ================================================================
    # Priority 5: AddCondimentToMixingBowl
    # ================================================================

    def test_add_condiment_when_ingredients_complete(self):
        """When bowl has 2 ingredients and condiments needed, add condiment."""
        bowl = MixingBowlState(
            ingredients=["flour", "honey"],
            target_recipe_slug="domeFigueMiel",
        )
        state = self._make_state(mixing_bowl=bowl)
        action = self.strategy.decide(state)
        self.assertIsInstance(action, AddCondimentToMixingBowlAction)
        self.assertEqual(action.condiment, "sugar")

    def test_no_add_condiment_when_bowl_empty(self):
        """When bowl is empty, don't add condiment."""
        state = self._make_state(mixing_bowl=MixingBowlState())
        action = self.strategy.decide(state)
        self.assertNotIsInstance(action, AddCondimentToMixingBowlAction)

    # ================================================================
    # Priority 4: Stir
    # ================================================================

    def test_stir_when_ready(self):
        """When bowl has 2 ingredients and all condiments, stir."""
        bowl = MixingBowlState(
            ingredients=["flour", "honey"],
            condiments={"sugar": 1},
            target_recipe_slug="domeFigueMiel",
        )
        state = self._make_state(mixing_bowl=bowl)
        action = self.strategy.decide(state)
        self.assertIsInstance(action, StirAction)

    def test_no_stir_when_condiments_missing(self):
        """Don't stir when condiments are not complete."""
        bowl = MixingBowlState(
            ingredients=["flour", "honey"],
            target_recipe_slug="domeFigueMiel",
            # no condiments added yet
        )
        state = self._make_state(mixing_bowl=bowl)
        action = self.strategy.decide(state)
        self.assertNotIsInstance(action, StirAction)

    def test_no_stir_when_already_stirred(self):
        """Don't stir again when already stirred."""
        bowl = MixingBowlState(
            ingredients=["flour", "honey"],
            condiments={"sugar": 1},
            target_recipe_slug="domeFigueMiel",
            is_stirred=True,
        )
        state = self._make_state(mixing_bowl=bowl)
        action = self.strategy.decide(state)
        self.assertNotIsInstance(action, StirAction)

    # ================================================================
    # Priority 3: MoveMixingBowlToCooker
    # ================================================================

    def test_move_to_cooker_when_stirred_and_cooker_free(self):
        """When bowl is stirred and cooker free, move to cooker."""
        bowl = MixingBowlState(
            ingredients=["flour", "honey"],
            condiments={"sugar": 1},
            target_recipe_slug="domeFigueMiel",
            is_stirred=True,
        )
        state = self._make_state(mixing_bowl=bowl)
        action = self.strategy.decide(state)
        self.assertIsInstance(action, MoveMixingBowlToCookerAction)
        self.assertEqual(action.cooker, "dessert_oven")

    def test_no_move_to_cooker_when_cooker_busy(self):
        """When cooker is busy, don't move to cooker."""
        bowl = MixingBowlState(
            ingredients=["flour", "honey"],
            condiments={"sugar": 1},
            target_recipe_slug="domeFigueMiel",
            is_stirred=True,
        )
        cookers = {
            "dessert_oven": CookerState(busy=True, cooker_type="dessert_oven",
                                        item_name="something", started_at=5.0,
                                        done_at=999.0, expired_at=999.0),
            "cooling_plate": CookerState(cooker_type="cooling_plate"),
        }
        state = self._make_state(mixing_bowl=bowl, cookers=cookers)
        action = self.strategy.decide(state)
        self.assertNotIsInstance(action, MoveMixingBowlToCookerAction)

    # ================================================================
    # Priority 2: ClearCooker
    # ================================================================

    def test_clear_expired_cooker(self):
        """When a cooker has expired, clear it."""
        bowl = MixingBowlState()  # Empty bowl, so we test higher priority
        cookers = {
            "dessert_oven": CookerState(
                busy=True, cooker_type="dessert_oven",
                item_name="expired", started_at=0.0, done_at=1.0, expired_at=5.0,
            ),
            "cooling_plate": CookerState(cooker_type="cooling_plate"),
        }
        state = self._make_state(mixing_bowl=bowl, cookers=cookers, time=10.0)
        action = self.strategy.decide(state)
        self.assertIsInstance(action, ClearCookerAction)
        self.assertEqual(action.cooker, "dessert_oven")

    # ================================================================
    # Priority 1: ServeFromCooker
    # ================================================================

    def test_serve_from_cooker_when_done(self):
        """When cooker is done and order matches, serve."""
        bowl = MixingBowlState()  # empty bowl
        cookers = {
            "dessert_oven": CookerState(
                busy=True, cooker_type="dessert_oven",
                item_name="domeFigueMiel", started_at=0.0, done_at=5.0, expired_at=12.0,
            ),
            "cooling_plate": CookerState(cooker_type="cooling_plate"),
        }
        state = self._make_state(mixing_bowl=bowl, cookers=cookers, time=10.0)
        action = self.strategy.decide(state)
        self.assertIsInstance(action, ServeFromCookerAction)
        self.assertEqual(action.cooker, "dessert_oven")
        self.assertEqual(action.slot_idx, 0)

    def test_no_serve_when_cooker_not_done(self):
        """When cooker is not done yet, don't serve."""
        bowl = MixingBowlState()
        cookers = {
            "dessert_oven": CookerState(
                busy=True, cooker_type="dessert_oven",
                item_name="domeFigueMiel", started_at=0.0, done_at=20.0, expired_at=27.0,
            ),
            "cooling_plate": CookerState(cooker_type="cooling_plate"),
        }
        state = self._make_state(mixing_bowl=bowl, cookers=cookers, time=10.0)
        action = self.strategy.decide(state)
        self.assertNotIsInstance(action, ServeFromCookerAction)

    # ================================================================
    # Rush priority
    # ================================================================

    def test_rush_order_prioritized(self):
        """Rush orders should be processed before normal orders."""
        # Two orders: one rush, one normal. Both need the first ingredient.
        order_rush = Order(order_id=1, recipe_slug="domeFigueMiel", is_rush=True,
                               created_at=0.0, timeout_at=80.0, done=False)
        order_normal = Order(order_id=2, recipe_slug="velvetTiramisu", is_rush=False,
                                 created_at=1.0, timeout_at=80.0, done=False)
        state = self._make_state(
            orders=(order_normal, order_rush, None, None),
            mixing_bowl=MixingBowlState(),
        )
        action = self.strategy.decide(state)
        self.assertIsInstance(action, MoveToMixingBowlAction)
        # Rush order (domeFigueMiel) has ingredient "flour"
        self.assertEqual(action.ingredient, "flour")


if __name__ == "__main__":
    unittest.main()
