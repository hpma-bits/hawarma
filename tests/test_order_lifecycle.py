"""Issue #18 订单生命周期测试：创建/扫描同步/serve 结算收敛为 GameEnv 原子 API。

竞态修复的回归护栏（全部用假时钟确定性构造竞态场景）：
- 防复活：已 serve / 已 timeout 删除的订单不被旧扫描帧复活
  （env 内记忆窗口，独立于 Runner 的 serve ghost 窗口）
- 延迟删除：订单连续 SCAN_MISS_DELETE_THRESHOLD(=2) 次扫描未出现才删除；
  中途重新扫到则 miss 计数清零
- 不串单：同 (slug, rush) 多单并存时按槽位匹配，order_id/对象身份保持
- serve 按 id 结算：serve 验证窗口（await 期间）目标单被 timeout 移位/删除后，
  结算找到正确订单（移位场景）或安全跳过（删除场景），绝不把分记到别的单上
- create_order 超时查表（RecipeTimeoutLookup 注入/懒加载）与 fallback
"""

import asyncio
import unittest
from unittest import mock

from hawarma.core.actions import ServeOrderAction
from hawarma.core.reward import RecipeRewardLookup, RecipeTimeoutLookup
from hawarma.game.game_env import GameEnv
from hawarma.game.runner import Runner
from hawarma.game.timing import ExecutionTiming


class FakeClock:
    """可控单调时钟：手动 advance 驱动时间前进（起点取大值以模拟墙钟量级）。"""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, dt: float) -> None:
        self._now += dt


# braisedNewYearFish 在 data/recipe_timeout.csv 中：normal=62, rush=37
CSV_SLUG = "braisedNewYearFish"
CSV_NORMAL_TIMEOUT = 62.0
CSV_RUSH_TIMEOUT = 37.0
# 不在 recipe_timeout.csv 中的 slug → 走 GameEnv 类常量 fallback（70/40）
UNKNOWN_SLUG = "shawarma"


def _make_env(clock: FakeClock) -> GameEnv:
    env = GameEnv(cooker_names=["fryer", "pot"], clock=clock)
    env.start_game()
    return env


# ============================================================================
# create_order：超时查表 / fallback / visibility 锁定 / id 自增
# ============================================================================


class TestCreateOrderTimeout(unittest.TestCase):
    """create_order 的 timeout 单源：RecipeTimeoutLookup 查表 + fallback 类常量。"""

    def test_timeout_from_real_csv_lookup(self):
        """真实 CSV 命中：braisedNewYearFish normal=62 / rush=37（懒加载路径）"""
        clock = FakeClock(start=5000.0)
        env = _make_env(clock)
        clock.advance(10.0)

        normal = env.create_order(CSV_SLUG, is_rush=False)
        rush = env.create_order(CSV_SLUG, is_rush=True)

        self.assertAlmostEqual(normal.timeout_at, 10.0 + CSV_NORMAL_TIMEOUT)
        self.assertAlmostEqual(rush.timeout_at, 10.0 + CSV_RUSH_TIMEOUT)

    def test_timeout_fallback_for_unknown_recipe(self):
        """查不到该配方：fallback 到原硬编码行为（normal 70 / rush 40）"""
        clock = FakeClock()
        env = _make_env(clock)
        clock.advance(10.0)

        normal = env.create_order(UNKNOWN_SLUG, is_rush=False)
        rush = env.create_order(UNKNOWN_SLUG, is_rush=True)

        self.assertAlmostEqual(normal.timeout_at, 10.0 + 70.0)
        self.assertAlmostEqual(rush.timeout_at, 10.0 + 40.0)

    def test_injected_timeout_lookup_takes_precedence(self):
        """构造注入的 lookup 实例优先（与 #22 reward_lookup 注入模式一致）"""
        lookup = mock.Mock(spec=RecipeTimeoutLookup)
        lookup.get_timeout.return_value = 12.5
        clock = FakeClock()
        env = _make_env(clock)
        env2 = GameEnv(cooker_names=["fryer"], clock=clock, timeout_lookup=lookup)
        env2.start_game()
        clock.advance(3.0)

        order = env2.create_order("whatever", is_rush=False)

        lookup.get_timeout.assert_called_once_with("whatever", False)
        self.assertAlmostEqual(order.timeout_at, 3.0 + 12.5)

    def test_create_order_locks_visibility_and_increments_id_without_slot(self):
        """生成瞬间锁定 total_visibility；order_id 自增；不落槽位（由调用方决定）"""
        clock = FakeClock()
        env = _make_env(clock)
        env._scoring.total_visibility = 25.0

        first = env.create_order(UNKNOWN_SLUG, is_rush=False)
        second = env.create_order(UNKNOWN_SLUG, is_rush=True)

        self.assertEqual(first.order_id, 1)
        self.assertEqual(second.order_id, 2)
        self.assertAlmostEqual(first.spawned_at_visibility, 25.0)
        self.assertAlmostEqual(second.spawned_at_visibility, 25.0)
        # create_order 只构造对象：槽位仍空，由 apply_scan_result / add_order 落位
        self.assertEqual(env.orders, [None, None, None, None])


# ============================================================================
# 防复活：已 serve / 已 timeout 的订单不被旧扫描帧复活
# ============================================================================


class TestNoResurrection(unittest.TestCase):
    """扫描旧帧到达时，已删除订单不得被重建为新单。"""

    def test_served_order_not_resurrected_by_stale_scan_frame(self):
        """已 serve 的订单：旧帧仍显示它 → 不重建（env 记忆窗口，无 runner ghost）"""
        clock = FakeClock(start=1_000_000.0)
        env = _make_env(clock)
        served_id = env.add_order(UNKNOWN_SLUG, is_rush=False)
        assert served_id is not None

        self.assertTrue(env.serve_order(0))
        clock.advance(0.3)  # 仍在记忆窗口（< 1.5s）：扫描捕获 serve 前旧帧

        stats = env.apply_scan_result([(UNKNOWN_SLUG, False)])

        self.assertIsNone(env.orders[0])
        self.assertEqual(stats["created"], 0)
        self.assertEqual(stats["resurrection_blocked"], 1)

    def test_timed_out_order_not_resurrected_by_stale_scan_frame(self):
        """已 timeout 删除的订单：旧帧仍显示它 → 不重建（timeout 删除无 ghost 窗口防护）"""
        clock = FakeClock()
        env = _make_env(clock)
        timed_out_id = env.add_order(UNKNOWN_SLUG, is_rush=False)  # timeout_at=70
        assert timed_out_id is not None

        clock.advance(70.0)
        self.assertEqual(env.check_and_remove_timed_out_orders(), [timed_out_id])
        clock.advance(0.2)  # 记忆窗口内

        stats = env.apply_scan_result([(UNKNOWN_SLUG, False)])

        self.assertIsNone(env.orders[0])
        self.assertEqual(stats["created"], 0)
        self.assertEqual(stats["resurrection_blocked"], 1)

    def test_memory_window_expires_and_respawn_is_allowed(self):
        """记忆窗口过期后，同名单可作为合法新单重建（新 order_id）"""
        clock = FakeClock(start=1_000_000.0)
        env = _make_env(clock)
        served_id = env.add_order(UNKNOWN_SLUG, is_rush=False)
        assert served_id is not None
        env.serve_order(0)

        clock.advance(2.0)  # 超过 REMOVED_ORDER_MEMORY_WINDOW(1.5s)

        env.apply_scan_result([(UNKNOWN_SLUG, False)])

        order = env.orders[0]
        self.assertIsNotNone(order)
        assert order is not None
        self.assertNotEqual(order.order_id, served_id)  # 是新单，不是复活

    def test_serve_ghost_window_skips_only_when_no_active_same_type(self):
        """serve ghost 窗口（recently_served）：无活跃同名单才跳过；有则正常匹配"""
        clock = FakeClock(start=1_000_000.0)
        env = _make_env(clock)
        order_id = env.add_order(UNKNOWN_SLUG, is_rush=False)
        assert order_id is not None
        order = env.orders[0]
        assert order is not None

        recently = {(UNKNOWN_SLUG, False): clock() - 0.5}

        # 有活跃同名单 → 不视为幽灵，匹配保留原单
        stats = env.apply_scan_result(
            [(UNKNOWN_SLUG, False)], recently_served=recently
        )
        self.assertEqual(stats["reused"], 1)
        self.assertIs(env.orders[0], order)

        # 无活跃同名单 → 跳过，不重建
        env.serve_order(0)
        stats = env.apply_scan_result(
            [(UNKNOWN_SLUG, False)], recently_served=recently
        )
        self.assertEqual(stats["ghost_skipped"] + stats["resurrection_blocked"], 1)
        self.assertEqual(stats["created"], 0)
        self.assertIsNone(env.orders[0])


# ============================================================================
# 连续 N 次未扫到才删除
# ============================================================================


class TestMissThresholdDeletion(unittest.TestCase):
    """删除语义：连续 SCAN_MISS_DELETE_THRESHOLD(=2) 次未扫到才删除。"""

    def test_first_miss_keeps_order_second_miss_removes(self):
        clock = FakeClock()
        env = _make_env(clock)
        kept_id = env.add_order(UNKNOWN_SLUG, is_rush=False)  # slot0
        other_id = env.add_order("falafel", is_rush=False)  # slot1
        assert kept_id is not None and other_id is not None

        # 第 1 次未扫到 other：保留（miss=1）
        stats1 = env.apply_scan_result([(UNKNOWN_SLUG, False)])
        self.assertEqual(stats1["kept_pending_removal"], 1)
        self.assertEqual(stats1["removed"], 0)
        self.assertIsNotNone(env.get_order_by_id(other_id))

        # 第 2 次连续未扫到：删除
        stats2 = env.apply_scan_result([(UNKNOWN_SLUG, False)])
        self.assertEqual(stats2["removed"], 1)
        self.assertIsNone(env.get_order_by_id(other_id))
        # 未消失的订单不受影响
        self.assertIsNotNone(env.get_order_by_id(kept_id))

    def test_miss_counter_resets_when_order_reappears(self):
        """miss 1 后重新扫到 → 计数清零；下一次未扫到仍是 miss 1（不删除）"""
        clock = FakeClock()
        env = _make_env(clock)
        order_id = env.add_order(UNKNOWN_SLUG, is_rush=False)
        assert order_id is not None
        other_id = env.add_order("falafel", is_rush=False)
        assert other_id is not None

        env.apply_scan_result([("falafel", False)])  # target miss 1
        env.apply_scan_result(
            [(UNKNOWN_SLUG, False), ("falafel", False)]
        )  # 重新扫到 → 清零
        stats = env.apply_scan_result([("falafel", False)])  # 再 miss 1（非 2）

        self.assertEqual(stats["removed"], 0)
        self.assertIsNotNone(env.get_order_by_id(order_id))


# ============================================================================
# 同 (slug, rush) 多单并存：按 slot 匹配不串单
# ============================================================================


class TestMultiSameTypeMatching(unittest.TestCase):
    """同 (slug, rush) 多单并存：匹配复用原对象，order_id/时间戳不串。"""

    def test_two_same_type_orders_both_matched_by_identity(self):
        clock = FakeClock()
        env = _make_env(clock)
        env.add_order(UNKNOWN_SLUG, is_rush=False)
        env.add_order(UNKNOWN_SLUG, is_rush=False)
        first, second = env.orders[0], env.orders[1]
        assert first is not None and second is not None
        created_at_first = first.created_at

        stats = env.apply_scan_result(
            [(UNKNOWN_SLUG, False), (UNKNOWN_SLUG, False)]
        )

        self.assertEqual(stats["reused"], 2)
        self.assertEqual(stats["created"], 0)
        # 对象身份保持：不串单、不重建
        self.assertIs(env.orders[0], first)
        self.assertIs(env.orders[1], second)
        self.assertAlmostEqual(env.orders[0].created_at, created_at_first)

    def test_shifted_positions_match_by_type_anywhere(self):
        """位移匹配：env [C, D]，扫描顺序 [D, C] → 按类型各归其位，id 保持"""
        clock = FakeClock()
        env = _make_env(clock)
        c_id = env.add_order("falafel", is_rush=False)  # slot0
        d_id = env.add_order(UNKNOWN_SLUG, is_rush=False)  # slot1
        assert c_id is not None and d_id is not None

        env.apply_scan_result([(UNKNOWN_SLUG, False), ("falafel", False)])

        self.assertEqual(env.orders[0].order_id, d_id)
        self.assertEqual(env.orders[1].order_id, c_id)
        self.assertIsNone(env.orders[2])


# ============================================================================
# serve 按 order_id 结算：验证窗口内 timeout 移位/删除的竞态
# ============================================================================


class _TimeoutDuringSwipeOperator:
    """stub Operator：serve swipe 的 await 期间模拟 timeout 循环触发。

    推进假时钟越过指定订单的超时点并调用 check_and_remove_timed_out_orders，
    精确复现「serve 验证窗口（≥0.25s await）内 timeout 移位/删除」的竞态。
    """

    def __init__(self, env: GameEnv, clock: FakeClock, advance: float) -> None:
        self._env = env
        self._clock = clock
        self._advance = advance

    async def serve_order(self, slot_idx: int) -> None:
        self._clock.advance(self._advance)
        # 模拟真实 timeout 循环：移除 + 记超时统计（Runner._timeout_loop 语义）
        for order_id in self._env.check_and_remove_timed_out_orders():
            self._env.on_order_timeout(order_id)

    async def clear_assembly(self) -> None:
        pass


class _StubVerifier:
    def __init__(self, is_empty: bool) -> None:
        self._is_empty = is_empty

    def is_assembly_empty(self) -> bool:
        return self._is_empty


class TestServeSettlesById(unittest.TestCase):
    """serve 结算竞态：按 serve 前锁定的 order_id，绝不结算到错单。"""

    def _make_runner(
        self, env: GameEnv, clock: FakeClock, operator, verifier
    ) -> Runner:
        # 仿 tests/test_execution_timing_baseline.py 的 Stub 模式：
        # __new__ 绕过设备依赖，注入真实 env + 打桩 operator/verifier
        runner = Runner.__new__(Runner)
        runner.env = env
        runner.ui = operator
        runner.verifier = verifier
        runner._timing = ExecutionTiming()
        runner._last_served = {}
        runner._serve_verify_wait = 0.0
        runner._clock = clock
        Runner._build_action_handlers(runner)
        return runner

    def test_target_timed_out_during_window_scores_nothing(self):
        """目标单在验证窗口内被 timeout 删除 → 安全跳过：不计分、不错单。

        旧实现按 success_slot 取 env.orders[slot] 结算：目标单删除后槽位左移，
        会把分记到移位上来的另一张单（U）头上。
        """
        clock = FakeClock(start=1_000_000.0)
        env = _make_env(clock)
        target_id = env.add_order(UNKNOWN_SLUG, is_rush=True)  # timeout 40
        other_id = env.add_order("falafel", is_rush=False)  # timeout 70
        assert target_id is not None and other_id is not None

        operator = _TimeoutDuringSwipeOperator(env, clock, advance=41.0)
        runner = self._make_runner(env, clock, operator, _StubVerifier(True))

        with mock.patch("hawarma.game.runner.G"):
            asyncio.run(runner._exec_serve_order(ServeOrderAction(slot_idx=0)))

        # 目标单已被 timeout 删除：不结算、不计分
        stats = env.get_stats()
        self.assertEqual(stats["orders_served"], 0)
        self.assertAlmostEqual(stats["total_score"], 0.0)
        self.assertEqual(stats["orders_timeout"], 1)
        # 移位上来的另一张单绝不被误结算
        survivor = env.orders[0]
        self.assertIsNotNone(survivor)
        assert survivor is not None
        self.assertEqual(survivor.order_id, other_id)
        self.assertFalse(survivor.done)

    def test_target_shifted_during_window_settles_correct_order(self):
        """目标单在验证窗口内因前置单 timeout 而左移 → 仍按 id 找到并正确结算。

        env [V(rush, 先超时), T(normal)]；serve 目标是 slot1 的 T。窗口内 V
        超时删除，T 左移到 slot0。旧实现按 slot1 取单（移位后为 None）会漏结算。
        """
        clock = FakeClock(start=1_000_000.0)
        env = _make_env(clock)
        v_id = env.add_order(CSV_SLUG, is_rush=True)  # timeout 37（CSV）
        target_id = env.add_order(CSV_SLUG, is_rush=False)  # timeout 62（CSV）
        assert v_id is not None and target_id is not None

        operator = _TimeoutDuringSwipeOperator(env, clock, advance=38.0)
        runner = self._make_runner(env, clock, operator, _StubVerifier(True))

        with mock.patch("hawarma.game.runner.G"):
            asyncio.run(runner._exec_serve_order(ServeOrderAction(slot_idx=1)))

        # T（target_id）被正确结算：无调料 + spawned_at_vis=0 → (64+14)*1.0
        stats = env.get_stats()
        self.assertEqual(stats["orders_served"], 1)
        self.assertAlmostEqual(stats["total_score"], (64 + 14) * 1.0)
        self.assertAlmostEqual(stats["total_visibility"], 14)
        self.assertIsNone(env.get_order_by_id(target_id))
        self.assertEqual(stats["orders_timeout"], 1)  # V 正常记超时

    def test_serve_order_by_id_missing_order_returns_none(self):
        """env API 直测：serve_order_by_id 找不到订单 → warning + None，无副作用"""
        clock = FakeClock()
        env = _make_env(clock)
        order_id = env.add_order(UNKNOWN_SLUG, is_rush=False)
        assert order_id is not None
        env.assembly.ingredients.append(("something", "fryer", 0.0))

        result = env.serve_order_by_id(order_id + 999)

        self.assertIsNone(result)
        # 不改状态：订单仍在、assembly 不被清空（与旧 serve_order 失败路径一致）
        self.assertIsNotNone(env.get_order_by_id(order_id))
        self.assertTrue(len(env.assembly.ingredients) > 0)

        # 对照：存在的 id 正常结算并返回被结算订单
        settled = env.serve_order_by_id(order_id)
        self.assertIsNotNone(settled)
        assert settled is not None
        self.assertEqual(settled.order_id, order_id)
        self.assertTrue(settled.done)
        self.assertEqual(len(env.assembly.ingredients), 0)


# ============================================================================
# Runner 扫描委托：_sync_orders_from_scan 只扫描 + 调 apply_scan_result
# ============================================================================


class TestRunnerSyncDelegation(unittest.IsolatedAsyncioTestCase):
    """Runner 同步循环委托 env.apply_scan_result（含 serve ghost 透传）。"""

    async def test_sync_delegates_and_uses_env_time_and_lookup(self):
        """经 Runner._sync_orders_from_scan 创建的单：相对时基 + 超时查表单源"""
        from hawarma.game.scanner import DetectedOrder

        clock = FakeClock(start=5000.0)
        env = _make_env(clock)
        clock.advance(5.0)

        class _StubScanner:
            async def scan_new_orders(self) -> list[DetectedOrder]:
                return [
                    DetectedOrder(
                        slot_idx=0,
                        recipe_slug=CSV_SLUG,
                        is_rush=False,
                        confidence=0.99,
                    )
                ]

        runner = Runner.__new__(Runner)
        runner.env = env
        runner.scanner = _StubScanner()
        runner._last_served = {}
        runner._clock = clock

        await runner._sync_orders_from_scan()

        order = env.orders[0]
        self.assertIsNotNone(order)
        assert order is not None
        self.assertAlmostEqual(order.created_at, 5.0)
        self.assertAlmostEqual(order.timeout_at, 5.0 + CSV_NORMAL_TIMEOUT)
        self.assertEqual(order.order_id, 1)


if __name__ == "__main__":
    unittest.main()
