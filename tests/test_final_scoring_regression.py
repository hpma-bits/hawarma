"""Ticket #12 回归护栏 1：终局结算（一次加总且幂等，同种子双端一致）.

只断言外部可观测行为（docs/game_rules.md:226）：
    最终总分 = 所有已完成订单的得分之和 + 游戏结束时的总 visibility

覆盖（unittest.TestCase，挂进 `python -m unittest discover tests` 统一跑器）：
- 一次加总：终局分数 = 逐单得分和 + 总 visibility，不重复计入 visibility
- 幂等：重复 finalize() / 反复 get_stats() 查询不重复加总
- 同种子确定性：SimEnv 同种子同 Action 序列两次终局一致
- 双端一致：同一送餐账本（含 rush / visibility 阈值跨越）下，
  真实 GameEnv.on_order_served 与 GameSimulator.serve_order 两条
  各自独立的计分路径得出相同的逐单分、总 visibility 与终局分

已有覆盖（pytest 风格、仅 `pytest` 跑器收集，本文件不重复实现）：
- tests/test_final_scoring.py —— 终局含 visibility、finalize 幂等、
  EpisodeResult/CSV 携带 scoring_version
- tests/test_real_env_scoring.py —— on_order_served 单价与倍率细节
- tests/test_action_dispatch.py::TestDualEndReplay —— 经 dispatch 的
  送餐序列双端回放一致

金快照生成方式：无（本文件不含金快照，见 test_gastronome_golden.py）.
"""

import unittest

from hawarma.core.actions import CookAction
from hawarma.core.models import Order
from hawarma.core.reward import RecipeRewardLookup
from hawarma.core.scoring import SCORING_VERSION, finalize_score
from hawarma.game.game_env import GameEnv
from hawarma.paths import data_path
from playground.env.sim import SimEnv
from playground.env_simulator import GameSimulator

RECIPE_A = "braisedNewYearFish"
RECIPE_B = "farmsteadFeastRoast"
SLUGS = [RECIPE_A, "gildedShoreRisotto", RECIPE_B, "newYearJiaozi"]
SEED = 12


class TestFinalSettlementSumsOnce(unittest.TestCase):
    """终局 = 逐单得分和 + 总 visibility，一次加总."""

    def test_final_score_equals_per_order_sum_plus_visibility(self):
        env = GameEnv(cooker_names=["skillet", "pot"], stockpile_slots=3)
        lookup = RecipeRewardLookup()

        # 依次「生成订单 → 立即送出」：spawn 时的总 visibility 确定性累加，
        # 覆盖 rush 与 has_condiments 两种形态
        ledger = [
            (RECIPE_A, False, True),
            (RECIPE_A, True, False),
            (RECIPE_B, False, True),
        ]
        expected_score = 0.0
        expected_vis = 0.0
        for i, (slug, rush, has_cond) in enumerate(ledger):
            spawn_vis = expected_vis  # add_order 锁定当前总 visibility
            env.add_order(slug, is_rush=rush)
            order = env.orders[0]
            self.assertIsNotNone(order)
            env.on_order_served(order, has_condiments=has_cond)
            env.serve_order(0)  # 腾出槽位供下一单

            expected_score += lookup.get_score(slug, has_cond, rush, spawn_vis)
            expected_vis += lookup.get_visibility(slug, has_cond)

        stats = env.get_stats()
        self.assertAlmostEqual(stats["total_score"], expected_score)
        self.assertAlmostEqual(stats["total_visibility"], expected_vis)
        # 一次加总：visibility 只通过终局项计一次，不得重复叠加
        self.assertAlmostEqual(env.finalize(), expected_score + expected_vis)
        self.assertAlmostEqual(stats["final_score"], expected_score + expected_vis)
        self.assertEqual(stats["scoring_version"], SCORING_VERSION)

    def test_finalize_and_repeated_stats_queries_do_not_inflate(self):
        """幂等：多次结算与反复统计查询不改变任何分数."""
        env = GameEnv(cooker_names=["skillet", "pot"], stockpile_slots=3)
        env.add_order(RECIPE_A, is_rush=False)
        order = env.orders[0]
        self.assertIsNotNone(order)
        env.on_order_served(order, has_condiments=True)

        finals = [env.finalize() for _ in range(3)]
        self.assertEqual(finals[0], finals[1])
        self.assertEqual(finals[1], finals[2])

        # 反复查询统计无副作用：分数不随查询次数增长
        first = env.get_stats()
        for _ in range(50):
            stats = env.get_stats()
            self.assertEqual(stats["total_score"], first["total_score"])
            self.assertEqual(stats["total_visibility"], first["total_visibility"])
            self.assertEqual(stats["final_score"], first["final_score"])
        self.assertEqual(env.finalize(), finals[0])


class TestSameSeedDeterminism(unittest.TestCase):
    """同种子：SimEnv 同种子同 Action 序列两次运行终局一致."""

    def test_same_seed_same_sequence_same_final(self):
        seq = [
            CookAction("clearwater_fish", "skillet", 4.0, priority=1),
            CookAction("creamfield_rice", "pot", 2.0, priority=2),
        ]
        finals = []
        stat_list = []
        for _ in range(2):
            env = SimEnv()
            env.reset(seed=SEED, recipe_slugs=SLUGS)
            env.run_action_sequence(list(seq))
            # 推进若干 tick 让烹饪时间流逝，产生订单/超时等事件
            for _ in range(30):
                env.step(None)
            finals.append(env.finalize())
            stat_list.append(env.get_stats())

        self.assertAlmostEqual(finals[0], finals[1])
        for key in ("actions_taken", "orders_served", "orders_timeout", "scoring_version"):
            self.assertEqual(
                stat_list[0][key], stat_list[1][key], msg=f"stats[{key}] diverged"
            )


class TestDualEndSameLedger(unittest.TestCase):
    """双端一致：同一送餐账本，真实端与模拟器各自计分路径终局一致.

    真实端走 GameEnv.on_order_served（RecipeRewardLookup 直查），
    模拟器端走 GameSimulator.serve_order（serve_order 内部 _calculate_score），
    两条路径互不复用，最后用共享终局语义 finalize_score 对齐比较。
    """

    LEDGER = [
        (RECIPE_A, False),
        (RECIPE_A, True),  # 第 2 单 rush，spawn 总 visibility 已进入加成区间
        (RECIPE_B, False),
        (RECIPE_A, False),
    ]

    def test_real_env_and_simulator_agree_on_same_serve_ledger(self):
        lookup = RecipeRewardLookup()
        ledger = self.LEDGER  # (slug, is_rush)，全部带调料（模拟器 serve 要求调料齐全）

        # ── 模拟器端：inject → 组装齐全 → serve_order（模拟器自算得分） ──
        sim = GameSimulator()
        sim.load_recipes(data_path("recipes.json"))
        sim.setup_from_recipes(SLUGS)

        sim_scores = []
        for slug, rush in ledger:
            recipe = sim._recipes[slug]
            inject = sim.inject_order(0, recipe, is_rush=rush)
            self.assertTrue(inject.success, msg=f"inject {slug} failed")
            asm = sim._state.assembly
            asm.target_recipe_slug = slug
            asm.ingredients = [
                (ing.name, ing.cooker_type, 0.0) for ing in recipe.ingredients
            ]
            asm.condiments = dict(recipe.condiments)
            result = sim.serve_order(0)
            self.assertTrue(result.success, msg=f"serve {slug} failed")
            sim_scores.append(result.score_earned)
            # serve 后模拟器进入动画窗口；tick 会引入随机订单生成，
            # 故直接关闭窗口以保持账本确定性（与既有测试直接操作 _state 同风格）
            # #14 将单一动画窗口拆分为 serve 禁令窗口，此处重置以保持账本确定性
            sim._serve_ban_until = 0.0

        # ── 真实端：构造同 spawn visibility 的订单逐单送出 ──
        real = GameEnv(cooker_names=["skillet", "pot", "oven"], stockpile_slots=3)
        spawn_vis = 0.0
        for order_id, ((slug, rush), sim_score) in enumerate(
            zip(ledger, sim_scores), start=1
        ):
            order = Order(
                order_id=order_id,
                recipe_slug=slug,
                is_rush=rush,
                created_at=0.0,
                timeout_at=70.0,
                spawned_at_visibility=spawn_vis,
            )
            real.on_order_served(order, has_condiments=True)
            # 模拟器端逐单得分（含区间倍率）必须与查表口径一致
            self.assertAlmostEqual(
                sim_score,
                lookup.get_score(slug, True, rush, spawn_vis),
                msg=f"per-order score diverged at order {order_id} ({slug})",
            )
            spawn_vis += lookup.get_visibility(slug, True)

        real_stats = real.get_stats()
        # 双端逐单和与总 visibility 一致
        self.assertAlmostEqual(real_stats["total_score"], sim._total_score)
        self.assertAlmostEqual(real_stats["total_visibility"], sim._state.total_visibility)
        # 终局分一致：真实端 finalize() vs 共享终局语义加总模拟器端账本
        self.assertAlmostEqual(
            real.finalize(),
            finalize_score(sim._total_score, sim._state.total_visibility),
        )


if __name__ == "__main__":
    unittest.main()
