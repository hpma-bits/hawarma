"""Issue #19 设备 IO 异步化：并发性测试（unittest.TestCase + stub/monkeypatch）.

验证设备 IO 移出事件循环后，三循环节拍（timeout 0.3s / agent 兜底 0.5s /
扫描 0.4-0.5s）在设备 IO 期间不被打断：

- Operator.swipe：假设备慢 swipe ≥0.3s（monkeypatch airtest api），与周期性
  心跳协程并发，断言 swipe 窗口内心跳 ≥2 次；同时验证 asyncio.Lock 串行化
  语义保留、耗时打点仍覆盖 to_thread 内的真实设备耗时。
- Runner._verify_with_multi_snapshot：慢 snapshot ×3 + 慢验证器（snapshot+
  模板匹配）并发心跳，断言验证窗口内心跳照常推进、结果与调用次数不变。
- Scanner.scan_orders 调试保存路径：脚本化假设备（首拍快、保存拍慢 0.35s），
  断言保存段（二次截图 + cv2.imwrite）期间心跳照常推进、调用语义不变。

对照测试：协程内同步 time.sleep 会让心跳停摆（<2 次），证明「≥2 次」断言
对「IO 是否阻塞事件循环」具备判别力。
"""

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hawarma.config import AppConfig
from hawarma.game.operator import Operator
from hawarma.game.runner import Runner
from hawarma.game.scanner import DetectedOrder, Scanner
from hawarma.recipe import Recipe, Station

RECIPE = "braisedNewYearFish"
# 假设备单次阻塞 IO 时长（≥0.3s，模拟真实 swipe / snapshot 占用）
SLOW_IO = 0.35
HEARTBEAT_INTERVAL = 0.06
WARMUP = 0.15
# swipe / 验证窗口内心跳次数下限（0.35s / 0.06s ≈ 5-6 拍，留裕量取 2）
MIN_BEATS = 2
# 窗口边界内缩（秒）：排除恰落在起点/终点处的节拍（时钟粒度与调度边缘），
# 使「窗口内心跳数」对「IO 是否阻塞事件循环」具备严格判别力
BEAT_EDGE_MARGIN = 0.005


def _make_recipe(slug: str, raw_ings: list[str], cookers: list[str],
                 durations: list[float]) -> Recipe:
    return Recipe(
        slug=slug,
        name=slug,
        raw_ingredients=raw_ings,
        cookers=cookers,
        cookers_layout=cookers,
        cook_durations=durations,
        condiments={},
        station=Station.GASTRONOME,
    )


def _make_operator() -> Operator:
    """真实 Operator：坐标映射 / 锁 / 计时为真，airtest swipe 由用例打桩."""
    recipes = [
        _make_recipe(RECIPE, ["clearwater_fish"], ["skillet"], [4.0]),
        _make_recipe("gildedShoreRisotto", ["clearwater_fish", "creamfield_rice"],
                     ["oven", "pot"], [3.0, 2.0]),
    ]
    return Operator(AppConfig(), recipes, station=Station.GASTRONOME)


class _SlowFakeDevice:
    """假设备：snapshot 阻塞 delay 秒（time.sleep，将在 worker 线程执行）."""

    def __init__(self, delay: float, screen=None) -> None:
        self.delay = delay
        self.screen = screen
        self.calls = 0

    def snapshot(self):
        self.calls += 1
        time.sleep(self.delay)
        return self.screen


class _ScriptedDevice:
    """脚本化假设备：按调用次序取 delays（超出取末值），用于区分扫描拍与保存拍."""

    def __init__(self, delays: list[float], screen=None) -> None:
        self._delays = list(delays)
        self._screen = screen
        self.calls = 0

    def snapshot(self):
        delay = self._delays[min(self.calls, len(self._delays) - 1)]
        self.calls += 1
        time.sleep(delay)
        return self._screen


class _FakeG:
    """替换 airtest G 的桩：只暴露 DEVICE."""

    def __init__(self, device) -> None:
        self.DEVICE = device


class _SlowStubVerifier:
    """验证器打桩：is_assembly_empty 阻塞 delay 秒后返回固定结果."""

    def __init__(self, delay: float, result: bool = True) -> None:
        self.delay = delay
        self.result = result
        self.calls = 0

    def is_assembly_empty(self) -> bool:
        self.calls += 1
        time.sleep(self.delay)
        return self.result


async def _heartbeat(beats: list[float], interval: float, stop: asyncio.Event) -> None:
    """周期性协程：每 interval 秒记录一次 perf_counter 时间戳（心跳）.

    用 time.perf_counter（高分辨率）而非 loop.time()：Windows 上
    loop.time() 基于 ~15.6ms 粒度的单调时钟，会把窗口边缘的节拍量化进窗口。
    """
    while not stop.is_set():
        await asyncio.sleep(interval)
        beats.append(time.perf_counter())


async def _run_with_heartbeat(target) -> tuple[list[float], float]:
    """并发驱动目标协程与心跳协程.

    先让心跳跑 WARMUP 秒，再执行目标协程；返回
    (目标执行窗口内的心跳时间戳列表, 窗口时长秒)。
    窗口两侧各内缩 BEAT_EDGE_MARGIN，排除边界节拍。
    """
    beats: list[float] = []
    stop = asyncio.Event()
    hb = asyncio.create_task(_heartbeat(beats, HEARTBEAT_INTERVAL, stop))
    await asyncio.sleep(WARMUP)
    start = time.perf_counter()
    await target()
    end = time.perf_counter()
    stop.set()
    await hb
    during = [
        b for b in beats
        if start + BEAT_EDGE_MARGIN <= b <= end - BEAT_EDGE_MARGIN
    ]
    return during, end - start


class TestHeartbeatHarnessControl(unittest.TestCase):
    """对照：事件循环内的同步阻塞确实让心跳停摆（证明断言有判别力）."""

    def test_sync_sleep_blocks_heartbeat(self):
        async def target():
            time.sleep(SLOW_IO)  # 反例：协程内同步阻塞

        during, window = asyncio.run(_run_with_heartbeat(target))
        # Windows sleep 粒度可能提前 ~1ms 返回，留 10ms 容差（窗口语义不变）
        self.assertGreaterEqual(window, SLOW_IO - 0.01)
        self.assertLess(len(during), MIN_BEATS, "sync sleep must stall the heartbeat")


class TestOperatorSwipeOffLoop(unittest.TestCase):
    """Operator.swipe 设备 IO 移出事件循环后的并发性与语义保留."""

    def test_heartbeat_progresses_during_slow_swipe(self):
        operator = _make_operator()
        device_times: list[float] = []

        def slow_swipe(start, end, duration=0.1, steps=5):
            t0 = time.perf_counter()
            time.sleep(SLOW_IO)
            device_times.append(time.perf_counter() - t0)

        async def target():
            await operator.swipe((100, 100), (200, 200), duration=0.1)

        with mock.patch("airtest.core.api.swipe", side_effect=slow_swipe):
            during, window = asyncio.run(_run_with_heartbeat(target))

        # 假设备慢 swipe 生效（≥0.3s），窗口覆盖真实设备耗时
        self.assertGreaterEqual(device_times[0], 0.3)
        self.assertGreaterEqual(window, SLOW_IO)
        # swipe 期间事件循环未被阻塞：心跳 ≥2 次
        self.assertGreaterEqual(
            len(during), MIN_BEATS,
            f"heartbeat stalled during swipe: {len(during)} beats in {window:.3f}s",
        )
        # 耗时打点仍覆盖 to_thread 内的真实设备往返（可测性不受影响）
        seg = operator.timing.swipe
        self.assertEqual(seg.count, 1)
        self.assertGreaterEqual(seg.total, 0.3)

    def test_concurrent_swipes_serialized_by_lock(self):
        operator = _make_operator()
        events: list[tuple[str, float]] = []

        def slow_swipe(start, end, duration=0.1, steps=5):
            events.append(("enter", time.perf_counter()))
            time.sleep(0.1)
            events.append(("exit", time.perf_counter()))

        async def target():
            await asyncio.gather(
                operator.swipe((0, 0), (1, 1)),
                operator.swipe((2, 2), (3, 3)),
            )

        with mock.patch("airtest.core.api.swipe", side_effect=slow_swipe):
            asyncio.run(target())

        # 串行化语义保留：enter/exit 严格交替，第二次 enter 晚于第一次 exit
        self.assertEqual([e[0] for e in events], ["enter", "exit", "enter", "exit"])
        self.assertLessEqual(events[1][1], events[2][1])


class TestRunnerVerifyOffLoop(unittest.TestCase):
    """Runner._verify_with_multi_snapshot：snapshot ×3 + 验证器全线程化."""

    def test_heartbeat_progresses_during_multi_snapshot_verify(self):
        device = _SlowFakeDevice(delay=0.12, screen=None)
        verifier = _SlowStubVerifier(delay=0.15, result=True)
        # 仿 tests/test_action_dispatch.py 的 Stub 模式：
        # __new__ 绕过设备依赖，只注入本方法用到的 verifier
        runner = Runner.__new__(Runner)
        runner.verifier = verifier
        results: list[bool] = []

        async def target():
            results.append(await Runner._verify_with_multi_snapshot(runner))

        with mock.patch("hawarma.game.runner.G", _FakeG(device)):
            during, window = asyncio.run(_run_with_heartbeat(target))

        # 行为零变化：3 次预热 snapshot + 1 次验证，结果透传
        self.assertEqual(device.calls, 3)
        self.assertEqual(verifier.calls, 1)
        self.assertEqual(results, [True])
        # 窗口 ≥ 3×0.12 + 0.15，期间事件循环照常推进
        self.assertGreaterEqual(window, 3 * 0.12 + 0.15)
        self.assertGreaterEqual(
            len(during), MIN_BEATS,
            f"heartbeat stalled during verify: {len(during)} beats in {window:.3f}s",
        )


class TestScannerDebugSaveOffLoop(unittest.TestCase):
    """Scanner 调试保存路径（二次截图 + 写盘）不阻塞扫描关键路径."""

    def test_debug_save_does_not_block_scan_path(self):
        scanner = Scanner.__new__(Scanner)  # 绕过 __init__ 的目录/配置副作用
        scanner._save_screenshots = True
        orders_seen: list[list] = []

        with tempfile.TemporaryDirectory() as tmp:
            scanner._screenshot_dir = Path(tmp)
            # 第 1 拍（扫描截图）快；第 2 拍（保存路径的二次截图）慢 0.35s，
            # 使窗口内心跳几乎全部落在保存段，得以判别保存是否阻塞
            device = _ScriptedDevice(delays=[0.01, SLOW_IO], screen=object())

            async def target():
                orders_seen.append(await scanner.scan_orders())

            detected = DetectedOrder(
                slot_idx=0, recipe_slug=RECIPE, is_rush=False, confidence=0.99
            )
            with mock.patch("hawarma.game.scanner.G", _FakeG(device)), \
                    mock.patch.object(
                        scanner, "_detect_order",
                        side_effect=lambda slot, screen: detected,
                    ), \
                    mock.patch("cv2.imwrite") as imwrite:
                during, window = asyncio.run(_run_with_heartbeat(target))

        # 行为零变化：4 槽扫描结果、两次截图（扫描 + 保存）、一次写盘
        self.assertEqual(len(orders_seen[0]), 4)
        self.assertEqual(device.calls, 2)
        imwrite.assert_called_once()
        # 保存段（0.35s 阻塞 IO）期间事件循环照常推进
        self.assertGreaterEqual(window, SLOW_IO)
        self.assertGreaterEqual(
            len(during), MIN_BEATS,
            f"heartbeat stalled during debug save: {len(during)} beats in {window:.3f}s",
        )


if __name__ == "__main__":
    unittest.main()
