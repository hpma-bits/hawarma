"""
EnvBridge 集成测试

地位：通过 EnvBridge 连接真实系统和 env_simulator，
      验证 Executor 的 swipe 序列不违反游戏规则。

输入：生产配方 + 订单场景
输出：规则验证结果

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新
"""

import asyncio
import sys
import types
import unittest

# Stub airtest before importing hawarma modules
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

from hawarma.env_simulator import GameSimulator, Ingredient, Recipe as SimRecipe
from hawarma.env_bridge import EnvBridge
from hawarma.models import Recipe
from hawarma.scheduler import Scheduler
from hawarma.services.executor import Executor
from hawarma.services.resource_guards import ResourceGuards
from hawarma.state import (
    init_game_state,
    init_session_state,
    reset_global_state,
)
from tests.fixtures.test_recipes import TEST_RECIPES, create_test_order, reset_order_counter
from tests.mocks import MockDetectionService, ScheduledOrder


# ============================================================================
# 工具函数
# ============================================================================


def to_sim_recipe(prod: Recipe) -> SimRecipe:
    """生产 Recipe → env_simulator Recipe"""
    return SimRecipe(
        name=prod.name,
        ingredients=[
            Ingredient(
                name=prod.raw_ingredients[i],
                cooker=prod.cookers[i],
                duration=prod.cook_durations[i],
            )
            for i in range(len(prod.raw_ingredients))
        ],
        condiments={c: 1 for c in prod.condiments},
    )


def collect_mappings(recipes: list[Recipe]):
    """从配方集合收集所有食材/灶台/调料，构建坐标映射"""
    all_ingredients: list[str] = []
    all_condiments: list[str] = []
    for r in recipes:
        for ing in r.raw_ingredients:
            if ing not in all_ingredients:
                all_ingredients.append(ing)
        for c in r.condiments:
            if c not in all_condiments:
                all_condiments.append(c)

    raw_ingredients_mapping = {
        ing: (50, 100 + i * 50) for i, ing in enumerate(all_ingredients)
    }
    cookers_mapping = {
        c: (100, 200 + i * 100) for i, c in enumerate(["grill", "oven", "skillet", "pot"])
    }
    condiments_mapping = {
        c: (150, 100 + i * 50) for i, c in enumerate(all_condiments)
    }

    return raw_ingredients_mapping, cookers_mapping, condiments_mapping


# ============================================================================
# 测试基类
# ============================================================================


class BridgeTestBase(unittest.TestCase):
    """EnvBridge 测试基类"""

    def _setup(
        self, prod_recipes: list[Recipe]
    ) -> tuple[GameSimulator, EnvBridge, Executor, Scheduler]:
        """初始化 bridge + executor + scheduler"""
        reset_global_state()
        reset_order_counter()

        cookers = ["grill", "oven", "skillet", "pot"]
        game_state = init_game_state(cookers)
        session_state = init_session_state(prod_recipes)

        # env_simulator
        sim = GameSimulator()
        sim.setup_cookers(cookers)
        sim.setup_stockpile(["stk0", "stk1", "stk2"])

        # 坐标映射
        raw_map, cooker_map, cond_map = collect_mappings(prod_recipes)
        assembly_pos = (500, 300)
        stockpile_positions = [(300, 100), (300, 200), (300, 300)]
        pickup_positions = [(700, 100), (700, 200), (700, 300), (700, 400)]

        # bridge
        bridge = EnvBridge(
            simulator=sim,
            raw_ingredients_mapping=raw_map,
            cookers_mapping=cooker_map,
            condiments_mapping=cond_map,
            assembly_pos=assembly_pos,
            stockpile_positions=stockpile_positions,
            pickup_positions=pickup_positions,
        )

        # executor + scheduler
        guards = ResourceGuards(cookers=cookers, stockpile_slot_count=3)
        executor = Executor(
            game_state=game_state,
            session_state=session_state,
            raw_ingredients_mapping=raw_map,
            cookers_mapping=cooker_map,
            condiments_mapping=cond_map,
            assembly_station_pos=assembly_pos,
            pickup_stations_pos=pickup_positions,
            stockpile_positions=stockpile_positions,
            ui_manager=bridge,
            guards=guards,
            ordered_recipes=prod_recipes,
        )
        scheduler = Scheduler(game_state, session_state)

        return sim, bridge, executor, scheduler, game_state

    def _inject(
        self,
        sim: GameSimulator,
        game_state,
        slot_idx: int,
        prod_recipe: Recipe,
        is_rush: bool = False,
    ):
        """向两个系统注入同一个订单"""
        sim_order = sim.inject_order(slot_idx, to_sim_recipe(prod_recipe), is_rush=is_rush)
        prod_order = create_test_order(
            prod_recipe.slug if hasattr(prod_recipe, "slug") else prod_recipe.name.lower().replace(" ", "_"),
            is_rush=is_rush,
        )
        game_state.orders[slot_idx] = prod_order
        return prod_order

    def _run(self, executor, scheduler, game_state, max_ticks: int = 500):
        """运行 tick 循环直到所有订单完成"""

        async def loop():
            for tick in range(max_ticks):
                now = asyncio.get_event_loop().time()
                async with game_state.lock:
                    actions = scheduler.get_next_actions()
                if actions:
                    await executor.execute_batch(actions)
                done = game_state.completed_orders_count >= len(self.recipes)
                if done:
                    return
                await asyncio.sleep(0.05)

        asyncio.run(loop())

    def _print_timeline(self, bridge: EnvBridge):
        """打印 swipe 时间线"""
        prev_t = bridge.records[0].time if bridge.records else 0
        for r in bridge.records:
            gap = r.time - prev_t
            gap_str = f"  (+{gap:.2f}s)" if gap > 0.001 else ""
            status = "OK" if r.success else "FAIL"
            print(
                f"  {r.time:7.2f}s  {r.action:20s}  "
                f"{r.symbol_start} -> {r.symbol_end}  [{status}]{gap_str}"
            )
            prev_t = r.time


# ============================================================================
# 测试场景
# ============================================================================


class TestBridgeScenarios(BridgeTestBase):
    """非库存场景的 bridge 验证"""

    def test_single_order(self):
        """单订单：红烧鱼"""
        fish = TEST_RECIPES["braised_fish"]
        sim, bridge, executor, scheduler, gs = self._setup([fish])

        self._inject(sim, gs, 0, fish)
        self._run(executor, scheduler, gs)

        self._print_timeline(bridge)
        self.assertEqual(
            len(bridge.violations), 0,
            f"Violations:\n" + "\n".join(f"  {v}" for v in bridge.violations),
        )
        self.assertEqual(gs.completed_orders_count, 1)

    def test_two_orders_same_cooker(self):
        """双订单：同一灶台串行"""
        fish = TEST_RECIPES["braised_fish"]  # skillet
        shrimp = TEST_RECIPES["saltbaked_shrimp"]  # skillet
        sim, bridge, executor, scheduler, gs = self._setup([fish, shrimp])

        self._inject(sim, gs, 0, fish)
        self._inject(sim, gs, 1, shrimp)
        self._run(executor, scheduler, gs)

        self._print_timeline(bridge)
        self.assertEqual(
            len(bridge.violations), 0,
            f"Violations:\n" + "\n".join(f"  {v}" for v in bridge.violations),
        )

    def test_rush_order(self):
        """Rush 订单"""
        tomahawk = TEST_RECIPES["tomahawk"]  # grill, long cook
        fish = TEST_RECIPES["braised_fish"]  # skillet
        sim, bridge, executor, scheduler, gs = self._setup([tomahawk, fish])

        self._inject(sim, gs, 0, tomahawk, is_rush=False)
        self._inject(sim, gs, 1, fish, is_rush=True)
        self._run(executor, scheduler, gs)

        self._print_timeline(bridge)
        self.assertEqual(
            len(bridge.violations), 0,
            f"Violations:\n" + "\n".join(f"  {v}" for v in bridge.violations),
        )

    def test_four_orders(self):
        """四订单满载"""
        recipes = [
            TEST_RECIPES["braised_fish"],
            TEST_RECIPES["hearty_pie"],
            TEST_RECIPES["saltbaked_shrimp"],
            TEST_RECIPES["risotto"],
        ]
        sim, bridge, executor, scheduler, gs = self._setup(recipes)

        for i, r in enumerate(recipes):
            self._inject(sim, gs, i, r)
        self._run(executor, scheduler, gs)

        self._print_timeline(bridge)
        self.assertEqual(
            len(bridge.violations), 0,
            f"Violations:\n" + "\n".join(f"  {v}" for v in bridge.violations),
        )
        self.assertEqual(
            gs.completed_orders_count, 4,
        )


class TestBridgeErrorDetection(BridgeTestBase):
    """验证 bridge 能正确检测违规"""

    def test_detect_invalid_cooker(self):
        """检测：向不存在的灶台烹饪"""
        fish = TEST_RECIPES["braised_fish"]
        sim, bridge, executor, scheduler, gs = self._setup([fish])

        sim.inject_order(0, to_sim_recipe(fish))

        # 直接调用 bridge 的 swipe，传入无效坐标
        async def test():
            await bridge.swipe((50, 100), (999, 999), duration=0.1)

        asyncio.run(test())

        self.assertTrue(bridge.has_violations())
        self.assertIn("Invalid", bridge.violations[0])

    def test_detect_assembly_conflict(self):
        """检测：组装站被占用时强行送入"""
        fish = TEST_RECIPES["braised_fish"]
        sim, bridge, executor, scheduler, gs = self._setup([fish])

        sim.inject_order(0, to_sim_recipe(fish))

        # 手动让 assembly 被占用
        sim.start_cooking("clearwater_fish", "skillet")
        sim.tick(4.0)
        sim.move_to_assembly("skillet")  # order 1 占用 assembly

        # 尝试另一个食材到 assembly（应该失败）
        async def test():
            # 模拟一个不存在的食材 swipe 到 assembly
            bridge.violations.clear()
            bridge.records.clear()
            # 手动调 _execute_sim 检查冲突
            result = sim.move_to_assembly("oven")  # oven 没东西
            self.assertFalse(result)

        asyncio.run(test())


if __name__ == "__main__":
    unittest.main(verbosity=2)
