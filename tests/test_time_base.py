"""Issue #17 统一时基测试：假时钟确定性驱动订单超时/动画窗口/Runner 同步。

时基约定（见 core/models.py 文件头）：
- Order.created_at/timeout_at 为局内相对秒数（与 env.time 同基），非 epoch 墙钟
- GameEnv/Runner 的墙钟测量走注入 clock（默认 time.monotonic）
"""

import unittest
from unittest.mock import Mock

from hawarma.game.game_env import GameEnv
from hawarma.game.runner import Runner
from hawarma.game.scanner import DetectedOrder


class FakeClock:
    """可控单调时钟：手动 advance 驱动时间前进（起点取大值以模拟墙钟量级）。"""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, dt: float) -> None:
        self._now += dt


class TestFakeClockOrderTimeout(unittest.TestCase):
    """假时钟确定性驱动订单生命周期：创建 → 未超时 → 恰好超时"""

    def test_order_timestamps_are_in_game_relative_seconds(self):
        """add_order 的 created_at/timeout_at 是局内相对秒数，不是 clock 原始读数/epoch"""
        clock = FakeClock(start=1_000_000.0)
        env = GameEnv(cooker_names=["fryer"], clock=clock)
        env.start_game()
        clock.advance(10.0)

        env.add_order("shawarma", is_rush=False)

        order = env.orders[0]
        self.assertIsNotNone(order)
        assert order is not None
        # 相对时基：起点 1e6 的墙钟不泄漏进订单字段
        self.assertAlmostEqual(order.created_at, 10.0)
        self.assertAlmostEqual(order.timeout_at, 80.0)  # 非 rush 70s 超时
        self.assertAlmostEqual(order.time_remaining(env.time), 70.0)
        self.assertFalse(order.is_expired(env.time))

    def test_order_times_out_exactly_when_clock_crosses_deadline(self):
        """rush 订单 40s 超时：39.9s 未超时，跨过 40.0s 后被移除"""
        clock = FakeClock()
        env = GameEnv(cooker_names=["fryer"], clock=clock)
        env.start_game()
        order_id = env.add_order("shawarma", is_rush=True)

        clock.advance(39.9)
        self.assertEqual(env.check_and_remove_timed_out_orders(), [])
        clock.advance(0.1)
        self.assertEqual(env.check_and_remove_timed_out_orders(), [order_id])
        self.assertIsNone(env.orders[0])


class TestFakeClockAnimationWindow(unittest.TestCase):
    """假时钟确定性驱动动画窗口开启/过期"""

    def test_animation_window_opens_and_expires_with_clock(self):
        clock = FakeClock()
        env = GameEnv(cooker_names=["fryer"], clock=clock)

        env.set_animation_window(1.5)
        self.assertTrue(env.is_in_animation_window())
        self.assertGreater(env.animation_window_remaining(), 0.0)

        clock.advance(1.6)
        self.assertFalse(env.is_in_animation_window())
        self.assertEqual(env.animation_window_remaining(), 0.0)


class TestRunnerClockInjection(unittest.IsolatedAsyncioTestCase):
    """Runner 注入同一假时钟：订单时间戳走 env.time，ghost 窗口走墙钟"""

    def _make_runner(self, env: GameEnv, clock: FakeClock) -> Runner:
        class _StubScanner:
            def __init__(self, detected: list[DetectedOrder]) -> None:
                self._detected = detected

            async def scan_new_orders(self) -> list[DetectedOrder]:
                return self._detected

        detected = [
            DetectedOrder(
                slot_idx=0, recipe_slug="shawarma", is_rush=False, confidence=0.99
            )
        ]
        return Runner(
            env=env,
            operator=Mock(),
            scanner=_StubScanner(detected),
            verifier=Mock(),
            strategy=Mock(),
            recipes={},
            clock=clock,
        )

    async def test_sync_orders_stamps_relative_time_and_ghost_skips(self):
        clock = FakeClock(start=5000.0)
        env = GameEnv(cooker_names=["fryer"], clock=clock)
        env.start_game()
        clock.advance(5.0)
        runner = self._make_runner(env, clock)

        # 1) 扫描同步创建的订单用局内相对秒数（env.time=5，非 rush 70s）
        await runner._sync_orders_from_scan()
        order = env.orders[0]
        self.assertIsNotNone(order)
        assert order is not None
        self.assertAlmostEqual(order.created_at, 5.0)
        self.assertAlmostEqual(order.timeout_at, 75.0)

        # 2) ghost 保护：同类型订单 0.5s（墙钟）前刚 serve 且 env 中无活跃同名单
        #    → 扫描结果被跳过，不重建订单
        env._orders = [None] * 4
        runner._last_served[("shawarma", False)] = clock() - 0.5
        await runner._sync_orders_from_scan()
        self.assertIsNone(env.orders[0])


if __name__ == "__main__":
    unittest.main()
