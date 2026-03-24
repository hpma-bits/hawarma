"""
性能实验

地位：运行各种场景，记录操作序列和用时，生成实验报告。
      不关心功能侧如何实现，只测量性能指标。

输出：实验报告（控制台 + 可选文件）

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新
"""

import asyncio
import sys
import time
import types
import unittest
from dataclasses import dataclass, field

# Stub airtest
if "airtest" not in sys.modules:
    for _name in [
        "airtest", "airtest.core", "airtest.core.api",
        "airtest.core.cv", "airtest.aircv",
    ]:
        sys.modules[_name] = types.ModuleType(_name)
    sys.modules["airtest.core.api"].G = type("G", (), {"DEVICE": None})()
    sys.modules["airtest.core.api"].Template = type("Template", (), {})
    sys.modules["airtest.core.api"].swipe = lambda *a, **kw: None
    sys.modules["airtest.core.cv"].Template = type("Template", (), {})
    sys.modules["airtest.core.cv"].ST = {}
    sys.modules["airtest.core.cv"].MATCHING_METHODS = {}
    sys.modules["airtest.core.cv"].InvalidMatchingMethodError = type(
        "InvalidMatchingMethodError", (Exception,), {}
    )
    sys.modules["airtest.aircv"].crop_image = lambda *a, **kw: None

from hawarma.state import init_game_state, init_session_state, reset_global_state
from hawarma.services.executor import Executor
from hawarma.services.resource_guards import ResourceGuards
from hawarma.scheduler import Scheduler
from tests.fixtures.test_recipes import TEST_RECIPES, create_test_order, reset_order_counter
from tests.mocks import MockUIOperationManager


# ============================================================================
# 实验结果
# ============================================================================


@dataclass
class SwipeRecord:
    timestamp: float
    start: tuple[int, int]
    end: tuple[int, int]
    action_hint: str = ""  # 人工标注的操作类型


@dataclass
class ExperimentResult:
    name: str
    description: str
    recipes_used: list[str]
    total_swipes: int
    total_time: float  # 模拟器时间（基于 swipe 间隔）
    real_time: float   # 实际墙钟时间
    orders_completed: int
    orders_total: int
    swipes: list[SwipeRecord] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"{'=' * 60}",
            f"实验: {self.name}",
            f"{'=' * 60}",
            f"描述: {self.description}",
            f"配方: {', '.join(self.recipes_used)}",
            f"",
            f"  订单完成:     {self.orders_completed}/{self.orders_total}",
            f"  总 swipe 数:  {self.total_swipes}",
            f"  模拟器时间:   {self.total_time:.2f}s",
            f"  实际耗时:     {self.real_time:.2f}s",
            f"",
            f"  操作时间线:",
        ]

        prev_t = 0
        for s in self.swipes:
            gap = s.timestamp - prev_t
            gap_str = f"(+{gap:.2f}s)" if gap > 0.001 else ""
            lines.append(
                f"    {s.timestamp:7.2f}s  {s.action_hint:20s}  "
                f"{s.start} -> {s.end}  {gap_str}"
            )
            prev_t = s.timestamp

        return "\n".join(lines)


# ============================================================================
# 实验运行器
# ============================================================================


def build_mappings(recipes):
    """构建坐标映射"""
    raw_map = {}
    for r in recipes:
        for ing in r.raw_ingredients:
            if ing not in raw_map:
                raw_map[ing] = (50, 100 + len(raw_map) * 50)

    cooker_map = {
        c: (100, 200 + i * 100)
        for i, c in enumerate(["grill", "oven", "skillet", "pot"])
    }

    cond_map = {}
    for r in recipes:
        for c in r.condiments:
            if c not in cond_map:
                cond_map[c] = (150, 100 + len(cond_map) * 50)

    return raw_map, cooker_map, cond_map


def classify_swipe(start, end, raw_map, cooker_map, cond_map, assembly, pickup):
    """根据坐标推断操作类型"""
    if start in raw_map.values() and end in cooker_map.values():
        return "cook"
    if start in cooker_map.values() and end == assembly:
        return "move_to_assembly"
    if start in cond_map.values() and end == assembly:
        return "add_condiment"
    if start == assembly and end in pickup:
        return "serve"
    if start in cooker_map.values() and end == (130, 560):
        return "clear_to_trash"
    return "unknown"


def run_experiment(
    name: str,
    description: str,
    recipe_names: list[str],
    order_slots: list[int] | None = None,
) -> ExperimentResult:
    """
    运行一个实验。

    Args:
        name: 实验名称
        description: 实验描述
        recipe_names: 使用的配方名列表
        order_slots: 每个配方对应的 slot（默认 0,1,2,...）
    """
    reset_global_state()
    reset_order_counter()

    recipes = [TEST_RECIPES[n] for n in recipe_names]
    if order_slots is None:
        order_slots = list(range(len(recipes)))

    cookers = ["grill", "oven", "skillet", "pot"]
    gs = init_game_state(cookers)
    ss = init_session_state(recipes)
    ui = MockUIOperationManager(simulate_delay=False, swipe_delay=0.0)
    guards = ResourceGuards(cookers=cookers, stockpile_slot_count=3)

    raw_map, cooker_map, cond_map = build_mappings(recipes)
    assembly = (500, 300)
    pickup = [(700, 100), (700, 200), (700, 300), (700, 400)]

    executor = Executor(
        game_state=gs,
        session_state=ss,
        raw_ingredients_mapping=raw_map,
        cookers_mapping=cooker_map,
        condiments_mapping=cond_map,
        assembly_station_pos=assembly,
        pickup_stations_pos=pickup,
        stockpile_positions=[(300, 100), (300, 200), (300, 300)],
        ui_manager=ui,
        guards=guards,
        ordered_recipes=recipes,
    )
    scheduler = Scheduler(gs, ss)

    for i, slot in enumerate(order_slots):
        gs.orders[slot] = create_test_order(recipe_names[i])

    # 运行
    real_t0 = time.monotonic()

    async def run():
        for tick in range(1000):
            now = asyncio.get_event_loop().time()
            async with gs.lock:
                actions = scheduler.get_next_actions()
            if actions:
                await executor.execute_batch(actions)
            if gs.completed_orders_count >= len(recipes):
                return
            await asyncio.sleep(0.05)

    asyncio.run(run())
    real_elapsed = time.monotonic() - real_t0

    # 收集结果
    swipes = []
    for op in ui.operations:
        hint = classify_swipe(op.start, op.end, raw_map, cooker_map, cond_map, assembly, pickup)
        swipes.append(SwipeRecord(
            timestamp=op.timestamp,
            start=op.start,
            end=op.end,
            action_hint=hint,
        ))

    # 模拟器时间 = 最后一个 swipe 的时间（基于 MockUI 记录的 timestamp）
    sim_time = swipes[-1].timestamp if swipes else 0

    return ExperimentResult(
        name=name,
        description=description,
        recipes_used=recipe_names,
        total_swipes=len(swipes),
        total_time=sim_time,
        real_time=real_elapsed,
        orders_completed=gs.completed_orders_count,
        orders_total=len(recipes),
        swipes=swipes,
    )


# ============================================================================
# 实验定义
# ============================================================================


class TestPerformanceExperiments(unittest.TestCase):
    """性能实验"""

    maxDiff = None

    def test_exp_01_single_order(self):
        """实验 1: 单订单基线"""
        result = run_experiment(
            "单订单基线",
            "1 个红烧鱼，测量单订单最小耗时",
            ["braised_fish"],
        )
        print(f"\n{result.summary()}")
        self.assertEqual(result.orders_completed, 1)

    def test_exp_02_two_diff_cookers(self):
        """实验 2: 双订单不同灶台"""
        result = run_experiment(
            "双订单不同灶台",
            "红烧鱼(skillet) + 爱心派(oven)，测量并行烹饪效果",
            ["braised_fish", "hearty_pie"],
        )
        print(f"\n{result.summary()}")
        self.assertEqual(result.orders_completed, 2)

    def test_exp_03_two_same_cooker(self):
        """实验 3: 双订单同灶台"""
        result = run_experiment(
            "双订单同灶台",
            "红烧鱼(skillet) + 盐焗虾(skillet)，测量串行等待",
            ["braised_fish", "saltbaked_shrimp"],
        )
        print(f"\n{result.summary()}")
        self.assertEqual(result.orders_completed, 2)

    def test_exp_04_four_orders(self):
        """实验 4: 四订单满载"""
        result = run_experiment(
            "四订单满载",
            "4 个不同配方，4 个灶台同时开工",
            ["braised_fish", "hearty_pie", "saltbaked_shrimp", "risotto"],
        )
        print(f"\n{result.summary()}")
        self.assertEqual(result.orders_completed, 4)

    def test_exp_05_rush_order(self):
        """实验 5: Rush 订单"""
        result = run_experiment(
            "Rush 订单优先",
            "普通牛排 + 加急红烧鱼，验证 rush 优先处理",
            ["tomahawk", "braised_fish"],
        )
        print(f"\n{result.summary()}")
        self.assertEqual(result.orders_completed, 2)

    def test_exp_06_report(self):
        """实验 6: 综合报告"""
        experiments = [
            ("单订单", ["braised_fish"]),
            ("双订单(不同灶台)", ["braised_fish", "hearty_pie"]),
            ("双订单(同灶台)", ["braised_fish", "saltbaked_shrimp"]),
            ("四订单", ["braised_fish", "hearty_pie", "saltbaked_shrimp", "risotto"]),
        ]

        print(f"\n{'=' * 70}")
        print(f"{'实验':<25} {'配方':<45} {'完成':>4} {'swipe':>6} {'时间':>7}")
        print(f"{'=' * 70}")

        for name, recipe_names in experiments:
            result = run_experiment(name, "", recipe_names)
            recipes_str = "+".join(
                TEST_RECIPES[n].name[:6] for n in recipe_names
            )
            print(
                f"{name:<25} {recipes_str:<45} "
                f"{result.orders_completed:>4}/{len(recipe_names)} "
                f"{result.total_swipes:>6} "
                f"{result.total_time:>6.2f}s"
            )

        print(f"{'=' * 70}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
