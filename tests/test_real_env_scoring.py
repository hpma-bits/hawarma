"""
真实环境得分系统单元测试

回归目标：
    GameEnv.on_order_served 历史上是 stub（score=1 per order），
    导致真实环境日志里的 "score" 实际是提交份数而非游戏得分。

本次修复：
    - on_order_served(order, has_condiments) 复用 RecipeRewardLookup，
      按订单生成时锁定的 spawned_at_visibility 计算精确得分
    - Order.spawned_at_visibility 设为不可变字段（immutable since creation）

参考：
    - env_simulator.py:1170-1206 (sim 的得分累加逻辑)
    - core/reward.py:60-92 (RecipeRewardLookup.get_score)
"""

import pytest

from hawarma.core.models import Order
from hawarma.core.reward import RecipeRewardLookup
from hawarma.game.game_env import GameEnv


# 测试用 recipe：braisedNewYearFish（数据稳定，1-食材 6s）
# base 92/64, visibility 28/14 (with/without condiments)
RECIPE = "braisedNewYearFish"
BASE_WITH = 92
BASE_WITHOUT = 64
VIS_WITH = 28
VIS_WITHOUT = 14


@pytest.fixture
def lookup() -> RecipeRewardLookup:
    return RecipeRewardLookup()


@pytest.fixture
def env() -> GameEnv:
    return GameEnv(cooker_names=["fryer", "pot"], stockpile_slots=3, game_duration=90.0)


# ============================================================================
# Order.spawned_at_visibility 不可变性
# ============================================================================


class TestOrderSpawnedAtVisibilityImmutability:
    def test_set_once_then_blocked(self):
        """设置一次后再赋值应抛 AttributeError"""
        order = Order(
            order_id=1,
            recipe_slug=RECIPE,
            is_rush=False,
            created_at=0.0,
            timeout_at=70.0,
            spawned_at_visibility=10.0,
        )
        assert order.spawned_at_visibility == 10.0
        with pytest.raises(AttributeError, match="immutable since creation"):
            order.spawned_at_visibility = 20.0  # type: ignore[misc]

    def test_kwarg_set_is_the_immutable_set(self):
        """通过 kwarg 第一次设置即为不可变起点"""
        order = Order(
            order_id=2,
            recipe_slug=RECIPE,
            is_rush=True,
            created_at=0.0,
            timeout_at=40.0,
            spawned_at_visibility=0.0,
        )
        with pytest.raises(AttributeError):
            order.spawned_at_visibility = 5.0  # type: ignore[misc]

    def test_other_fields_remain_mutable(self):
        """done / served_at 仍可修改（不受 immutability 限制）"""
        order = Order(
            order_id=3,
            recipe_slug=RECIPE,
            is_rush=False,
            created_at=0.0,
            timeout_at=70.0,
        )
        order.done = True
        order.served_at = 12.5
        assert order.done is True
        assert order.served_at == 12.5


# ============================================================================
# GameEnv.add_order 锁定 spawned_at_visibility
# ============================================================================


class TestAddOrderLocksSpawnedAtVisibility:
    def test_initial_order_locks_zero(self, env: GameEnv):
        """第一个订单生成时 total_visibility=0，锁定 0"""
        order_id = env.add_order(RECIPE, is_rush=False)
        assert order_id is not None
        order = env.orders[0]
        assert order is not None
        assert order.spawned_at_visibility == 0.0

    def test_subsequent_orders_lock_current_total(self, env: GameEnv):
        """后续订单锁定当前 total_visibility"""
        env._total_visibility = 100.0
        env.add_order(RECIPE, is_rush=False)
        order = env.orders[0]
        assert order is not None
        assert order.spawned_at_visibility == 100.0


# ============================================================================
# GameEnv.on_order_served 精确得分
# ============================================================================


class TestOnOrderServedScoring:
    def test_no_condiments_no_rush_base_multiplier(
        self, env: GameEnv, lookup: RecipeRewardLookup
    ):
        """无调料 + 非 rush + spawned_at_vis=0 → 1.0× 倍率"""
        order_id = env.add_order(RECIPE, is_rush=False)
        assert order_id is not None
        order = env.orders[0]
        assert order is not None

        env.on_order_served(order, has_condiments=False)

        expected = float((BASE_WITHOUT + VIS_WITHOUT) * 1.0)
        assert env.get_stats()["total_score"] == expected
        assert env.get_stats()["orders_served"] == 1
        assert env._total_visibility == VIS_WITHOUT

    def test_with_condiments_no_rush_base_multiplier(
        self, env: GameEnv, lookup: RecipeRewardLookup
    ):
        """有调料 + 非 rush + spawned_at_vis=0 → 1.0× 倍率"""
        order_id = env.add_order(RECIPE, is_rush=False)
        assert order_id is not None
        order = env.orders[0]
        assert order is not None

        env.on_order_served(order, has_condiments=True)

        expected = float((BASE_WITH + VIS_WITH) * 1.0)
        assert env.get_stats()["total_score"] == expected
        assert env._total_visibility == VIS_WITH

    def test_rush_applies_rush_multiplier(self, env: GameEnv):
        """rush 订单在 spawned_at_vis=0 时使用 1.6× 倍率"""
        env.add_order(RECIPE, is_rush=True)
        order = env.orders[0]
        assert order is not None

        env.on_order_served(order, has_condiments=False)

        # (64 + 14) * 1.6 = 124.8
        expected = (BASE_WITHOUT + VIS_WITHOUT) * 1.6
        assert env.get_stats()["total_score"] == expected

    def test_high_visibility_via_manual_order(self, env: GameEnv):
        """手动构造一个 spawned_at_vis=200 的订单，验证 1.3× 倍率"""
        from hawarma.core.models import Order as OrderModel

        order = OrderModel(
            order_id=999,
            recipe_slug=RECIPE,
            is_rush=False,
            created_at=0.0,
            timeout_at=70.0,
            spawned_at_visibility=200.0,
        )
        env._orders[0] = order
        env._total_visibility = 200.0

        env.on_order_served(order, has_condiments=True)

        # 200 在 [160, 240) 区间 → 非 rush 倍率 1.3
        expected = (BASE_WITH + VIS_WITH) * 1.3
        assert env.get_stats()["total_score"] == expected

    def test_visibility_accumulates_across_orders(self, env: GameEnv):
        """连续 serve 多个订单，total_visibility 单调累加"""
        env.add_order(RECIPE, is_rush=False)
        env.add_order(RECIPE, is_rush=False)
        env.add_order(RECIPE, is_rush=False)

        for slot in range(3):
            order = env.orders[slot]
            assert order is not None
            env.on_order_served(order, has_condiments=False)

        # 3 × 14 = 42
        assert env._total_visibility == 3 * VIS_WITHOUT
        assert env.get_stats()["orders_served"] == 3

    def test_subsequent_orders_see_accumulated_visibility(self, env: GameEnv):
        """第 2 个订单的 spawned_at_visibility 应是第 1 个 serve 后的累加值"""
        env.add_order(RECIPE, is_rush=False)
        order_1 = env.orders[0]
        assert order_1 is not None
        env.on_order_served(order_1, has_condiments=True)
        # 累加后 total_visibility = 28
        assert env._total_visibility == VIS_WITH

        env.add_order(RECIPE, is_rush=False)
        order_2 = env.orders[1]
        assert order_2 is not None
        assert order_2.spawned_at_visibility == float(VIS_WITH)

        env.on_order_served(order_2, has_condiments=True)
        # 两个订单 spawned_at_vis 都在 [0, 40) → 1.0×；总得分 = 120 × 2
        expected = float(BASE_WITH + VIS_WITH) * 2
        assert env.get_stats()["total_score"] == expected
