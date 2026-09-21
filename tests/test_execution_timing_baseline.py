"""Ticket #12 回归护栏 2：送餐与滑动耗时基线（只观测，不卡阈值）.

用 stub / monkeypatch 驱动一次真实代码路径的执行：
- 滑动往返：真实 Operator（airtest swipe 打桩为 no-op，计时逻辑为真）
- 送餐路径：真实 Runner 分发（dispatch_batch）驱动 _exec_serve_order，
  验证器打桩分别命中「一次成功」与「两次失败 → 重试 → 清理」两条路径

只断言外部可观测行为：ExecutionTiming 各分段「有记录 + 数值在宽松合理区间
（0 ≤ 耗时 < 60s）」，不设任何性能阈值（阈值待 30 局直方图基线后另定）。

已有覆盖（pytest 风格、仅 `pytest` 跑器收集，本文件不重复实现）：
- tests/test_execution_timing.py —— SegmentTiming/ExecutionTiming 聚合、
  Timer 幂等、to_dict 分段键、动画窗口剩余、SrvGap/Idle 直方图
- 本文件补的缺口：经真实执行路径（swipe 往返 + 送餐验证/重试/清理）
  驱动打点落账的基线回归.
"""

import asyncio
import unittest
from unittest import mock

from hawarma.config import AppConfig
from hawarma.core.actions import CookAction, ServeOrderAction
from hawarma.game.game_env import GameEnv
from hawarma.game.runner import Runner
from hawarma.game.timing import ExecutionTiming
from hawarma.game.operator import Operator
from hawarma.recipe import Recipe, Station

RECIPE = "braisedNewYearFish"
# 宽松合理区间上限（秒）：单段操作耗时的物理上界，不是性能阈值
SANE_UPPER_BOUND = 60.0


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
    """真实 Operator：坐标映射与滑动计时为真，airtest swipe 打桩为 no-op."""
    recipes = [
        _make_recipe(RECIPE, ["clearwater_fish"], ["skillet"], [4.0]),
        _make_recipe("gildedShoreRisotto", ["clearwater_fish", "creamfield_rice"],
                     ["oven", "pot"], [3.0, 2.0]),
    ]
    return Operator(AppConfig(), recipes, station=Station.GASTRONOME)


class _StubVerifier:
    """送餐验证器打桩：可切换「组装站已空（serve 成功）」两种回报."""

    def __init__(self, is_empty: bool) -> None:
        self.is_empty = is_empty

    def is_assembly_empty(self) -> bool:
        return self.is_empty


class TestOperatorSwipeTimingBaseline(unittest.TestCase):
    """滑动往返耗时：经 Operator 真实 swipe 封装落账."""

    def test_swipe_roundtrip_recorded_in_sane_range(self):
        operator = _make_operator()
        with mock.patch("airtest.core.api.swipe"):
            asyncio.run(operator.cook("clearwater_fish", "skillet"))
            asyncio.run(operator.serve_order(0))

        swipe = operator.timing.swipe
        self.assertGreaterEqual(swipe.count, 2)
        self.assertLess(swipe.avg, SANE_UPPER_BOUND)
        self.assertGreater(swipe.avg, 0.0)
        self.assertLess(swipe.total, SANE_UPPER_BOUND)
        self.assertLess(swipe.max, SANE_UPPER_BOUND)
        self.assertGreaterEqual(swipe.max, swipe.avg)


class TestRunnerServePathTimingBaseline(unittest.TestCase):
    """送餐验证路径：经 dispatch_batch 真实分发驱动各分段打点落账."""

    def setUp(self) -> None:
        self.env = GameEnv(cooker_names=["skillet", "oven", "pot"], stockpile_slots=3)
        self.operator = _make_operator()

    def _make_runner(self, verifier: _StubVerifier) -> Runner:
        # 仿 tests/test_action_dispatch.py 的 Stub 模式：
        # __new__ 绕过设备依赖，注入真实 env/operator + 打桩 verifier
        runner = Runner.__new__(Runner)
        runner.env = self.env
        runner.ui = self.operator
        runner.verifier = verifier
        runner._timing = ExecutionTiming()
        runner._last_served = {}
        runner._serve_verify_wait = 0.2
        Runner._build_action_handlers(runner)
        return runner

    def _fill_assembly_for_recipe(self) -> None:
        self.env.assembly.target_recipe_slug = RECIPE
        self.env.assembly.ingredients.append(("clearwater_fish", "skillet", 0.0))
        self.env.assembly.condiments["hearthspice"] = 1

    def _dispatch(self, runner: Runner, actions: list) -> None:
        with mock.patch("airtest.core.api.swipe"), \
                mock.patch("hawarma.game.runner.G"):
            asyncio.run(Runner.dispatch_batch(runner, actions))

    def test_success_and_failure_serve_paths_record_all_segments(self):
        # ── 路径 A：cook swipe + 一次验证成功 ──
        self.env.add_order(RECIPE, is_rush=False)
        self._fill_assembly_for_recipe()
        runner_ok = self._make_runner(_StubVerifier(is_empty=True))
        self._dispatch(runner_ok, [
            CookAction("clearwater_fish", "skillet", 4.0, priority=1),
            ServeOrderAction(slot_idx=0, priority=5),
        ])
        # serve 成功：订单被记分并移出槽位
        self.assertEqual(self.env.get_stats()["orders_served"], 1)

        # ── 路径 B：验证两次失败 → 左侧重试 → 丢弃清理（slot 1 有左侧可重试）──
        runner_fail = self._make_runner(_StubVerifier(is_empty=False))
        self._dispatch(runner_fail, [ServeOrderAction(slot_idx=1)])

        # ── 基线断言：各分段有记录且数值在宽松合理区间 ──
        expected_counts = {
            "swipe": 2,               # 路径 A cook+serve；路径 B 至少一次 serve swipe
            "serve_verify_wait": 2,   # 两条路径各一次首验等待
            "serve_verify_snapshot": 2,  # 两条路径各一次首验截图（重试段计时归 serve_retry）
            "serve_retry": 1,         # B 的一次左侧重试
            "serve_cleanup": 1,       # B 的丢弃清理
        }
        combined: dict[str, dict] = {}
        for runner in (runner_ok, runner_fail):
            for name, seg in runner._collect_timing().items():
                combined.setdefault(name, {"count": 0, "total": 0.0})
                combined[name]["count"] += seg["count"]
                combined[name]["total"] += seg["total"]

        self.assertEqual(
            set(combined),
            {"swipe", "serve_verify_wait", "serve_verify_snapshot",
             "serve_retry", "serve_cleanup"},
        )
        for name, min_count in expected_counts.items():
            self.assertGreaterEqual(
                combined[name]["count"], min_count,
                msg=f"segment {name} not recorded enough",
            )
            self.assertGreaterEqual(combined[name]["total"], 0.0)
            self.assertLess(combined[name]["total"], SANE_UPPER_BOUND,
                            msg=f"segment {name} out of sane range")

        # 逐段单独校验（存在性 + 合理区间，不设阈值）
        for runner in (runner_ok, runner_fail):
            for name, seg in runner._collect_timing().items():
                self.assertTrue({"count", "total", "avg", "max"} <= set(seg))
                if seg["count"] > 0:
                    self.assertGreater(seg["avg"], 0.0, msg=f"{name}.avg")
                    self.assertLess(seg["avg"], SANE_UPPER_BOUND, msg=f"{name}.avg")
                    self.assertLess(seg["max"], SANE_UPPER_BOUND, msg=f"{name}.max")
                    self.assertLessEqual(seg["avg"], seg["max"], msg=f"{name}")


if __name__ == "__main__":
    unittest.main()
