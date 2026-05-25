"""
GameDataReward 测试

验证基于 reward.csv 的精确分数计算。
"""

import pytest

from hawarma.core.reward import RecipeRewardLookup
from playground.env.reward import GameDataReward, SparseReward
from hawarma.core.state import UnifiedState
from hawarma.core.models import AssemblyState, Order
from playground.env_simulator_types import Event, EventType


class TestRecipeRewardLookup:
    """测试 RecipeRewardLookup"""

    def test_loads_csv(self):
        lookup = RecipeRewardLookup()
        assert "gildedShoreRisotto" in lookup
        assert "nonexistent_recipe" not in lookup

    def test_get_score_with_condiments(self):
        lookup = RecipeRewardLookup()
        score = lookup.get_score("gildedShoreRisotto", has_condiments=True, is_rush=False)
        # base 106 + visibility 32 = 138
        assert score == 138.0

    def test_get_score_without_condiments(self):
        lookup = RecipeRewardLookup()
        score = lookup.get_score("gildedShoreRisotto", has_condiments=False, is_rush=False)
        # base 74 + visibility 16 = 90
        assert score == 90.0

    def test_get_score_rush(self):
        lookup = RecipeRewardLookup()
        score = lookup.get_score("gildedShoreRisotto", has_condiments=True, is_rush=True)
        # (106 + 32) * 1.6 = 220.8
        assert score == 220.8

    def test_get_score_unknown_recipe(self):
        lookup = RecipeRewardLookup()
        score = lookup.get_score("Unknown Recipe", has_condiments=True, is_rush=False)
        assert score == 0.0

    def test_get_score_with_visibility_tiers(self):
        """测试不同 total_visibility 区间的得分加成"""
        lookup = RecipeRewardLookup()
        # gildedShoreRisotto with cond: base 106 + visibility 32 = 138
        # tier 0 [0, 40):  normal 1.0x, rush 1.6x
        assert lookup.get_score("gildedShoreRisotto", True, False, 0) == 138.0
        assert lookup.get_score("gildedShoreRisotto", True, True, 0) == 220.8
        # tier 1 [40, 80):  normal 1.1x, rush 2.0x
        assert lookup.get_score("gildedShoreRisotto", True, False, 40) == 151.8
        assert lookup.get_score("gildedShoreRisotto", True, True, 40) == 276.0
        # tier 2 [80, 160): normal 1.2x, rush 2.5x
        assert lookup.get_score("gildedShoreRisotto", True, False, 80) == 165.6
        assert lookup.get_score("gildedShoreRisotto", True, True, 80) == 345.0
        # tier 3 [160, 240): normal 1.3x, rush 3.0x
        assert lookup.get_score("gildedShoreRisotto", True, False, 160) == 179.4
        assert lookup.get_score("gildedShoreRisotto", True, True, 160) == 414.0
        # tier 4 [240, 360): normal 1.4x, rush 3.5x
        assert lookup.get_score("gildedShoreRisotto", True, False, 240) == 193.2
        assert lookup.get_score("gildedShoreRisotto", True, True, 240) == 483.0
        # tier 5 [360, ∞):  normal 1.5x, rush 4.0x
        assert lookup.get_score("gildedShoreRisotto", True, False, 360) == 207.0
        assert lookup.get_score("gildedShoreRisotto", True, True, 360) == 552.0

    def test_get_visibility(self):
        lookup = RecipeRewardLookup()
        assert lookup.get_visibility("gildedShoreRisotto", True) == 32
        assert lookup.get_visibility("gildedShoreRisotto", False) == 16
        assert lookup.get_visibility("Unknown Recipe", True) == 0

    def test_all_recipes_in_lookup(self):
        """验证 recipes.json 中的所有菜品都在 reward.csv 中"""
        import json
        lookup = RecipeRewardLookup()

        with open("data/recipes.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        recipes = data if isinstance(data, list) else data.get("recipes", [])

        missing = []
        for recipe in recipes:
            slug = recipe["slug"]
            if slug not in lookup:
                missing.append(slug)

        assert not missing, f"Missing recipes in reward.csv: {missing}"


class TestGameDataReward:
    """测试 GameDataReward"""

    @pytest.fixture
    def reward_fn(self):
        return GameDataReward()

    def test_no_events_zero_reward(self, reward_fn):
        state = UnifiedState(
            time=0.0, orders=(), cookers={}, assembly=AssemblyState(),
            stockpile={}, recipes={}, game_duration=90.0, is_in_animation_window=False,
        )
        reward = reward_fn.compute(state, None, state, [])
        assert reward == 0.0

    def test_serve_with_condiments(self, reward_fn):
        prev_state = UnifiedState(
            time=10.0,
            orders=(
                Order(order_id=1, recipe_slug="gildedShoreRisotto", is_rush=False,
                         created_at=0.0, timeout_at=60.0),
            ),
            cookers={},
            assembly=AssemblyState(condiments={"salt": 1}),
            stockpile={},
            recipes={},
            game_duration=90.0,
            is_in_animation_window=False,
        )
        events = [
            Event(
                timestamp=10.0,
                event_type=EventType.ORDER_SERVED,
                details={"order_id": 1, "recipe": "gildedShoreRisotto"},
            )
        ]
        reward = reward_fn.compute(prev_state, None, prev_state, events)
        # base 106 + visibility 32 = 138
        assert reward == 138.0

    def test_serve_without_condiments(self, reward_fn):
        prev_state = UnifiedState(
            time=10.0,
            orders=(
                Order(order_id=1, recipe_slug="gildedShoreRisotto", is_rush=False,
                         created_at=0.0, timeout_at=60.0),
            ),
            cookers={},
            assembly=AssemblyState(),  # 无调料
            stockpile={},
            recipes={},
            game_duration=90.0,
            is_in_animation_window=False,
        )
        events = [
            Event(
                timestamp=10.0,
                event_type=EventType.ORDER_SERVED,
                details={"order_id": 1, "recipe": "gildedShoreRisotto"},
            )
        ]
        reward = reward_fn.compute(prev_state, None, prev_state, events)
        # base 74 + visibility 16 = 90
        assert reward == 90.0

    def test_serve_rush_order(self, reward_fn):
        prev_state = UnifiedState(
            time=10.0,
            orders=(
                Order(order_id=1, recipe_slug="gildedShoreRisotto", is_rush=True,
                         created_at=0.0, timeout_at=60.0),
            ),
            cookers={},
            assembly=AssemblyState(condiments={"salt": 1}),
            stockpile={},
            recipes={},
            game_duration=90.0,
            is_in_animation_window=False,
        )
        events = [
            Event(
                timestamp=10.0,
                event_type=EventType.ORDER_SERVED,
                details={"order_id": 1, "recipe": "gildedShoreRisotto"},
            )
        ]
        reward = reward_fn.compute(prev_state, None, prev_state, events)
        # (106 + 32) * 1.6 = 220.8
        assert reward == 220.8

    def test_serve_with_high_visibility(self, reward_fn):
        """测试 spawned_at_visibility 锁定得分加成"""
        prev_state = UnifiedState(
            time=10.0,
            orders=(
                Order(order_id=1, recipe_slug="gildedShoreRisotto", is_rush=False,
                         created_at=0.0, timeout_at=60.0),
            ),
            cookers={},
            assembly=AssemblyState(condiments={"salt": 1}),
            stockpile={},
            recipes={},
            game_duration=90.0,
            is_in_animation_window=False,
        )
        events = [
            Event(
                timestamp=10.0,
                event_type=EventType.ORDER_SERVED,
                details={
                    "order_id": 1,
                    "recipe": "gildedShoreRisotto",
                    "spawned_at_visibility": 240.0,  # tier 4: normal +40%
                },
            )
        ]
        reward = reward_fn.compute(prev_state, None, prev_state, events)
        # (106 + 32) * 1.4 = 193.2
        assert reward == 193.2

    def test_multiple_serves(self, reward_fn):
        prev_state = UnifiedState(
            time=10.0,
            orders=(
                Order(order_id=1, recipe_slug="a", is_rush=False, created_at=0.0, timeout_at=60.0),
                Order(order_id=2, recipe_slug="b", is_rush=False, created_at=0.0, timeout_at=60.0),
            ),
            cookers={},
            assembly=AssemblyState(condiments={"salt": 1}),
            stockpile={},
            recipes={},
            game_duration=90.0,
            is_in_animation_window=False,
        )
        events = [
            Event(
                timestamp=10.0,
                event_type=EventType.ORDER_SERVED,
                details={"order_id": 1, "recipe": "gildedShoreRisotto"},
            ),
            Event(
                timestamp=10.0,
                event_type=EventType.ORDER_SERVED,
                details={"order_id": 2, "recipe": "newYearJiaozi"},
            ),
        ]
        reward = reward_fn.compute(prev_state, None, prev_state, events)
        # gildedShoreRisotto with cond = 138
        # newYearJiaozi with cond = 106 + 32 = 138
        assert reward == 138.0 + 138.0


class TestSparseRewardFallback:
    """验证 SparseReward 仍然可用"""

    def test_reads_event_score(self):
        reward_fn = SparseReward()
        state = UnifiedState(
            time=0.0, orders=(), cookers={}, assembly=AssemblyState(),
            stockpile={}, recipes={}, game_duration=90.0, is_in_animation_window=False,
        )
        events = [
            Event(
                timestamp=10.0,
                event_type=EventType.ORDER_SERVED,
                details={"score": 150},
            )
        ]
        reward = reward_fn.compute(state, None, state, events)
        assert reward == 150.0
