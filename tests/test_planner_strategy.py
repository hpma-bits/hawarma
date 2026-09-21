"""Issue #21：PlannerStrategy（deadline 感知滚动时域调度）单元测试.

覆盖验收标准 2 的六类断言：
- 灶台绑定（cook 只发 ingredient→绑定 cooker 的 CookAction）
- 动画窗口内不发 ServeOrderAction
- 过期食材优先清理
- deadline 感知（低分临期单 vs 高分余量大单；gastronome 因不看 deadline 选后者）
- decide() 单次耗时 < 100ms（4 订单满负荷）
- decide() 不修改 state（含 #16 深快照下 env 侧状态不变）
- 注册表注册为 "planner"

状态构造参考 tests/test_gastronome_golden.py 的形态（data/recipes.json 真实数据）.
"""

from __future__ import annotations

import dataclasses
import time
import unittest

from hawarma.agent.registry import get_strategy, list_strategies
from hawarma.agent.strategies.gastronome import GastronomeStrategy
from hawarma.agent.strategies.planner import PlannerStrategy
from hawarma.core.actions import (
    ClearCookerAction,
    CookAction,
    ServeOrderAction,
)
from hawarma.core.models import AssemblyState, CookerState, Order, StockpileSlot
from hawarma.core.state import UnifiedState
from hawarma.paths import data_path
from hawarma.services.recipe_manager import RecipeManager


def _load_recipes(slugs: list[str]) -> dict:
    manager = RecipeManager(data_path("recipes.json"))
    manager.load_recipes()
    return {slug: manager.get_recipe_by_slug(slug) for slug in slugs}


# 配方数据（data/recipes.json 真实数据；时长/绑定由数据决定）：
#   paleleafMeatRoll : succulent_cut/grill/2.0 + blanquette_fig/skillet/3.0（unit 118）
#   midsummerLambRoast: tender_lamb/oven/4.0 单食材（unit 120）
#   newYearJiaozi    : dough_wrappers/pot/3.0 + tender_lamb/grill/4.0
#   braisedNewYearFish: clearwater_fish/skillet/4.0 单食材
#   gildedShoreRisotto: clearwater_fish/oven/3.0 + creamfield_rice/pot/2.0
#   deepwaterInkPasta : deepwater_tentacle/oven/5.0 + pliant_pasta/pot/3.0
SLUGS_PERF = [
    "newYearJiaozi",
    "gildedShoreRisotto",
    "deepwaterInkPasta",
    "braisedNewYearFish",
]
RECIPES_DEADLINE = _load_recipes(["paleleafMeatRoll", "midsummerLambRoast"])
RECIPES_BINDING = _load_recipes(["newYearJiaozi", "braisedNewYearFish"])
RECIPES_SINGLE = _load_recipes(["braisedNewYearFish"])
RECIPES_PERF = _load_recipes(SLUGS_PERF)


def _cooker(cooker_type: str, busy: bool = False, item: str | None = None,
            started_at: float | None = None, done_at: float | None = None,
            expired_at: float | None = None) -> CookerState:
    return CookerState(busy=busy, item_name=item, cooker_type=cooker_type,
                       started_at=started_at, done_at=done_at, expired_at=expired_at)


def _free_cookers() -> dict[str, CookerState]:
    return {
        "skillet": _cooker("skillet"),
        "oven": _cooker("oven"),
        "pot": _cooker("pot"),
        "grill": _cooker("grill"),
    }


def _order(order_id: int, slug: str, rush: bool = False,
           created_at: float = 10.0, timeout_at: float = 80.0,
           spawned_vis: float = 0.0) -> Order:
    return Order(order_id=order_id, recipe_slug=slug, is_rush=rush,
                 created_at=created_at, timeout_at=timeout_at,
                 spawned_at_visibility=spawned_vis)


def _state(orders, cookers, assembly=None, stockpile=None,
           time: float = 10.0, recipes=None,
           is_in_animation_window: bool = False,
           total_visibility: float = 0.0) -> UnifiedState:
    return UnifiedState(
        time=time,
        orders=tuple(orders),
        cookers=cookers,
        assembly=assembly or AssemblyState(),
        stockpile=stockpile or {f"slot{i}": StockpileSlot() for i in range(3)},
        recipes=recipes if recipes is not None else RECIPES_SINGLE,
        game_duration=90.0,
        is_in_animation_window=is_in_animation_window,
        total_visibility=total_visibility,
    )


def _snapshot(state: UnifiedState) -> UnifiedState:
    """字段级深快照（等价比较用；UnifiedState 为 frozen dataclass）"""
    return UnifiedState(
        time=state.time,
        orders=tuple(o.snapshot() if o else None for o in state.orders),
        cookers={k: v.snapshot() for k, v in state.cookers.items()},
        assembly=state.assembly.snapshot(),
        stockpile={k: v.snapshot() for k, v in state.stockpile.items()},
        recipes=dict(state.recipes),
        game_duration=state.game_duration,
        is_in_animation_window=state.is_in_animation_window,
        total_visibility=state.total_visibility,
        mixing_bowl=state.mixing_bowl.snapshot(),
    )


class TestPlannerRegistry(unittest.TestCase):
    """验收 1：注册为 planner，可经 registry 加载"""

    def test_registered_and_loadable(self):
        self.assertIn("planner", list_strategies())
        strategy = get_strategy("planner")
        self.assertIsInstance(strategy, PlannerStrategy)


class TestPlannerReactiveLayer(unittest.TestCase):
    """反应式安全层：清过期、动画窗口禁 serve"""

    def setUp(self):
        self.strategy = PlannerStrategy()
        self.strategy.on_game_start(RECIPES_SINGLE)

    def test_expired_cooker_cleared_first(self):
        """过期食材优先清理（即使有订单可烹饪）"""
        state = _state(
            orders=[_order(1, "braisedNewYearFish"), None, None, None],
            cookers={
                "skillet": _cooker("skillet", True, "clearwater_fish",
                                   started_at=6.0, done_at=6.0, expired_at=10.5),
                "oven": _cooker("oven"),
                "pot": _cooker("pot"),
                "grill": _cooker("grill"),
            },
            time=11.0,
        )
        action = self.strategy.decide(state)
        self.assertIsInstance(action, ClearCookerAction)
        self.assertEqual(action.cooker, "skillet")

    def test_no_serve_in_animation_window(self):
        """动画窗口内组装站齐料齐调料也不发 ServeOrderAction"""
        state = _state(
            orders=[_order(1, "braisedNewYearFish"), None, None, None],
            cookers=_free_cookers(),
            assembly=AssemblyState(
                ingredients=[("clearwater_fish", "skillet", 9.0)],
                target_recipe_slug="braisedNewYearFish",
                condiments={"hearthspice": 1, "acacia_honey": 1},
            ),
            is_in_animation_window=True,
        )
        action = self.strategy.decide(state)
        self.assertNotIsInstance(action, ServeOrderAction)

    def test_serve_when_ready_outside_window(self):
        """窗口外齐料齐调料立即送餐"""
        state = _state(
            orders=[_order(1, "braisedNewYearFish"), None, None, None],
            cookers=_free_cookers(),
            assembly=AssemblyState(
                ingredients=[("clearwater_fish", "skillet", 9.0)],
                target_recipe_slug="braisedNewYearFish",
                condiments={"hearthspice": 1, "acacia_honey": 1},
            ),
        )
        action = self.strategy.decide(state)
        self.assertIsInstance(action, ServeOrderAction)
        self.assertEqual(action.slot_idx, 0)


class TestPlannerCookerBinding(unittest.TestCase):
    """验收 2a：cook 只发 ingredient→绑定 cooker 的 CookAction"""

    def test_cook_respects_ingredient_cooker_binding(self):
        """newYearJiaozi 的 tender_lamb 绑定 grill（duration 4.0 最长优先）"""
        strategy = PlannerStrategy()
        strategy.on_game_start(RECIPES_BINDING)
        state = _state(
            orders=[_order(1, "newYearJiaozi"), None, None, None],
            cookers=_free_cookers(),
            recipes=RECIPES_BINDING,
        )
        action = strategy.decide(state)
        self.assertIsInstance(action, CookAction)
        # 从配方数据断言绑定关系，而非硬编码
        recipe = RECIPES_BINDING["newYearJiaozi"]
        bound = {ing.name: ing.cooker_type for ing in recipe.ingredients}
        self.assertEqual(action.cooker, bound[action.ingredient])
        durations = {ing.name: ing.duration for ing in recipe.ingredients}
        self.assertEqual(action.duration, durations[action.ingredient])
        self.assertEqual(action.order_id, 1)

    def test_full_episode_never_violates_binding(self):
        """整局仿真中所有 CookAction 的 (ingredient, cooker) 均为配方绑定对"""
        from playground.agents.base import Agent
        from playground.core.episode import run_episode
        from playground.env.sim import SimEnv

        bound_pairs: set[tuple[str, str]] = set()
        for recipe in RECIPES_PERF.values():
            bound_pairs |= {(ing.name, ing.cooker_type) for ing in recipe.ingredients}

        violations: list[CookAction] = []
        original = PlannerStrategy.decide

        def spying_decide(self, state):
            action = original(self, state)
            if isinstance(action, CookAction):
                if (action.ingredient, action.cooker) not in bound_pairs:
                    violations.append(action)
            return action

        PlannerStrategy.decide = spying_decide  # type: ignore[method-assign]
        try:
            result = run_episode(SimEnv(), Agent(PlannerStrategy()), seed=7,
                                 recipe_slugs=SLUGS_PERF)
        finally:
            PlannerStrategy.decide = original  # type: ignore[method-assign]
        self.assertEqual(violations, [])
        self.assertGreater(result.orders_served, 0)


class TestPlannerDeadlineAwareness(unittest.TestCase):
    """验收 2d：deadline 感知（与 gastronome 的差异点）

    构造：A = paleleafMeatRoll（unit 118，双食材，截止 19.0 仅剩 9s，紧但可行）
          B = midsummerLambRoast（unit 120，单食材，截止 70.0 余量大）
    gastronome 的 CPM 评分（-cp + duration）偏向单食材短 CP 的 B；planner 读
    deadline：排列 [B, A] 中 A 的最早完成下界（~21.0）超过其截止 → 违约损失，
    只有 [A, B] 两单全保 → 首个动作是 A 的关键动作（最长食材 blanquette_fig）。
    """

    def test_planner_prioritizes_deadline_critical_order(self):
        strategy = PlannerStrategy()
        strategy.on_game_start(RECIPES_DEADLINE)
        state = _state(
            orders=[
                _order(1, "paleleafMeatRoll", created_at=10.0, timeout_at=19.0),
                _order(2, "midsummerLambRoast", created_at=10.0, timeout_at=70.0),
                None, None,
            ],
            cookers=_free_cookers(),
            recipes=RECIPES_DEADLINE,
            time=10.0,
        )
        action = strategy.decide(state)
        self.assertIsInstance(action, CookAction)
        # 必须是 A（order 1）的关键动作，而不是高分余量大的 B
        self.assertEqual(action.order_id, 1)
        self.assertEqual(action.ingredient, "blanquette_fig")  # A 的最长食材
        self.assertEqual(action.cooker, "skillet")

    def test_gastronome_picks_slack_order_here(self):
        """同状态下 gastronome 因不看 deadline 选 B（差异点证据）"""
        strategy = GastronomeStrategy()
        strategy.on_game_start(RECIPES_DEADLINE)
        state = _state(
            orders=[
                _order(1, "paleleafMeatRoll", created_at=10.0, timeout_at=19.0),
                _order(2, "midsummerLambRoast", created_at=10.0, timeout_at=70.0),
                None, None,
            ],
            cookers=_free_cookers(),
            recipes=RECIPES_DEADLINE,
            time=10.0,
        )
        action = strategy.decide(state)
        self.assertIsInstance(action, CookAction)
        self.assertEqual(action.order_id, 2)  # B（高分的单食材单）
        self.assertEqual(action.ingredient, "tender_lamb")

    def test_planner_serves_both_orders_in_episode(self):
        """紧截止场景下整局仿真两单都被服务（deadline 规划真正落地）"""
        from playground.agents.base import Agent
        from playground.core.episode import run_episode
        from playground.env.sim import SimEnv

        result = run_episode(
            SimEnv(), Agent(PlannerStrategy()), seed=3,
            recipe_slugs=["paleleafMeatRoll", "midsummerLambRoast",
                          "heartyCustardPie", "saltbakedShrimp"],
        )
        self.assertGreaterEqual(result.orders_served, 2)
        self.assertEqual(result.orders_timeout, 0)


class TestPlannerPerformanceAndPurity(unittest.TestCase):
    """验收 2e/2f：decide() 耗时与状态纯净性"""

    @classmethod
    def setUpClass(cls):
        cls.strategy = PlannerStrategy()
        cls.strategy.on_game_start(RECIPES_PERF)
        # 4 订单满负荷：全部灶台烹饪中、库存占用、组装站半载
        cls.state = UnifiedState(
            time=30.0,
            orders=(
                _order(1, "newYearJiaozi", created_at=26.0, timeout_at=98.0),
                _order(2, "gildedShoreRisotto", created_at=27.0, timeout_at=99.0),
                _order(3, "deepwaterInkPasta", created_at=28.0, timeout_at=105.0),
                _order(4, "braisedNewYearFish", rush=True, created_at=29.0,
                       timeout_at=66.0),
            ),
            cookers={
                "skillet": _cooker("skillet", True, "clearwater_fish",
                                   started_at=29.0, done_at=33.0, expired_at=38.0),
                "oven": _cooker("oven", True, "deepwater_tentacle",
                                started_at=29.5, done_at=34.5, expired_at=39.5),
                "pot": _cooker("pot", True, "dough_wrappers",
                               started_at=29.2, done_at=32.2, expired_at=37.2),
                "grill": _cooker("grill", True, "tender_lamb",
                                 started_at=29.1, done_at=33.1, expired_at=38.1),
            },
            assembly=AssemblyState(
                ingredients=[("clearwater_fish", "oven", 30.0)],
                target_recipe_slug="gildedShoreRisotto",
            ),
            stockpile={
                "slot0": StockpileSlot(item_name="creamfield_rice",
                                       cooker_type="pot", count=1),
                "slot1": StockpileSlot(item_name="pliant_pasta",
                                       cooker_type="pot", count=1),
                "slot2": StockpileSlot(),
            },
            recipes=RECIPES_PERF,
            game_duration=90.0,
            is_in_animation_window=False,
            total_visibility=200.0,
        )

    def test_decide_under_100ms_full_load(self):
        """4 订单满负荷下单次 decide() < 100ms（连续 10 次，任一次都不超）"""
        for _ in range(10):
            start = time.perf_counter()
            self.strategy.decide(self.state)
            elapsed = time.perf_counter() - start
            self.assertLess(
                elapsed, 0.100,
                msg=f"decide() took {elapsed * 1000:.1f}ms (budget 100ms)",
            )

    def test_decide_does_not_mutate_state(self):
        """decide() 前后 UnifiedState 字段级深快照完全一致"""
        before = _snapshot(self.state)
        self.strategy.decide(self.state)
        self.assertEqual(_snapshot(self.state), before)

    def test_decide_does_not_mutate_env_side_state(self):
        """#16 深快照下 env 侧状态不被 decide() 污染"""
        from playground.agents.base import Agent
        from playground.env.sim import SimEnv

        env = SimEnv()
        agent = Agent(PlannerStrategy())
        obs, info = env.reset(seed=11, recipe_slugs=SLUGS_PERF)
        agent.strategy.on_game_start(info["recipes"])
        for _ in range(60):  # 推进到中局满负荷
            result = env.step(agent.act(obs))
            obs = result.observation
            if result.terminated:
                break
        before = env.get_unified_state()
        agent.strategy.decide(obs)
        self.assertEqual(env.get_unified_state(), before)

    def test_decide_is_deterministic(self):
        """同一状态重复 decide() 产出一致（滚动重规划的确定性前提）"""
        first = self.strategy.decide(self.state)
        for _ in range(3):
            self.assertEqual(
                dataclasses.asdict(first) if first else None,
                dataclasses.asdict(self.strategy.decide(self.state)) if first else None,
            )


class TestPlannerDecideGuard(unittest.TestCase):
    """decide() 早于 on_game_start 调用时显式报错（同 gastronome #22 语义）"""

    def test_raises_without_on_game_start(self):
        strategy = PlannerStrategy()
        state = _state(
            orders=[_order(1, "braisedNewYearFish"), None, None, None],
            cookers=_free_cookers(),
        )
        with self.assertRaises(RuntimeError):
            strategy.decide(state)


if __name__ == "__main__":
    unittest.main()
