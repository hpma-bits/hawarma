"""
状态快照回归测试（Issue #16）

验证 UnifiedState 的观测不可变语义（双端口径一致）：
- GameEnv.get_unified_state()（真实环境）与 SimEnv.get_unified_state()（模拟器）
  返回全量深快照：篡改返回值任意层（cooker / order / assembly / stockpile /
  mixing_bowl 的字段与嵌套容器）不得污染 env 内部状态；
- 模拟器侧 GameState.copy() 用 deepcopy，真实环境侧改为各模型 snapshot()
  字段级拷贝，两端"观测不可变"语义对齐；
- Order 快照保留冻结字段语义：spawned_at_visibility 在快照上同样创建后不可改。

性能自检（粗测，无硬断言阈值）：
- GameEnv.get_unified_state() 深快照单次耗时（time.perf_counter，循环 1000 次
  取均值）：本机实测约 0.03 ms/次，远低于 0.5ms 量级；
  游戏每步决策调用（约 2-10Hz）的预算充足。
- SimEnv.get_unified_state() 同口径实测约 0.05 ms/次（recipes dict 较大）。
  （具体数字随机器浮动，超阈值时在 issue 报告中说明。）

采用 unittest 风格（python -m unittest discover tests 可收集）。

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

import time
import unittest
from pathlib import Path

from hawarma.core.models import (
    AssemblyState,
    CookerState,
    MixingBowlState,
    Order,
    StockpileSlot,
)
from hawarma.game.game_env import GameEnv
from playground.env.sim import SimEnv

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
RECIPES_FILE = str(_PROJECT_ROOT / "data" / "recipes.json")


# ============================================================================
# 模型级 snapshot() 单元测试
# ============================================================================


class TestModelSnapshot(unittest.TestCase):
    """各核心模型 snapshot() 的字段拷贝与嵌套容器隔离"""

    def test_cooker_state_snapshot(self):
        c = CookerState(busy=True, item_name="fish", cooker_type="grill",
                        started_at=1.0, done_at=5.0, expired_at=10.0)
        snap = c.snapshot()
        self.assertIsNot(snap, c)
        self.assertEqual(snap, c)  # dataclass 全字段相等
        snap.busy = False
        snap.done_at = None
        self.assertTrue(c.busy)
        self.assertEqual(c.done_at, 5.0)

    def test_assembly_state_snapshot_replaces_containers(self):
        a = AssemblyState(
            ingredients=[("fish", "grill", 1.0), ("rice", "pot", 2.0)],
            target_recipe_slug="r1",
            owner_order_id=7,
            condiments={"salt": 1},
        )
        snap = a.snapshot()
        self.assertIsNot(snap, a)
        self.assertIsNot(snap.ingredients, a.ingredients)
        self.assertIsNot(snap.condiments, a.condiments)
        self.assertEqual(snap, a)  # 内容一致
        snap.ingredients.append(("hacked", "oven", 9.0))
        snap.ingredients_cookers.append(("hacked", "oven"))
        snap.condiments["salt"] = 99
        snap.condiments["pepper"] = 5
        snap.target_recipe_slug = "hacked"
        snap.owner_order_id = 99
        self.assertEqual(len(a.ingredients), 2)
        self.assertEqual(a.condiments, {"salt": 1})
        self.assertEqual(a.target_recipe_slug, "r1")
        self.assertEqual(a.owner_order_id, 7)

    def test_stockpile_slot_snapshot(self):
        s = StockpileSlot(item_name="meat", cooker_type="skillet", count=2)
        snap = s.snapshot()
        self.assertIsNot(snap, s)
        self.assertEqual(snap, s)
        snap.count = 0
        snap.item_name = None
        snap.cooker_type = None
        self.assertEqual(s.count, 2)
        self.assertEqual(s.item_name, "meat")
        self.assertEqual(s.cooker_type, "skillet")

    def test_mixing_bowl_state_snapshot_replaces_containers(self):
        m = MixingBowlState(ingredients=["cream", "berry"],
                            condiments={"sugar": 1},
                            target_recipe_slug="cake",
                            is_stirred=True)
        snap = m.snapshot()
        self.assertIsNot(snap, m)
        self.assertIsNot(snap.ingredients, m.ingredients)
        self.assertIsNot(snap.condiments, m.condiments)
        self.assertEqual(snap, m)
        snap.ingredients.append("hacked")
        snap.ingredients.clear()
        snap.condiments["sugar"] = 99
        snap.target_recipe_slug = "hacked"
        snap.is_stirred = False
        self.assertEqual(m.ingredients, ["cream", "berry"])
        self.assertEqual(m.condiments, {"sugar": 1})
        self.assertEqual(m.target_recipe_slug, "cake")
        self.assertTrue(m.is_stirred)

    def test_order_snapshot_copies_fields(self):
        o = Order(order_id=1, recipe_slug="r1", is_rush=True,
                  created_at=2.0, timeout_at=42.0,
                  spawned_at_visibility=3.5, done=False)
        snap = o.snapshot()
        self.assertIsNot(snap, o)
        self.assertEqual(snap, o)
        snap.done = True
        snap.timeout_at = 0.0
        snap.served_at = 9.0
        self.assertFalse(o.done)
        self.assertEqual(o.timeout_at, 42.0)
        self.assertIsNone(o.served_at)

    def test_order_snapshot_preserves_frozen_field_semantics(self):
        """快照的 spawned_at_visibility 同样在构造时锁定，创建后不可改"""
        o = Order(order_id=1, recipe_slug="r1", is_rush=False,
                  created_at=0.0, timeout_at=10.0, spawned_at_visibility=3.5)
        snap = o.snapshot()
        self.assertEqual(snap.spawned_at_visibility, 3.5)
        with self.assertRaises(AttributeError):
            snap.spawned_at_visibility = 9.9
        self.assertEqual(o.spawned_at_visibility, 3.5)


# ============================================================================
# GameEnv（真实环境）观测隔离
# ============================================================================


def _make_populated_game_env() -> GameEnv:
    """构造一个各层状态均非空的真实环境"""
    env = GameEnv(cooker_names=["grill", "pot", "skillet"],
                  stockpile_slots=3, game_duration=90.0)
    # 灶台：一口在烹饪
    env.start_cooking("chicken", "grill", 4.0)
    # 订单：占用 slot0
    env.add_order("shawarma", is_rush=True)
    # 组装站：已有食材 + 调料 + 目标配方（直接构造，避免依赖配方推断）
    env._assembly.ingredients.append(("chicken", "grill", 0.0))
    env._assembly.target_recipe_slug = "shawarma"
    env._assembly.owner_order_id = 1
    env._assembly.condiments["salt"] = 1
    # 库存：slot0 有 2 个食材
    env._stockpile["slot0"].item_name = "beef"
    env._stockpile["slot0"].cooker_type = "skillet"
    env._stockpile["slot0"].count = 2
    # 搅拌盆：非空、已搅拌
    env._mixing_bowl.ingredients.append("cream")
    env._mixing_bowl.condiments["sugar"] = 1
    env._mixing_bowl.target_recipe_slug = "cake"
    env._mixing_bowl.is_stirred = True
    return env


class TestGameEnvSnapshotIsolation(unittest.TestCase):
    """GameEnv.get_unified_state() 返回全量深快照，篡改不污染 env"""

    def test_no_shared_mutable_objects(self):
        env = _make_populated_game_env()
        state = env.get_unified_state()
        # 容器与元素均不与 env 内部共享
        self.assertIsNot(state.cookers, env._cookers)
        self.assertIsNot(state.cookers["grill"], env._cookers["grill"])
        self.assertIsNot(state.orders[0], env._orders[0])
        self.assertIsNot(state.assembly, env._assembly)
        self.assertIsNot(state.assembly.ingredients, env._assembly.ingredients)
        self.assertIsNot(state.assembly.condiments, env._assembly.condiments)
        self.assertIsNot(state.stockpile, env._stockpile)
        self.assertIsNot(state.stockpile["slot0"], env._stockpile["slot0"])
        self.assertIsNot(state.mixing_bowl, env._mixing_bowl)
        self.assertIsNot(state.mixing_bowl.ingredients, env._mixing_bowl.ingredients)
        self.assertIsNot(state.mixing_bowl.condiments, env._mixing_bowl.condiments)

    def test_snapshot_content_matches_env(self):
        """快照内容与 env 内部状态逐字段一致（防止 snapshot 丢字段）"""
        env = _make_populated_game_env()
        state = env.get_unified_state()
        self.assertEqual(state.cookers["grill"], env._cookers["grill"])
        self.assertEqual(state.orders[0], env._orders[0])
        self.assertEqual(state.assembly, env._assembly)
        self.assertEqual(state.stockpile["slot0"], env._stockpile["slot0"])
        self.assertEqual(state.mixing_bowl, env._mixing_bowl)

    def test_mutating_snapshot_does_not_touch_env(self):
        env = _make_populated_game_env()
        order = env._orders[0]
        self.assertIsNotNone(order)
        timeout_at_before = order.timeout_at

        state = env.get_unified_state()

        # 篡改快照的每一层
        state.cookers["grill"].busy = False
        state.cookers["grill"].item_name = "hacked"
        state.cookers["grill"].done_at = None
        state.cookers["grill"].started_at = None
        state.cookers["grill"].expired_at = None
        state.orders[0].done = True
        state.orders[0].timeout_at = 0.0
        state.orders[0].served_at = 1.0
        state.assembly.ingredients.append(("hacked", "oven", 9.0))
        state.assembly.ingredients.clear()
        state.assembly.ingredients_cookers.append(("hacked", "oven"))
        state.assembly.condiments["salt"] = 99
        state.assembly.condiments["pepper"] = 5
        state.assembly.target_recipe_slug = "hacked"
        state.assembly.owner_order_id = 99
        state.stockpile["slot0"].count = 0
        state.stockpile["slot0"].item_name = None
        state.stockpile["slot0"].cooker_type = None
        state.mixing_bowl.ingredients.append("hacked")
        state.mixing_bowl.condiments["sugar"] = 99
        state.mixing_bowl.target_recipe_slug = "hacked"
        state.mixing_bowl.is_stirred = False

        # env 内部状态不变
        self.assertTrue(env._cookers["grill"].busy)
        self.assertEqual(env._cookers["grill"].item_name, "chicken")
        self.assertIsNotNone(env._cookers["grill"].done_at)
        self.assertIsNotNone(env._cookers["grill"].started_at)
        self.assertIsNotNone(env._cookers["grill"].expired_at)
        self.assertFalse(order.done)
        self.assertEqual(order.timeout_at, timeout_at_before)
        self.assertIsNone(order.served_at)
        self.assertEqual(env._assembly.ingredients, [("chicken", "grill", 0.0)])
        self.assertEqual(env._assembly.condiments, {"salt": 1})
        self.assertEqual(env._assembly.target_recipe_slug, "shawarma")
        self.assertEqual(env._assembly.owner_order_id, 1)
        self.assertEqual(env._stockpile["slot0"].count, 2)
        self.assertEqual(env._stockpile["slot0"].item_name, "beef")
        self.assertEqual(env._stockpile["slot0"].cooker_type, "skillet")
        self.assertEqual(env._mixing_bowl.ingredients, ["cream"])
        self.assertEqual(env._mixing_bowl.condiments, {"sugar": 1})
        self.assertEqual(env._mixing_bowl.target_recipe_slug, "cake")
        self.assertTrue(env._mixing_bowl.is_stirred)

    def test_mutating_snapshot_containers_does_not_touch_env(self):
        """篡改快照容器本身（增删 key / 替换元素）同样不触内部"""
        env = _make_populated_game_env()
        state = env.get_unified_state()
        state.cookers["grill"] = CookerState()  # 替换元素
        state.cookers.pop("pot")
        state.stockpile.pop("slot1")
        self.assertIn("pot", env._cookers)
        self.assertIn("slot1", env._stockpile)
        self.assertTrue(env._cookers["grill"].busy)


# ============================================================================
# SimEnv（模拟器）观测隔离
# ============================================================================


def _make_populated_sim_env() -> SimEnv:
    """构造一个各层状态均非空的模拟器环境（确定性种子 + 受控推进）"""
    env = SimEnv(recipes_file=RECIPES_FILE)
    env.reset(seed=42)
    sim = env._sim
    assert sim is not None
    # 确定性：t=2.0 生成首单，推进到 t=3.0 使其越过 1s 可见性窗口
    sim._next_order_refresh_time = 2.0
    sim.tick(2.0)
    sim.tick(1.0)
    assert sim._state.orders[0] is not None
    # 灶台/组装站/库存：直接构造非空状态（GameState 无 mixing_bowl 字段）
    cooker_name = next(iter(sim._state.cookers))
    cooker = sim._state.cookers[cooker_name]
    cooker.busy = True
    cooker.item_name = "fish"
    cooker.cooker_type = cooker_name
    cooker.started_at = 2.0
    cooker.done_at = 4.0
    cooker.expired_at = 9.0
    sim._state.assembly.ingredients.append(("fish", cooker_name, 2.0))
    sim._state.assembly.target_recipe_slug = "r"
    sim._state.assembly.condiments["salt"] = 1
    slot_name = next(iter(sim._state.stockpile))
    slot = sim._state.stockpile[slot_name]
    slot.item_name = "meat"
    slot.cooker_type = "skillet"
    slot.count = 2
    return env


class TestSimEnvSnapshotIsolation(unittest.TestCase):
    """SimEnv.get_unified_state() 无 sim._state 引用逃逸，篡改不污染模拟器"""

    def test_no_shared_mutable_objects(self):
        env = _make_populated_sim_env()
        sim_state = env._sim._state
        state = env.get_unified_state()
        order_idx = next(i for i, o in enumerate(state.orders) if o is not None)
        self.assertIsNot(state.cookers, sim_state.cookers)
        self.assertIsNot(next(iter(state.cookers.values())),
                         next(iter(sim_state.cookers.values())))
        self.assertIsNot(state.orders[order_idx], sim_state.orders[order_idx])
        self.assertIsNot(state.assembly, sim_state.assembly)
        self.assertIsNot(state.assembly.ingredients, sim_state.assembly.ingredients)
        self.assertIsNot(state.assembly.condiments, sim_state.assembly.condiments)
        self.assertIsNot(state.stockpile, sim_state.stockpile)
        self.assertIsNot(next(iter(state.stockpile.values())),
                         next(iter(sim_state.stockpile.values())))

    def test_mutating_snapshot_does_not_touch_sim_state(self):
        env = _make_populated_sim_env()
        sim_state = env._sim._state
        order_idx = next(i for i, o in enumerate(sim_state.orders) if o is not None)
        order = sim_state.orders[order_idx]
        timeout_at_before = order.timeout_at
        cooker_name = next(iter(sim_state.cookers))
        cooker_ref = sim_state.cookers[cooker_name]
        slot_name = next(iter(sim_state.stockpile))
        slot_ref = sim_state.stockpile[slot_name]

        state = env.get_unified_state()

        # 篡改快照的每一层（含可见订单与隐藏窗口外的字段）
        state.cookers[cooker_name].busy = False
        state.cookers[cooker_name].item_name = "hacked"
        state.cookers[cooker_name].done_at = None
        state.orders[order_idx].done = True
        state.orders[order_idx].timeout_at = 0.0
        state.orders[order_idx].served_at = 1.0
        state.assembly.ingredients.append(("hacked", "oven", 9.0))
        state.assembly.ingredients.clear()
        state.assembly.ingredients_cookers.append(("hacked", "oven"))
        state.assembly.condiments["salt"] = 99
        state.assembly.condiments["pepper"] = 5
        state.assembly.target_recipe_slug = "hacked"
        state.stockpile[slot_name].count = 0
        state.stockpile[slot_name].item_name = None
        state.cookers.pop(cooker_name)
        state.stockpile.pop(slot_name)

        # sim._state 内部状态不变
        self.assertTrue(cooker_ref.busy)
        self.assertEqual(cooker_ref.item_name, "fish")
        self.assertIsNotNone(cooker_ref.done_at)
        self.assertFalse(order.done)
        self.assertEqual(order.timeout_at, timeout_at_before)
        self.assertIsNone(order.served_at)
        self.assertEqual(sim_state.assembly.ingredients, [("fish", cooker_name, 2.0)])
        self.assertEqual(sim_state.assembly.condiments, {"salt": 1})
        self.assertEqual(sim_state.assembly.target_recipe_slug, "r")
        self.assertEqual(slot_ref.count, 2)
        self.assertEqual(slot_ref.item_name, "meat")
        self.assertIn(cooker_name, sim_state.cookers)
        self.assertIn(slot_name, sim_state.stockpile)


# ============================================================================
# 性能自检（粗测，无硬断言阈值）
# ============================================================================


class TestSnapshotPerformanceProbe(unittest.TestCase):
    """
    深快照单次耗时粗测（time.perf_counter，循环 1000 次取均值）。

    不设硬断言阈值（CI 机器浮动大）；量级预期 < 0.5ms/次。
    实测记录见本文件头部注释与 issue 报告。
    """

    N = 1000

    def test_game_env_snapshot_speed_probe(self):
        env = _make_populated_game_env()
        env.get_unified_state()  # 预热
        t0 = time.perf_counter()
        for _ in range(self.N):
            env.get_unified_state()
        elapsed_ms = (time.perf_counter() - t0) / self.N * 1000.0
        # 软性 sanity：超过 10ms 才算异常量级（阈值远宽于 0.5ms 目标）
        self.assertLess(elapsed_ms, 10.0, f"snapshot too slow: {elapsed_ms:.3f} ms")

    def test_sim_env_snapshot_speed_probe(self):
        env = _make_populated_sim_env()
        env.get_unified_state()  # 预热
        t0 = time.perf_counter()
        for _ in range(self.N):
            env.get_unified_state()
        elapsed_ms = (time.perf_counter() - t0) / self.N * 1000.0
        self.assertLess(elapsed_ms, 10.0, f"snapshot too slow: {elapsed_ms:.3f} ms")


if __name__ == "__main__":
    unittest.main()
