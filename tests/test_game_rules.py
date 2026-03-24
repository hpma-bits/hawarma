"""
游戏规则验证 playground

地位：模拟游戏交互环境，验证 Executor 输出的 swipe 序列和 game_state
      是否违反游戏规则。不关心功能侧如何实现，接口对齐即可。

输入：文本订单检测（MockDetectionService）
输出：规则验证结果、性能指标

硬规则（违反即失败）：
  R1 组装站互斥 — 同一时刻 assembly 只服务一个订单
  R2 库存上限 5 — 每种食材库存不超过 5 份
  R3 灶台过期清理 — 食材在灶台最多停留 5 秒，之后需移至垃圾桶
  R4 动画窗口禁操作 — FinishOrder 后 1.5s 内不产出新 swipe
  R5 swipe 坐标合法 — 起点/终点必须是游戏元素位置
  R6 送餐目的地与当前 slot 一致 — assembly→pickup 终点 = pickup_stations[订单当前 slot]

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新
"""

import asyncio
import sys
import time
import types
import unittest
from dataclasses import dataclass

# Stub airtest before importing hawarma modules (airtest not available in test env)
if "airtest" not in sys.modules:
    _airtest = types.ModuleType("airtest")
    _airtest_core = types.ModuleType("airtest.core")
    _airtest_core_api = types.ModuleType("airtest.core.api")
    _airtest_core_cv = types.ModuleType("airtest.core.cv")
    _airtest_aircv = types.ModuleType("airtest.aircv")
    _airtest_core_api.G = type("G", (), {"DEVICE": None})()
    _airtest_core_api.Template = type("Template", (), {})
    _airtest_core_api.swipe = lambda *a, **kw: None
    _airtest_core_cv.Template = type("Template", (), {})
    _airtest_core_cv.ST = {}
    _airtest_core_cv.MATCHING_METHODS = {}
    _airtest_core_cv.InvalidMatchingMethodError = type(
        "InvalidMatchingMethodError", (Exception,), {}
    )
    _airtest_aircv.crop_image = lambda *a, **kw: None
    sys.modules["airtest"] = _airtest
    sys.modules["airtest.core"] = _airtest_core
    sys.modules["airtest.core.api"] = _airtest_core_api
    sys.modules["airtest.core.cv"] = _airtest_core_cv
    sys.modules["airtest.aircv"] = _airtest_aircv

from loguru import logger

from hawarma.models import Order, OrderStage, Recipe
from hawarma.scheduler import Scheduler
from hawarma.services.executor import Executor
from hawarma.services.resource_guards import ResourceGuards
from hawarma.state import (
    GameState,
    SessionState,
    init_game_state,
    init_session_state,
    reset_global_state,
)
from tests.fixtures.test_recipes import (
    TEST_RECIPES,
    create_test_order,
    reset_order_counter,
)
from tests.mocks import MockDetectionService, MockUIOperationManager, ScheduledOrder


# ============================================================================
# 规则验证器
# ============================================================================


@dataclass
class RuleViolation:
    """单条规则违反记录"""

    rule: str
    description: str
    timestamp: float | None = None


class GameRuleValidator:
    """
    游戏规则验证器。

    对 game_state 和 mock_ui.operations 进行事后检查，
    判断游戏过程中是否违反了硬规则。
    """

    TRASH_POS = (130, 560)

    def __init__(
        self,
        game_state: GameState,
        mock_ui: MockUIOperationManager,
        valid_elements: set[tuple[int, int]],
        stockpile_positions: list[tuple[int, int]],
        pickup_positions: list[tuple[int, int]],
        assembly_pos: tuple[int, int],
    ):
        self.game_state = game_state
        self.mock_ui = mock_ui
        self.valid_elements = valid_elements
        self.stockpile_positions = stockpile_positions
        self.pickup_positions = pickup_positions
        self.assembly_pos = assembly_pos

    def check_all(self, r6_violations: list[RuleViolation] | None = None) -> list[RuleViolation]:
        """执行全部规则检查，返回违反列表"""
        violations = []
        violations.extend(self.check_valid_swipe_coordinates())
        violations.extend(self.check_assembly_mutual_exclusion())
        violations.extend(self.check_stockpile_limit())
        violations.extend(self.check_cooker_retention())
        violations.extend(self.check_animation_window())
        # R6 使用实时 tracker，通过 r6_violations 传入
        if r6_violations:
            violations.extend(r6_violations)
        return violations

    # ------------------------------------------------------------------
    # R5: swipe 坐标合法
    # ------------------------------------------------------------------

    def check_valid_swipe_coordinates(self) -> list[RuleViolation]:
        """检查每个 swipe 的起点和终点是否对应游戏元素"""
        violations = []
        for op in self.mock_ui.operations:
            if op.type != "swipe":
                continue
            if op.start not in self.valid_elements:
                violations.append(
                    RuleViolation("R5", f"Invalid swipe start: {op.start}", op.timestamp)
                )
            if op.end not in self.valid_elements:
                violations.append(
                    RuleViolation("R5", f"Invalid swipe end: {op.end}", op.timestamp)
                )
        return violations

    # ------------------------------------------------------------------
    # R1: 组装站互斥
    # ------------------------------------------------------------------

    def check_assembly_mutual_exclusion(self) -> list[RuleViolation]:
        """
        检查组装站是否被多个订单同时使用。

        通过 swipe 序列推断 assembly 归属：
        - 食材/调料 swipe 到 assembly → 设置 owner
        - assembly → pickup swipe → 释放 owner
        - 不同订单的食材连续到达 assembly（中间无 Finish）→ 违反
        """
        violations = []
        current_owner: int | None = None

        for op in self.mock_ui.operations:
            if op.type != "swipe":
                continue

            if op.end == self.assembly_pos:
                # 食材或调料到达 assembly
                owner = self.game_state.assembly.owner_order_id
                if (
                    owner is not None
                    and current_owner is not None
                    and owner != current_owner
                ):
                    violations.append(
                        RuleViolation(
                            "R1",
                            f"Assembly conflict: order {owner} sends ingredient "
                            f"while order {current_owner} still owns assembly",
                            op.timestamp,
                        )
                    )
                if owner is not None:
                    current_owner = owner

            elif op.start == self.assembly_pos and op.end in self.pickup_positions:
                # FinishOrder: assembly → pickup，释放归属
                current_owner = None

        return violations

    # ------------------------------------------------------------------
    # R2: 库存上限 5
    # ------------------------------------------------------------------

    def check_stockpile_limit(self) -> list[RuleViolation]:
        """检查库存计数是否超过 5"""
        violations = []
        for ingredient, count in self.game_state.stockpile_counts.items():
            if count > 5:
                violations.append(
                    RuleViolation(
                        "R2",
                        f"Stockpile overflow: {ingredient} count={count} (max 5)",
                    )
                )
        return violations

    # ------------------------------------------------------------------
    # R3: 灶台过期清理
    # ------------------------------------------------------------------

    def check_cooker_retention(self) -> list[RuleViolation]:
        """检查是否有灶台食材超过 5 秒保留期未清理"""
        violations = []
        now = time.monotonic()
        overdue = self.game_state.get_overdue_cookers(now)
        for cooker_name, cooker_state in overdue:
            violations.append(
                RuleViolation(
                    "R3",
                    f"Cooker overdue: {cooker_name} has '{cooker_state.ingredient_name}' "
                    f"past clear_by "
                    f"(clear_by={cooker_state.clear_by:.2f}, now={now:.2f})",
                )
            )
        return violations

    # ------------------------------------------------------------------
    # R6: 送餐目的地与当前 slot 一致
    # ------------------------------------------------------------------

    def check_pickup_slot_correctness(self) -> list[RuleViolation]:
        """
        检查每次 assembly→pickup swipe 的终点是否等于
        pickup_stations[该订单在 game_state 中的当前 slot]。

        游戏规则（§2.4）：订单完成后 slot 左移，pickup station 跟随左移。
        如果 pickup_slot 在位移前就已确定，可能导致送餐目标错误。
        """
        violations = []

        for op in self.mock_ui.operations:
            if op.type != "swipe":
                continue
            if op.start != self.assembly_pos:
                continue
            if op.end not in self.pickup_positions:
                continue

            # 这是一个 assembly→pickup swipe
            owner_id = self.game_state.assembly.owner_order_id
            if owner_id is None:
                violations.append(
                    RuleViolation(
                        "R6",
                        f"Assembly→pickup swipe but no assembly owner",
                        op.timestamp,
                    )
                )
                continue

            slot_idx = self.game_state.get_order_slot_index_by_id(owner_id)
            if slot_idx < 0:
                violations.append(
                    RuleViolation(
                        "R6",
                        f"Assembly→pickup for order {owner_id} "
                        f"but order not found in slots",
                        op.timestamp,
                    )
                )
                continue

            expected_pos = self.pickup_positions[slot_idx]
            if op.end != expected_pos:
                violations.append(
                    RuleViolation(
                        "R6",
                        f"Wrong pickup target: order {owner_id} in slot {slot_idx} "
                        f"swiped to {op.end}, expected {expected_pos}",
                        op.timestamp,
                    )
                )

        return violations

    # ------------------------------------------------------------------
    # R4: 动画窗口禁操作
    # ------------------------------------------------------------------

    def check_animation_window(self) -> list[RuleViolation]:
        """
        检查动画窗口内是否有新的 serve swipe（assembly→pickup）。
        其他操作（cook、move、season）在动画窗口内是允许的。
        """
        violations = []
        finish_timestamps: list[float] = []

        for op in self.mock_ui.operations:
            if op.type != "swipe":
                continue
            if op.start == self.assembly_pos and op.end in self.pickup_positions:
                finish_timestamps.append(op.timestamp)

        for finish_ts in finish_timestamps:
            for op in self.mock_ui.operations:
                if op.type != "swipe":
                    continue
                if op.timestamp <= finish_ts:
                    continue
                if op.timestamp <= finish_ts + 1.5:
                    # 只检查 serve swipe（assembly→pickup）
                    if op.start == self.assembly_pos and op.end in self.pickup_positions:
                        violations.append(
                            RuleViolation(
                                "R4",
                                f"Serve during animation window: {op} at "
                                f"{op.timestamp:.2f}s "
                                f"(until {finish_ts + 1.5:.2f}s)",
                                op.timestamp,
                            )
                        )

        return violations


# ============================================================================
# 模拟运行器
# ============================================================================


@dataclass
class SimulationResult:
    """模拟结果"""

    scenario_name: str
    total_duration: float
    orders_completed: int
    orders_failed: int
    game_state: GameState
    mock_ui: MockUIOperationManager
    r6_violations: list[RuleViolation]


class _AssemblyTracker:
    """
    实时跟踪 assembly 归属，检查送餐目的地是否正确。

    在每次 swipe 后调用 track()，根据 swipe 的起点/终点推断
    assembly 归属变化和送餐目标是否正确。
    """

    def __init__(
        self,
        game_state: GameState,
        assembly_pos: tuple[int, int],
        pickup_positions: list[tuple[int, int]],
    ):
        self.game_state = game_state
        self.assembly_pos = assembly_pos
        self.pickup_positions = pickup_positions
        self.violations: list[RuleViolation] = []
        self._current_owner: int | None = None

    def track(self, op) -> None:
        """每次 swipe 后调用，更新归属并检查送餐目标"""
        if op.type != "swipe":
            return

        if op.end == self.assembly_pos:
            # 食材/调料到达 assembly
            if self._current_owner is None:
                owner = self.game_state.assembly.owner_order_id
                if owner is not None:
                    self._current_owner = owner

        elif op.start == self.assembly_pos and op.end in self.pickup_positions:
            # 送餐：assembly → pickup
            if self._current_owner is not None:
                slot = self.game_state.get_order_slot_index_by_id(
                    self._current_owner
                )
                if slot >= 0:
                    expected = self.pickup_positions[slot]
                    if op.end != expected:
                        self.violations.append(
                            RuleViolation(
                                "R6",
                                f"Wrong pickup: order {self._current_owner} "
                                f"in slot {slot}, "
                                f"swiped to {op.end}, expected {expected}",
                                op.timestamp,
                            )
                        )
                    # Debug: always log for analysis
                    logger.debug(
                        f"R6 check: order {self._current_owner} in slot {slot}, "
                        f"swiped to {op.end}, expected {expected}, "
                        f"match={op.end == expected}"
                    )
            else:
                logger.debug(
                    f"R6: assembly→pickup but no tracked owner"
                )
            self._current_owner = None


class ScenarioRunner:
    """
    游戏模拟运行器。

    喂入订单、运行 tick 循环、收集 swipe 输出和 game_state。
    不关心 Scheduler/Executor 内部如何实现。
    """

    def __init__(
        self,
        scenario_name: str,
        recipes: list[Recipe],
        order_schedule: list[ScheduledOrder],
        tick_interval: float = 0.05,
        max_duration: float = 30.0,
    ):
        self.scenario_name = scenario_name
        self.recipes = recipes
        self.order_schedule = order_schedule
        self.tick_interval = tick_interval
        self.max_duration = max_duration

        self.game_state: GameState | None = None
        self.mock_ui: MockUIOperationManager | None = None
        self.mock_detection: MockDetectionService | None = None
        self.executor: Executor | None = None
        self.scheduler: Scheduler | None = None

        self._valid_elements: set[tuple[int, int]] = set()
        self._stockpile_positions: list[tuple[int, int]] = []
        self._pickup_positions: list[tuple[int, int]] = []
        self._assembly_pos: tuple[int, int] = (0, 0)
        self._tracker: _AssemblyTracker | None = None
        self._manual_orders: dict[float, list[tuple[int, Order]]] = {}

    def inject_order(self, slot_idx: int, order: Order, appear_at: float) -> None:
        """
        手动注入订单到指定 slot，不依赖 MockDetectionService。

        用于测试间隙场景（如 orders=[slot0, slot2]）。
        """
        if appear_at not in self._manual_orders:
            self._manual_orders[appear_at] = []
        self._manual_orders[appear_at].append((slot_idx, order))

    def setup(self) -> None:
        """初始化游戏环境"""
        reset_global_state()
        reset_order_counter()

        all_cookers = []
        for recipe in self.recipes:
            for cooker in recipe.cookers_layout:
                if cooker not in all_cookers:
                    all_cookers.append(cooker)

        self.game_state = init_game_state(all_cookers)
        session_state = init_session_state(self.recipes)

        self.mock_ui = MockUIOperationManager(simulate_delay=False, swipe_delay=0.0)
        self.mock_detection = MockDetectionService(schedule=self.order_schedule)

        guards = ResourceGuards(cookers=all_cookers, stockpile_slot_count=3)

        # 构建位置映射
        all_ingredients = []
        for recipe in self.recipes:
            for ing in recipe.raw_ingredients:
                if ing not in all_ingredients:
                    all_ingredients.append(ing)

        all_condiments = []
        for recipe in self.recipes:
            for cond in recipe.condiments:
                if cond not in all_condiments:
                    all_condiments.append(cond)

        cookers_mapping = {
            c: (100, 200 + i * 100) for i, c in enumerate(all_cookers)
        }
        raw_ingredients_mapping = {
            ing: (50, 100 + i * 50) for i, ing in enumerate(all_ingredients)
        }
        condiments_mapping = {
            cond: (150, 100 + i * 50) for i, cond in enumerate(all_condiments)
        }
        self._assembly_pos = (500, 300)
        self._stockpile_positions = [(300, 100), (300, 200), (300, 300)]
        self._pickup_positions = [(700, 100), (700, 200), (700, 300), (700, 400)]

        self.executor = Executor(
            game_state=self.game_state,
            session_state=session_state,
            raw_ingredients_mapping=raw_ingredients_mapping,
            cookers_mapping=cookers_mapping,
            condiments_mapping=condiments_mapping,
            assembly_station_pos=self._assembly_pos,
            pickup_stations_pos=self._pickup_positions,
            stockpile_positions=self._stockpile_positions,
            ui_manager=self.mock_ui,
            guards=guards,
            ordered_recipes=self.recipes,
        )
        self.scheduler = Scheduler(self.game_state, session_state)

        # R6 实时追踪器
        self._tracker = _AssemblyTracker(
            self.game_state, self._assembly_pos, self._pickup_positions
        )

        # 收集所有合法游戏元素坐标
        self._valid_elements = set()
        self._valid_elements.update(raw_ingredients_mapping.values())
        self._valid_elements.update(cookers_mapping.values())
        self._valid_elements.update(condiments_mapping.values())
        self._valid_elements.add(self._assembly_pos)
        self._valid_elements.update(self._stockpile_positions)
        self._valid_elements.update(self._pickup_positions)
        self._valid_elements.add((130, 560))  # 垃圾桶

    async def run(self) -> SimulationResult:
        """运行模拟"""
        self.setup()
        start_time = asyncio.get_event_loop().time()

        logger.info(f"=== Starting scenario: {self.scenario_name} ===")

        try:
            while True:
                now = asyncio.get_event_loop().time()
                elapsed = now - start_time

                if elapsed > self.max_duration:
                    logger.warning(f"Scenario timed out at {elapsed:.2f}s")
                    break

                if self._all_orders_completed():
                    logger.info(f"All orders completed at {elapsed:.2f}s")
                    break

                self.mock_detection.set_time(elapsed)

                # 手动注入订单
                for appear_at, orders in self._manual_orders.items():
                    if elapsed >= appear_at:
                        for slot_idx, order in orders:
                            async with self.game_state.lock:
                                if self.game_state.orders[slot_idx] is None:
                                    self.game_state.orders[slot_idx] = order
                                    logger.info(
                                        f"Injected order in slot {slot_idx}: "
                                        f"{order.recipe.name}"
                                    )
                        # 清除已注入的批次
                        self._manual_orders[appear_at] = []
                self._manual_orders = {
                    k: v for k, v in self._manual_orders.items() if v
                }

                # 扫描新订单（MockDetectionService）
                for slot_idx in range(4):
                    async with self.game_state.lock:
                        if self.game_state.orders[slot_idx] is not None:
                            continue
                    order = self.mock_detection.detect_order(slot_idx)
                    if order:
                        async with self.game_state.lock:
                            if self.game_state.orders[slot_idx] is None:
                                self.game_state.orders[slot_idx] = order
                                logger.info(
                                    f"New order in slot {slot_idx}: "
                                    f"{order.recipe.name}"
                                )

                # tick: 调度 + 执行
                async with self.game_state.lock:
                    actions = self.scheduler.get_next_actions()

                if actions:
                    await self.executor.execute_batch(actions)
                    # R6: 追踪最新的 swipe
                    if self.mock_ui.operations:
                        self._tracker.track(self.mock_ui.operations[-1])

                await asyncio.sleep(self.tick_interval)

        except Exception as e:
            logger.exception(f"Scenario failed: {e}")
            raise

        now = asyncio.get_event_loop().time()
        completed = self.game_state.completed_orders_count

        return SimulationResult(
            scenario_name=self.scenario_name,
            total_duration=now - start_time,
            orders_completed=completed,
            orders_failed=sum(
                1 for o in self.game_state.orders if o is not None and not o.done
            ),
            game_state=self.game_state,
            mock_ui=self.mock_ui,
            r6_violations=self._tracker.violations,
        )

    def _all_orders_completed(self) -> bool:
        # 还有手动订单未注入
        if self._manual_orders:
            return False

        pending = self.mock_detection.get_pending_orders()
        if pending:
            return False

        for order in self.game_state.orders:
            if order is not None and not order.done:
                return False

        all_scheduled = self.mock_detection.get_all_scheduled_orders()
        detected_count = self.mock_detection.get_detection_count()

        # 有检测源但均未开始 → 还没开始
        if all_scheduled and detected_count == 0:
            return False

        # 无任何订单来源 → 视为完成
        if not all_scheduled and detected_count == 0:
            # 有已完成订单才视为完成
            return self.game_state.completed_orders_count > 0

        return True

    def create_validator(self) -> GameRuleValidator:
        """创建规则验证器"""
        return GameRuleValidator(
            game_state=self.game_state,
            mock_ui=self.mock_ui,
            valid_elements=self._valid_elements,
            stockpile_positions=self._stockpile_positions,
            pickup_positions=self._pickup_positions,
            assembly_pos=self._assembly_pos,
        )


# ============================================================================
# 场景工厂
# ============================================================================


def create_single_order_scenario():
    order = create_test_order("braised_fish", is_rush=False)
    return (
        "single_order_basic",
        [TEST_RECIPES["braised_fish"]],
        [ScheduledOrder(slot_idx=0, order=order, appear_at=0.0)],
        1,
    )


def create_two_order_scenario():
    order1 = create_test_order("braised_fish", is_rush=False)
    order2 = create_test_order("hearty_pie", is_rush=False)
    return (
        "two_orders_concurrent",
        [TEST_RECIPES["braised_fish"], TEST_RECIPES["hearty_pie"]],
        [
            ScheduledOrder(slot_idx=0, order=order1, appear_at=0.0),
            ScheduledOrder(slot_idx=1, order=order2, appear_at=0.5),
        ],
        2,
    )


def create_rush_order_scenario():
    normal_order = create_test_order("tomahawk", is_rush=False)
    rush_order = create_test_order("braised_fish", is_rush=True)
    return (
        "rush_order_preemption",
        [TEST_RECIPES["tomahawk"], TEST_RECIPES["braised_fish"]],
        [
            ScheduledOrder(slot_idx=0, order=normal_order, appear_at=0.0),
            ScheduledOrder(slot_idx=1, order=rush_order, appear_at=1.0),
        ],
        2,
    )


def create_multi_order_scenario():
    orders = [
        create_test_order("braised_fish", is_rush=False),
        create_test_order("hearty_pie", is_rush=False),
        create_test_order("saltbaked_shrimp", is_rush=False),
        create_test_order("risotto", is_rush=False),
    ]
    return (
        "four_orders_full_load",
        [
            TEST_RECIPES["braised_fish"],
            TEST_RECIPES["hearty_pie"],
            TEST_RECIPES["saltbaked_shrimp"],
            TEST_RECIPES["risotto"],
        ],
        [
            ScheduledOrder(slot_idx=i, order=orders[i], appear_at=i * 0.5)
            for i in range(4)
        ],
        4,
    )


def create_gap_scenario():
    """
    间隙场景：orders 在 slot 0 和 slot 2，slot 1 为空。

    用于测试 advance_slots() 后 pickup 目标是否正确（R6）。
    完成 slot 0 后，slot 2 的订单应位移到 slot 0，
    其送餐目标应变为 pickup[0] 而非 pickup[2]。
    """
    order1 = create_test_order("braised_fish", is_rush=False)
    order2 = create_test_order("hearty_pie", is_rush=False)
    return (
        "gap_slot_shift",
        [TEST_RECIPES["braised_fish"], TEST_RECIPES["hearty_pie"]],
        [],  # 不用 MockDetectionService，手动注入
        2,
    )


# ============================================================================
# 测试：逐条规则验证
# ============================================================================


class TestGameRuleValidation(unittest.TestCase):
    """逐条验证游戏规则"""

    def _run_scenario(self, scenario_fn) -> tuple[SimulationResult, GameRuleValidator]:
        name, recipes, schedule, _ = scenario_fn()
        runner = ScenarioRunner(name, recipes, schedule, max_duration=30.0)
        result = asyncio.run(runner.run())
        return result, runner.create_validator()

    # ---- R5: swipe 坐标合法 ----

    def test_r5_single_order_swipe_coordinates(self):
        """R5: 单订单所有 swipe 坐标合法"""
        result, validator = self._run_scenario(create_single_order_scenario)

        print(f"\n--- Swipe timeline ({result.scenario_name}) ---")
        for op in result.mock_ui.operations:
            print(f"  {op}")

        violations = validator.check_valid_swipe_coordinates()
        self.assertEqual(
            len(violations), 0,
            f"R5 violations:\n"
            + "\n".join(f"  {v.description}" for v in violations),
        )

    def test_r5_multi_order_swipe_coordinates(self):
        """R5: 多订单所有 swipe 坐标合法"""
        result, validator = self._run_scenario(create_two_order_scenario)
        violations = validator.check_valid_swipe_coordinates()
        self.assertEqual(
            len(violations), 0,
            f"R5 violations:\n"
            + "\n".join(f"  {v.description}" for v in violations),
        )

    # ---- R1: 组装站互斥 ----

    def test_r1_assembly_mutual_exclusion(self):
        """R1: 两个订单共享组装站时不应冲突"""
        result, validator = self._run_scenario(create_two_order_scenario)
        violations = validator.check_assembly_mutual_exclusion()
        self.assertEqual(
            len(violations), 0,
            f"R1 violations:\n"
            + "\n".join(f"  {v.description}" for v in violations),
        )

    # ---- R2: 库存上限 ----

    def test_r2_stockpile_limit(self):
        """R2: 正常场景下库存不应超过 5"""
        result, validator = self._run_scenario(create_single_order_scenario)
        violations = validator.check_stockpile_limit()
        self.assertEqual(
            len(violations), 0,
            f"R2 violations:\n"
            + "\n".join(f"  {v.description}" for v in violations),
        )

    def test_r2_no_upper_bound_guard(self):
        """
        R2: increment_stock 无上限保护。

        预期失败：当前 increment_stock 允许超过 5。
        """
        result, _ = self._run_scenario(create_single_order_scenario)

        result.game_state.increment_stock("test_ing", amount=10)
        count = result.game_state.get_stock_count("test_ing")

        self.assertLessEqual(
            count, 5,
            f"R2 not enforced: increment_stock allowed count={count}, limit is 5",
        )

    # ---- R3: 灶台过期清理 ----

    def test_r3_cooker_retention(self):
        """R3: 正常场景下灶台不应有食材过期"""
        result, validator = self._run_scenario(create_single_order_scenario)
        violations = validator.check_cooker_retention()
        self.assertEqual(
            len(violations), 0,
            f"R3 violations:\n"
            + "\n".join(f"  {v.description}" for v in violations),
        )

    def test_r3_no_cleanup_triggered(self):
        """
        R3: 系统检测到过期灶台但不清理。

        预期失败：get_overdue_cookers 能检测但无清理逻辑。
        """
        result, _ = self._run_scenario(create_single_order_scenario)

        now = time.monotonic()
        cooker_names = list(result.game_state.cookers.keys())
        cooker = result.game_state.cookers[cooker_names[0]]
        cooker.busy = True
        cooker.ingredient_name = "stuck_ingredient"
        cooker.clear_by = now - 1.0

        overdue = result.game_state.get_overdue_cookers(now)
        self.assertEqual(
            len(overdue), 0,
            f"R3 not enforced: {len(overdue)} cooker(s) overdue but "
            f"no cleanup mechanism triggered",
        )

    # ---- R4: 动画窗口 ----

    def test_r4_animation_window(self):
        """R4: FinishOrder 后 1.5s 内不应有新 swipe"""
        result, validator = self._run_scenario(create_single_order_scenario)

        print(f"\n--- Animation window check ---")
        for op in result.mock_ui.operations:
            print(f"  {op}")

        violations = validator.check_animation_window()
        self.assertEqual(
            len(violations), 0,
            f"R4 violations:\n"
            + "\n".join(f"  {v.description}" for v in violations),
        )

    # ---- R6: 送餐目的地与当前 slot 一致 ----

    def test_r6_pickup_slot_single_order(self):
        """R6: 单订单送餐到正确的 pickup station"""
        result, _ = self._run_scenario(create_single_order_scenario)

        self.assertEqual(
            len(result.r6_violations), 0,
            f"R6 violations:\n"
            + "\n".join(f"  {v.description}" for v in result.r6_violations),
        )

    def test_r6_pickup_slot_multi_order(self):
        """
        R6: 多订单按顺序完成时，每次送餐到正确的 pickup station。

        场景：4 个订单在 slots [0,1,2,3]，按顺序完成。
        验证：每次 assembly→pickup 的终点对应订单完成时的当前 slot。
        """
        result, _ = self._run_scenario(create_multi_order_scenario)

        print(f"\n--- Pickup slot check ({result.scenario_name}) ---")
        for op in result.mock_ui.operations:
            if op.type == "swipe" and op.start == (500, 300):
                print(f"  Serve swipe: {op}")

        self.assertEqual(
            len(result.r6_violations), 0,
            f"R6 violations:\n"
            + "\n".join(f"  {v.description}" for v in result.r6_violations),
        )

    def test_r6_pickup_slot_after_slot_shift(self):
        """
        R6: 完成 slot 0 后，slot 2 的订单位移到 slot 0，送餐目标应变为 pickup[0]。

        场景：orders 在 slot 0 和 slot 2（slot 1 为空）。
        完成 slot 0 → advance_slots → slot 2 位移到 slot 0。
        第二个订单的 assembly→pickup 应指向 pickup[0]，而非 pickup[2]。

        预期失败：当前 pickup_slot 在调度时确定，不随位移更新。
        """
        name, recipes, schedule, expected = create_gap_scenario()
        runner = ScenarioRunner(name, recipes, schedule, max_duration=30.0)

        # 手动注入订单，制造间隙
        order1 = create_test_order("braised_fish", is_rush=False)
        order2 = create_test_order("hearty_pie", is_rush=False)
        runner.inject_order(0, order1, appear_at=0.0)
        runner.inject_order(2, order2, appear_at=0.0)

        result = asyncio.run(runner.run())

        print(f"\n--- R6 gap scenario ---")
        for op in result.mock_ui.operations:
            if op.type == "swipe":
                print(f"  {op}")
        print(f"  Violations: {len(result.r6_violations)}")
        for v in result.r6_violations:
            print(f"    [{v.rule}] {v.description}")

        # 检查 slot 位移是否发生
        order2_slot = result.game_state.get_order_slot_index_by_id(order2.order_id)
        print(f"  Order 2 final slot: {order2_slot}")

        self.assertEqual(
            result.orders_completed, expected,
            f"Expected {expected} orders completed, got {result.orders_completed}",
        )

        self.assertEqual(
            len(result.r6_violations), 0,
            f"R6 violations (pickup slot not updated after shift):\n"
            + "\n".join(f"  {v.description}" for v in result.r6_violations),
        )


# ============================================================================
# 测试：集成场景
# ============================================================================


class TestScenarios(unittest.TestCase):
    """运行各场景，验证基本功能和全部规则"""

    def _run_and_validate(self, scenario_fn) -> SimulationResult:
        name, recipes, schedule, expected = scenario_fn()
        runner = ScenarioRunner(name, recipes, schedule, max_duration=30.0)
        result = asyncio.run(runner.run())
        validator = runner.create_validator()

        print(f"\n=== {name} ===")
        print(f"  Duration: {result.total_duration:.2f}s")
        print(f"  Completed: {result.orders_completed}/{expected}")
        print(f"  Swipes: {len(result.mock_ui.operations)}")

        self.assertEqual(
            result.orders_completed, expected,
            f"Expected {expected} orders completed, got {result.orders_completed}",
        )

        violations = validator.check_all(r6_violations=result.r6_violations)
        for v in violations:
            print(f"  [{v.rule}] {v.description}")
        self.assertEqual(
            len(violations), 0,
            f"Game rule violations:\n"
            + "\n".join(f"  [{v.rule}] {v.description}" for v in violations),
        )

        return result

    def test_single_order(self):
        """单订单基础流程"""
        self._run_and_validate(create_single_order_scenario)

    def test_two_orders_concurrent(self):
        """双订单并发"""
        self._run_and_validate(create_two_order_scenario)

    def test_rush_order(self):
        """Rush Order 插队"""
        self._run_and_validate(create_rush_order_scenario)

    def test_four_orders_full_load(self):
        """4 订单满载"""
        self._run_and_validate(create_multi_order_scenario)


# ============================================================================
# 测试：性能基准
# ============================================================================


class TestPerformanceBenchmark(unittest.TestCase):
    """运行所有场景并输出性能报告"""

    def test_benchmark_all_scenarios(self):
        scenarios = [
            create_single_order_scenario,
            create_two_order_scenario,
            create_rush_order_scenario,
            create_multi_order_scenario,
        ]

        print("\n" + "=" * 60)
        print("PERFORMANCE BENCHMARK")
        print("=" * 60)

        for scenario_fn in scenarios:
            name, recipes, schedule, expected = scenario_fn()
            runner = ScenarioRunner(name, recipes, schedule, max_duration=60.0)
            result = asyncio.run(runner.run())
            violations = runner.create_validator().check_all()

            print(f"\n{name}")
            print(f"  Duration:        {result.total_duration:.2f}s")
            print(f"  Orders done:     {result.orders_completed}/{expected}")
            print(f"  Swipes:          {len(result.mock_ui.operations)}")
            print(f"  Rule violations: {len(violations)}")

            self.assertGreater(
                result.orders_completed, 0,
                f"{name} should complete at least 1 order",
            )

        print("\n" + "=" * 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
