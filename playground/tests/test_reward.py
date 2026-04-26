"""
GameDataReward 测试

验证基于 reward.csv 的精确分数计算。
"""

import pytest

from hawarma.rewards import RecipeRewardLookup
from playground.env.rewards import GameDataReward, SparseReward
from playground.env.unified_state import UnifiedState
from hawarma.bridge.base_environment import AssemblyState, OrderInfo
from hawarma.env_simulator_types import Event, EventType


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
                OrderInfo(order_id=1, recipe_slug="gildedShoreRisotto", is_rush=False,
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
                OrderInfo(order_id=1, recipe_slug="gildedShoreRisotto", is_rush=False,
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
                OrderInfo(order_id=1, recipe_slug="gildedShoreRisotto", is_rush=True,
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

    def test_multiple_serves(self, reward_fn):
        prev_state = UnifiedState(
            time=10.0,
            orders=(
                OrderInfo(order_id=1, recipe_slug="a", is_rush=False, created_at=0.0, timeout_at=60.0),
                OrderInfo(order_id=2, recipe_slug="b", is_rush=False, created_at=0.0, timeout_at=60.0),
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
