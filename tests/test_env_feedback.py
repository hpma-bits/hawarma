"""Issue #20 环境反馈闭环测试：动作「先 UI 后 env」的拒绝可见性 + 验证器 fail-closed。

覆盖（验收标准 4）：
- env 拒绝 pull_from_stockpile（空 slot）时：warning 日志 + _agent_wakeup 被 set
- env 拒绝 add_condiment（配方不符）时同样
- env 拒绝 add_to_assembly（配方不符）时同样，且不再 clear_cooker（全有/全无语义）
- env 拒绝 serve_from_cooker 时不再打误导性的成功 info
- Verifier 模板缺失路径返回 False + logger.error；一次性熔断提示类级只打一次
- Verifier snapshot 失败（None / 抛异常）返回 False
- serve 验证失败路径入口：verifier False → 重试 → 清 assembly + warning + wakeup
- 连续 5 次异常触发 error 级摘要日志、第 6 次不再重复；成功一轮后计数复位

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from loguru import logger as loguru_logger

import hawarma.game.runner as runner_module
import hawarma.game.verifier as verifier_module
from hawarma.core.actions import (
    AddCondimentAction,
    CookAction,
    MoveToAssemblyAction,
    PullFromStockpileAction,
    ServeFromCookerAction,
    ServeOrderAction,
)
from hawarma.game.game_env import GameEnv
from hawarma.game.runner import Runner, _ErrorStreak
from hawarma.game.timing import ExecutionTiming
from hawarma.game.verifier import Verifier
from hawarma.recipe import Recipe, Station


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


class _LogSink:
    """loguru 捕获 sink：记录格式化后的消息文本（exception 追加堆栈）"""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def __call__(self, message) -> None:
        self.messages.append(str(message))

    @property
    def text(self) -> str:
        return "\n".join(self.messages)

    def count(self, needle: str) -> int:
        return sum(1 for m in self.messages if needle in m)


class _StubEnv:
    """最小 env 桩：handler 用到的 env 表面 + 可配置状态更新返回值"""

    def __init__(self) -> None:
        self.time = 0.0
        self.orders: list = [None] * 4
        self.cookers: dict = {}
        self.pull_from_stockpile_result = True
        self.add_condiment_result = True
        self.add_to_assembly_result = True
        self.start_cooking_result = True
        self.serve_from_cooker_result = True
        self.clear_cooker_calls: list[str] = []

    def is_game_over(self) -> bool:
        return False

    def pull_from_stockpile(self, slot: str) -> bool:
        return self.pull_from_stockpile_result

    def add_condiment(self, condiment: str) -> bool:
        return self.add_condiment_result

    def add_to_assembly(self, ingredient, cooker, order_id=None, recipe_slug=None) -> bool:
        return self.add_to_assembly_result

    def start_cooking(self, ingredient, cooker, duration) -> bool:
        return self.start_cooking_result

    def serve_from_cooker(self, cooker: str, slot_idx: int) -> bool:
        return self.serve_from_cooker_result

    def clear_cooker(self, cooker: str) -> bool:
        self.clear_cooker_calls.append(cooker)
        return True

    def get_order_by_id(self, order_id):
        return None


def _make_runner(env, ui, **extra) -> Runner:
    """Stub Runner：跳过构造函数依赖，只装配 handler 测试所需属性"""
    runner = Runner.__new__(Runner)
    runner.env = env
    runner.ui = ui
    runner._agent_wakeup = asyncio.Event()
    runner._action_error_streak = _ErrorStreak("Action execution")
    Runner._build_action_handlers(runner)
    for key, value in extra.items():
        setattr(runner, key, value)
    return runner


# ============================================================================
# env 拒绝 → warning + _agent_wakeup
# ============================================================================


class TestEnvRejectionWakesAgent(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sink = _LogSink()
        self.handler_id = loguru_logger.add(self.sink, format="{message}")

    def tearDown(self) -> None:
        loguru_logger.remove(self.handler_id)

    async def test_rejected_pull_from_stockpile_warns_and_wakes_agent(self):
        """env 拒绝 pull（空 slot）：warning 含 action repr + _agent_wakeup set"""
        env = _StubEnv()
        env.pull_from_stockpile_result = False  # 模拟 slot 空
        ui = MagicMock()
        ui.pull_from_stockpile = AsyncMock()
        runner = _make_runner(env, ui)

        await runner._execute_action(
            PullFromStockpileAction(slot="slot0", ingredient="clearwater_fish")
        )

        self.assertGreaterEqual(self.sink.count("Env rejected"), 1)
        self.assertGreaterEqual(self.sink.count("PullFromStockpileAction"), 1)
        self.assertGreaterEqual(self.sink.count("pull_from_stockpile rejected"), 1)
        self.assertTrue(runner._agent_wakeup.is_set())

    async def test_rejected_add_condiment_warns_and_wakes_agent(self):
        """env 拒绝 add_condiment（配方不符）：warning + _agent_wakeup set"""
        env = _StubEnv()
        env.add_condiment_result = False
        ui = MagicMock()
        ui.add_condiment = AsyncMock()
        runner = _make_runner(env, ui)

        await runner._execute_action(AddCondimentAction(condiment="hearthspice"))

        self.assertGreaterEqual(self.sink.count("Env rejected"), 1)
        self.assertGreaterEqual(self.sink.count("add_condiment rejected"), 1)
        self.assertTrue(runner._agent_wakeup.is_set())

    async def test_accepted_pull_is_silent_and_does_not_wake(self):
        """env 接受时不打拒绝 warning、不额外 set wakeup（防误报）"""
        env = _StubEnv()
        ui = MagicMock()
        ui.pull_from_stockpile = AsyncMock()
        runner = _make_runner(env, ui)

        await runner._execute_action(
            PullFromStockpileAction(slot="slot0", ingredient="clearwater_fish")
        )

        self.assertEqual(self.sink.count("Env rejected"), 0)
        self.assertFalse(runner._agent_wakeup.is_set())

    async def test_rejected_move_to_assembly_skips_cooker_clear(self):
        """add_to_assembly 被拒（配方校验失败）：不打成功 info、不 clear_cooker、wakeup set

        clear_cooker 被跳过 = 与 env.move_to_assembly 全有/全无语义对齐：
        env 组装站没收下食材时，灶台状态也保持不变。
        """
        env = _StubEnv()
        env.cookers = {"skillet": SimpleNamespace(item_name="creamfield_rice", busy=True)}
        env.add_to_assembly_result = False
        ui = MagicMock()
        ui.move_to_assembly = AsyncMock()
        runner = _make_runner(env, ui)

        await runner._execute_action(MoveToAssemblyAction(cooker="skillet", order_id=1))

        self.assertGreaterEqual(self.sink.count("Env rejected"), 1)
        self.assertGreaterEqual(self.sink.count("add_to_assembly rejected"), 1)
        self.assertEqual(self.sink.count("-> assembly"), 0)  # 不打成功 info
        self.assertEqual(env.clear_cooker_calls, [])
        self.assertTrue(runner._agent_wakeup.is_set())

    async def test_move_to_assembly_recipe_mismatch_against_real_env(self):
        """真实 GameEnv 配方校验拒绝路径：食材不属于订单配方 → 拒绝且灶台保持忙"""
        recipes = {"gilded": _make_recipe("gilded", ["clearwater_fish"], ["skillet"], [4.0])}
        env = GameEnv(cooker_names=["skillet", "pot"], recipes=recipes)
        env.start_game()
        env.add_order("gilded", is_rush=False)
        self.assertTrue(env.start_cooking("creamfield_rice", "skillet", 0.0))

        ui = MagicMock()
        ui.move_to_assembly = AsyncMock()
        runner = _make_runner(env, ui)

        await runner._execute_action(MoveToAssemblyAction(cooker="skillet", order_id=1))

        self.assertGreaterEqual(self.sink.count("Env rejected"), 1)
        # 被拒后灶台不被 clear：env 仍认为食材在灶台上，交给 agent 重决策
        self.assertTrue(env.cookers["skillet"].busy)
        self.assertEqual(env.cookers["skillet"].item_name, "creamfield_rice")
        self.assertTrue(runner._agent_wakeup.is_set())

    async def test_rejected_serve_from_cooker_no_misleading_success_log(self):
        """serve_from_cooker 被拒：打拒绝 warning，不再打 'Served from' 成功 info"""
        env = _StubEnv()
        env.serve_from_cooker_result = False
        ui = MagicMock()
        ui.serve_from_cooker = AsyncMock()
        runner = _make_runner(env, ui)

        await runner._execute_action(ServeFromCookerAction(cooker="oven", slot_idx=0))

        self.assertGreaterEqual(self.sink.count("Env rejected"), 1)
        self.assertEqual(self.sink.count("Served from"), 0)
        self.assertTrue(runner._agent_wakeup.is_set())


# ============================================================================
# Verifier fail-closed
# ============================================================================


class TestVerifierFailClosed(unittest.TestCase):
    def setUp(self) -> None:
        # 类级熔断提示 flag 复位，保证用例间独立（Issue #20）
        Verifier._template_missing_hint_shown = False
        self.sink = _LogSink()
        self.handler_id = loguru_logger.add(self.sink, format="{message}")

    def tearDown(self) -> None:
        loguru_logger.remove(self.handler_id)
        Verifier._template_missing_hint_shown = False

    def _missing_template_config(self):
        config = MagicMock()
        config.image_directory = tempfile.mkdtemp()  # 空目录 → 模板必然缺失
        config.debug.save_assembly_verify_screenshots = False
        config.debug.screenshot_directory = "logs/order_screenshots"
        config.matching.assembly_threshold = 0.9
        config.screen.assembly_region = (1150, 720, 1600, 1030)
        return config

    def _loaded_template_config(self):
        config = self._missing_template_config()
        config.image_directory = str(Path(__file__).parent.parent / "static" / "img")
        return config

    def test_missing_template_returns_false_with_error(self):
        """模板缺失 → False（fail-closed）+ logger.error，不再 assume empty 当成功"""
        verifier = Verifier(self._missing_template_config())
        self.assertIsNone(verifier._empty_template)

        self.assertFalse(verifier.is_assembly_empty())
        self.assertGreaterEqual(self.sink.count("template not loaded"), 1)
        self.assertGreaterEqual(self.sink.count("failing closed"), 1)

    def test_missing_template_hint_is_class_level_once(self):
        """一次性熔断提示：类级 flag，跨实例只打一次；单行 error 每次仍打"""
        v1 = Verifier(self._missing_template_config())
        v2 = Verifier(self._missing_template_config())

        self.assertFalse(v1.is_assembly_empty())
        self.assertFalse(v2.is_assembly_empty())

        self.assertEqual(self.sink.count("circuit-breaker"), 1)  # 提示只打一次
        self.assertEqual(self.sink.count("template not loaded"), 2)  # error 每次都打

    def test_snapshot_none_returns_false(self):
        """snapshot 返回 None → False + error（fail-closed）"""
        verifier = Verifier(self._loaded_template_config())
        self.assertIsNotNone(verifier._empty_template)

        mock_g = MagicMock()
        mock_g.DEVICE.snapshot.return_value = None
        with patch.object(verifier_module, "G", mock_g):
            self.assertFalse(verifier.is_assembly_empty())
        self.assertGreaterEqual(self.sink.count("failed to take snapshot"), 1)

    def test_snapshot_exception_returns_false(self):
        """snapshot 抛异常 → False + error 带堆栈（fail-closed）"""
        verifier = Verifier(self._loaded_template_config())

        mock_g = MagicMock()
        mock_g.DEVICE.snapshot.side_effect = RuntimeError("device detached")
        with patch.object(verifier_module, "G", mock_g):
            self.assertFalse(verifier.is_assembly_empty())
        self.assertGreaterEqual(self.sink.count("snapshot/match failed"), 1)
        self.assertGreaterEqual(self.sink.count("Traceback"), 1)


# ============================================================================
# serve 验证失败路径入口（fail-closed verifier → 重试 → 清 assembly）
# ============================================================================


class _ServeStubEnv:
    """serve 验证路径用 env 桩"""

    def __init__(self) -> None:
        self.time = 0.0
        self.orders: list = [None] * 4
        self.clear_assembly_calls = 0
        self.assembly = SimpleNamespace(
            ingredients_cookers=[("clearwater_fish", "skillet", 0.0)],
            condiments={},
        )

    def is_game_over(self) -> bool:
        return False

    def clear_assembly(self) -> bool:
        self.clear_assembly_calls += 1
        return True


class TestServeVerifyFailurePath(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sink = _LogSink()
        self.handler_id = loguru_logger.add(self.sink, format="{message}")

    def tearDown(self) -> None:
        loguru_logger.remove(self.handler_id)

    async def test_fail_closed_verifier_drives_retry_then_cleanup(self):
        """verifier 持续 False（模板缺失语义）→ 重试左侧 slot → 双失败清 assembly + warning + wakeup"""
        env = _ServeStubEnv()
        ui = MagicMock()
        ui.serve_order = AsyncMock()
        ui.clear_assembly = AsyncMock()
        verifier = MagicMock()
        verifier.is_assembly_empty = MagicMock(return_value=False)
        runner = _make_runner(
            env,
            ui,
            verifier=verifier,
            _timing=ExecutionTiming(),
            _serve_verify_wait=0.0,
            _last_served={},
            _clock=lambda: 0.0,
        )

        mock_g = MagicMock()
        mock_g.DEVICE.snapshot.return_value = MagicMock()
        with patch.object(runner_module, "G", mock_g):
            await runner._execute_action(ServeOrderAction(slot_idx=1))

        # 原始 slot + 左侧重试各 swipe 一次，验证两次
        self.assertEqual(ui.serve_order.await_count, 2)
        self.assertEqual(verifier.is_assembly_empty.call_count, 2)
        # 双失败 → 清理组装站（UI + env）
        self.assertEqual(ui.clear_assembly.await_count, 1)
        self.assertEqual(env.clear_assembly_calls, 1)
        self.assertGreaterEqual(self.sink.count("Serve verification failed"), 2)
        self.assertGreaterEqual(
            self.sink.count("Serve verification failed, assembly discarded."), 1
        )
        self.assertTrue(runner._agent_wakeup.is_set())


# ============================================================================
# 连续异常计数（Issue #20 验收标准 3/4）
# ============================================================================


class _FailingTimeoutEnv:
    """timeout 循环桩：check 持续抛错，is_game_over 第 7 次起返回 True（跑满 6 轮）"""

    def __init__(self) -> None:
        self.time = 0.0
        self._checks = 0

    def is_game_over(self) -> bool:
        self._checks += 1
        return self._checks > 6

    def check_and_remove_timed_out_orders(self) -> list[int]:
        raise RuntimeError("tick boom")


class TestConsecutiveErrorStreak(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sink = _LogSink()
        self.handler_id = loguru_logger.add(self.sink, format="{message}")

    def tearDown(self) -> None:
        loguru_logger.remove(self.handler_id)

    async def test_handler_streak_summary_at_fifth_no_repeat_then_reset(self):
        """连续 5 次 handler 异常触发一次摘要；第 6 次不重复；成功后复位可再触发"""
        env = _StubEnv()
        ui = MagicMock()
        ui.cook = AsyncMock(side_effect=RuntimeError("device boom"))
        runner = _make_runner(env, ui)
        action = CookAction("clearwater_fish", "skillet", 4.0)

        for _ in range(6):
            await runner._execute_action(action)

        self.assertEqual(self.sink.count("Failed to execute CookAction"), 6)
        # 每次失败都带堆栈（logger.exception）
        failure_msgs = [m for m in self.sink.messages if "Failed to execute" in m]
        self.assertTrue(all("Traceback" in m for m in failure_msgs))
        self.assertTrue(all("RuntimeError" in m for m in failure_msgs))
        # 摘要恰好一次（第 5 次触发，第 6 次不重复刷）
        self.assertEqual(self.sink.count("5 consecutive errors"), 1)
        self.assertGreaterEqual(self.sink.count("loop continues"), 1)

        # 成功一轮 → 复位
        ui.cook.side_effect = None
        await runner._execute_action(action)
        self.assertEqual(self.sink.count("Cooking clearwater_fish"), 1)

        # 复位后再连错 4 次不触发，第 5 次再次触发
        ui.cook.side_effect = RuntimeError("device boom")
        for _ in range(4):
            await runner._execute_action(action)
        self.assertEqual(self.sink.count("5 consecutive errors"), 1)
        await runner._execute_action(action)
        self.assertEqual(self.sink.count("5 consecutive errors"), 2)

    async def test_timeout_loop_streak_summary_and_loop_survives(self):
        """timeout 循环连续 6 轮异常：第 5 轮打一次摘要，循环不终止跑满 6 轮"""
        runner = Runner.__new__(Runner)
        runner.env = _FailingTimeoutEnv()
        runner._running = True
        runner._agent_wakeup = asyncio.Event()
        runner._timeout_error_streak = _ErrorStreak("Timeout loop")

        await runner._timeout_loop()

        self.assertEqual(self.sink.count("Timeout loop error"), 6)
        self.assertEqual(self.sink.count("5 consecutive errors"), 1)
        timeout_msgs = [m for m in self.sink.messages if "Timeout loop error" in m]
        self.assertTrue(all("Traceback" in m for m in timeout_msgs))


if __name__ == "__main__":
    unittest.main()
