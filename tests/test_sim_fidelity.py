"""
模拟器保真度测试（Issue #14）

验证 GameSimulator / SimEnv 与 docs/game_rules.md 第 3/4/9 节的 4 项对齐：
1. serve_order 校验组装站食材 (name, cooker_type) 集合与 recipe 完全一致（规则 3.5）
2. 过期食材留在灶台直到显式 ClearCookerAction（规则 4.2/9.1）
3. SimEnv 观测路径统一走 1s 新单隐藏（规则 3.4.2，消除 get_order 双口径）
4. serve 禁令窗口（1.5s）与新单可见性窗口（1s）独立；
   提交后场上无单立即刷新，不被 serve 禁令窗口推迟（规则 3.4.1）

采用 unittest 风格（python -m unittest discover tests 可收集）。

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

import unittest
from pathlib import Path

from hawarma.recipe import Recipe
from playground.env_simulator import GameSimulator
from playground.env.sim import SimEnv
from playground.env_simulator_types import EventType

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_recipe(
    slug: str,
    raw_ingredients: list[str],
    cookers: list[str],
    cook_durations: list[float],
    condiments: dict[str, int] | None = None,
) -> Recipe:
    """构造最小可用的 Pydantic Recipe"""
    return Recipe(
        slug=slug,
        name=slug,
        raw_ingredients=raw_ingredients,
        cookers=cookers,
        cookers_layout=list(cookers),
        cook_durations=cook_durations,
        condiments=condiments or {},
    )


def make_sim(*recipes: Recipe) -> GameSimulator:
    """构造已配置好的模拟器；禁用随机订单生成保证确定性"""
    sim = GameSimulator()
    for recipe in recipes:
        sim._recipes[recipe.slug] = recipe
    sim.setup_from_recipes([r.slug for r in recipes])
    sim._next_order_refresh_time = float("inf")
    return sim


R1 = dict(slug="r1", raw_ingredients=["fish", "rice"], cookers=["oven", "pot"], cook_durations=[2.0, 3.0])
R2 = dict(slug="r2", raw_ingredients=["rice", "meat"], cookers=["pot", "skillet"], cook_durations=[3.0, 4.0])


class TestServeValidatesIngredientSet(unittest.TestCase):
    """#14-1: serve 校验食材 (name, cooker_type) 集合与 recipe 完全一致"""

    def _assemble(self, sim: GameSimulator, ingredient: str, cooker: str) -> None:
        """烹饪一个食材并移到组装站（等待其完成）"""
        self.assertTrue(sim.start_cooking(ingredient, cooker).success)
        duration = next(
            ing.duration
            for r in sim._recipes.values()
            for ing in r.ingredients
            if ing.name == ingredient and ing.cooker_type == cooker
        )
        sim.tick(duration)
        self.assertTrue(sim.move_to_assembly(cooker).success)

    def test_serve_rejects_partial_and_cross_recipe_mix(self):
        sim = make_sim(make_recipe(**R1), make_recipe(**R2))
        recipe = sim._recipes["r1"]
        sim.inject_order(0, recipe)
        sim._next_order_refresh_time = float("inf")

        # 场景 A：recipe 需 2 种食材，只放了 1 种（is_complete 仍为 True）
        self._assemble(sim, "fish", "oven")
        self.assertTrue(sim._state.assembly.is_complete)  # 前置：旧口径下即可提交
        result = sim.serve_order(0)
        self.assertFalse(result.success, "partial ingredient set must be rejected")
        self.assertIn("do not match", result.error_message)
        # 菜品留在组装站，订单未完成（"被退回"语义）
        self.assertEqual(len(sim._state.assembly.ingredients), 1)
        self.assertFalse(sim._state.orders[0].is_completed)

        # 场景 B：跨 recipe 混放（fish/r1 + meat/r2，name 不重复故可放入）
        self._assemble(sim, "meat", "skillet")
        self.assertEqual(len(sim._state.assembly.ingredients), 2)
        result = sim.serve_order(0)
        self.assertFalse(result.success, "cross-recipe mix must be rejected")
        self.assertEqual(len(sim._state.assembly.ingredients), 2)

        # 场景 C：清空后放入与 recipe 完全一致的集合 → 提交成功
        self.assertTrue(sim.move_to_trash("assembly").success)
        self._assemble(sim, "fish", "oven")
        self._assemble(sim, "rice", "pot")
        result = sim.serve_order(0)
        self.assertTrue(result.success, result.error_message)
        self.assertTrue(sim._state.assembly.is_free)
        self.assertTrue(sim._state.orders[0] is None)


class TestExpiredIngredientStaysUntilCleared(unittest.TestCase):
    """#14-2: 过期食材留在灶台直到显式清理；过期事件按过期时刻只发一次"""

    def _count_events(self, sim: GameSimulator, event_type: EventType, cooker: str | None = None) -> int:
        return sum(
            1
            for e in sim._event_history
            if e.event_type == event_type
            and (cooker is None or e.details.get("cooker") == cooker)
        )

    def test_expired_ingredient_occupies_cooker_until_explicit_clear(self):
        sim = make_sim(make_recipe(**R1))
        self.assertTrue(sim.start_cooking("fish", "oven").success)  # done 2.0, expired 7.0
        sim.tick(7.5)

        # 过期事件在过期时刻之后的首个 tick 触发一次
        self.assertEqual(self._count_events(sim, EventType.INGREDIENT_EXPIRED, "oven"), 1)
        # 食材仍占用灶台（不自动释放）
        cooker = sim.get_cooker_state("oven")
        self.assertTrue(cooker.busy)
        self.assertEqual(cooker.item_name, "fish")

        # 过期后不能移到组装站/库存，必须清理
        self.assertFalse(sim.move_to_assembly("oven").success)
        self.assertFalse(sim.move_to_stockpile("oven", "slot0").success)

        # 继续推进不重复发过期事件
        sim.tick(0.5)
        self.assertEqual(self._count_events(sim, EventType.INGREDIENT_EXPIRED, "oven"), 1)

        # 显式 ClearCookerAction 语义（清理动作的 0.3s 等价耗时由 SimEnv action_delay 承担）
        result = sim.clear_cooker("oven")
        self.assertTrue(result.success, result.error_message)
        self.assertFalse(sim.get_cooker_state("oven").busy)

        # 未过期灶台不允许"清理"（清理仅针对已糊食材）
        sim.start_cooking("fish", "oven")
        self.assertFalse(sim.clear_cooker("oven").success)

    def test_completion_and_expiry_events_fire_once_per_session(self):
        sim = make_sim(make_recipe(**R1))
        sim.start_cooking("fish", "oven")  # session 1: done 2.0, expired 7.0
        sim.tick(9.0)
        self.assertEqual(self._count_events(sim, EventType.COOKING_COMPLETED, "oven"), 1)
        self.assertEqual(self._count_events(sim, EventType.INGREDIENT_EXPIRED, "oven"), 1)
        sim.tick(5.0)  # 长期占用不再刷事件
        self.assertEqual(self._count_events(sim, EventType.COOKING_COMPLETED, "oven"), 1)
        self.assertEqual(self._count_events(sim, EventType.INGREDIENT_EXPIRED, "oven"), 1)

        sim.clear_cooker("oven")
        sim.start_cooking("fish", "oven")  # session 2
        sim.tick(9.0)
        self.assertEqual(self._count_events(sim, EventType.COOKING_COMPLETED, "oven"), 2)
        self.assertEqual(self._count_events(sim, EventType.INGREDIENT_EXPIRED, "oven"), 2)


class TestUnifiedStateNewOrderVisibility(unittest.TestCase):
    """#14-3: SimEnv 观测路径统一走 1s 新单隐藏（与 get_order 同口径）"""

    RECIPES_FILE = str(_PROJECT_ROOT / "data" / "recipes.json")

    def _env_with_first_order(self, detection_delay: float) -> tuple[SimEnv, GameSimulator]:
        env = SimEnv(recipes_file=self.RECIPES_FILE, detection_delay=detection_delay)
        env.reset(seed=42)
        sim = env._sim
        sim._next_order_refresh_time = 2.0  # 确定性：t=2.0 生成首单
        sim.tick(2.0)
        assert sim._state.orders[0] is not None
        return env, sim

    def test_new_order_hidden_for_one_second(self):
        env, sim = self._env_with_first_order(detection_delay=0.4)
        # 默认 detection_delay=0.4 < 1.0 → 取 max，隐藏窗口为 1s
        self.assertIsNone(env.get_unified_state().orders[0], "hidden at created_at+0.0")
        self.assertIsNone(sim.get_order(0), "get_order 与 get_unified_state 同口径")
        sim.tick(0.9)  # t=2.9 < 3.0
        self.assertIsNone(env.get_unified_state().orders[0])
        sim.tick(0.1)  # t=3.0 恰好可见
        self.assertIsNotNone(env.get_unified_state().orders[0])
        self.assertIsNotNone(sim.get_order(0))

    def test_detection_delay_and_animation_combine_via_max(self):
        # detection_delay=2.0 > 1.0 → 隐藏窗口取 2s（叠加语义，不是替换）
        env, sim = self._env_with_first_order(detection_delay=2.0)
        sim.tick(1.4)  # t=3.4：超过 1s 动画窗口但仍隐藏
        self.assertIsNone(env.get_unified_state().orders[0])
        sim.tick(0.5)  # t=3.9 < 4.0
        self.assertIsNone(env.get_unified_state().orders[0])
        sim.tick(0.1)  # t=4.0 可见
        self.assertIsNotNone(env.get_unified_state().orders[0])


class TestServeBanAndImmediateRefresh(unittest.TestCase):
    """#14-4: serve 禁令窗口与新单可见性窗口独立；无单时立即刷新"""

    def _serve_only_order(self, sim: GameSimulator) -> float:
        """组装 r1 全套食材并提交唯一订单，返回提交时刻"""
        recipe = sim._recipes["r1"]
        sim.inject_order(0, recipe)
        for ingredient, cooker, duration in (("fish", "oven", 2.0), ("rice", "pot", 3.0)):
            self.assertTrue(sim.start_cooking(ingredient, cooker).success)
            sim.tick(duration)
            self.assertTrue(sim.move_to_assembly(cooker).success)
        serve_time = sim.time
        result = sim.serve_order(0)
        self.assertTrue(result.success, result.error_message)
        return serve_time

    def test_immediate_refresh_not_delayed_by_serve_ban_window(self):
        sim = make_sim(make_recipe(**R1))
        serve_time = self._serve_only_order(sim)  # t=5.0

        # serve 禁令窗口（slot 位移 1.5s）激活
        self.assertTrue(sim.is_in_animation_window())
        self.assertAlmostEqual(sim._serve_ban_until, serve_time + GameSimulator.ANIMATION_DURATION)

        # 提交后场上无单：下一个 tick 立即刷新（不再等 1.5s 禁令窗口结束）
        sim.tick(0.1)
        new_order = sim._state.orders[0]
        self.assertIsNotNone(new_order, "immediate refresh should create new order")
        self.assertLessEqual(new_order.created_at, serve_time + 0.1 + 1e-9)
        self.assertFalse(sim._needs_immediate_refresh)

        # 新单创建不得缩短 serve 禁令窗口（旧 bug：_animation_until 被覆盖为 +1.0）
        self.assertAlmostEqual(sim._serve_ban_until, serve_time + GameSimulator.ANIMATION_DURATION)
        self.assertTrue(sim.is_in_animation_window())
        # 1.5s 后禁令解除
        sim.tick(1.5)
        self.assertFalse(sim.is_in_animation_window())

    def test_new_order_independent_visibility_during_ban_window(self):
        sim = make_sim(make_recipe(**R1))
        serve_time = self._serve_only_order(sim)  # t=5.0
        sim.tick(0.1)  # 新单 created_at=5.1，可见时刻 6.1

        # serve 禁令窗口内新单已存在但受 1s 可见性约束不可见
        self.assertIsNone(sim.get_order(0))
        sim.tick(0.9)  # t=6.0 < 6.1 仍不可见（可见性独立于禁令窗口）
        self.assertIsNone(sim.get_order(0))
        sim.tick(0.1)  # t=6.1 可见
        self.assertIsNotNone(sim.get_order(0))


if __name__ == "__main__":
    unittest.main()
