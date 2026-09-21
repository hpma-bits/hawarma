"""Ticket #12 回归护栏 3：GastronomeStrategy 金决策快照（行为漂移立即现形）.

给定 10 个代表性 UnifiedState 固定场景，GastronomeStrategy.decide() 的产出
必须与 tests/golden/gastronome_decisions.json 快照完全相等。
只锁「给定状态 → 决策产出」这一外部可观测行为，不锁瀑布内部实现。

场景覆盖（issue #12 要求的 8 类 + move/pull 细分）：
可送餐 / 清理过期 / 抢占组装 / 移动到组装站 / 并行烹饪(CPM) / 调料 /
库存取(pull) / 库存放(store) / 预烹饪 / 空转返回 None。

确定性设计：
- 配方用 data/recipes.json 真实数据固定 4 个 slug（文件为静态数据）
- 状态构造全部显式字面量；dict 按固定顺序构造
- 唯一遍历 set 的分支（预烹饪）按 duration 降序取唯一最大者，不受
  PYTHONHASHSEED 影响；比对用 dict 相等（与键序无关）

快照再生成方式（行为有意变更时）：
    # Git Bash
    HAWARMA_REGEN_GOLDEN=1 PYTHONPATH=src python -m unittest tests.test_gastronome_golden
    # CMD
    set HAWARMA_REGEN_GOLDEN=1 && python -m unittest tests.test_gastronome_golden
    然后人工 review tests/golden/gastronome_decisions.json 的 diff 后提交。

已有覆盖：tests/test_rush_tiebreaker.py（rush/visibility 跨越对排序的影响）、
tests/test_dessert_strategy.py（Dessert 策略）——与本文件互补，不重复。
"""

import dataclasses
import json
import os
import unittest
from pathlib import Path

from hawarma.agent.strategies.gastronome import GastronomeStrategy
from hawarma.core.models import AssemblyState, CookerState, Order, StockpileSlot
from hawarma.core.state import UnifiedState
from hawarma.paths import data_path
from hawarma.services.recipe_manager import RecipeManager

GOLDEN_PATH = Path(__file__).parent / "golden" / "gastronome_decisions.json"
REGEN_ENV = "HAWARMA_REGEN_GOLDEN"

# 固定 4 配方（data/recipes.json 真实数据，插入顺序即字典顺序）：
#   braisedNewYearFish : clearwater_fish/skillet/4.0
#   gildedShoreRisotto : clearwater_fish/oven/3.0 + creamfield_rice/pot/2.0
#   farmsteadFeastRoast: farmstead_pork/oven/4.0
#   newYearJiaozi      : dough_wrappers/pot/3.0 + tender_lamb/grill/4.0
SLUGS = ["braisedNewYearFish", "gildedShoreRisotto",
         "farmsteadFeastRoast", "newYearJiaozi"]


def _load_recipes() -> dict:
    manager = RecipeManager(data_path("recipes.json"))
    manager.load_recipes()
    return {slug: manager.get_recipe_by_slug(slug) for slug in SLUGS}


def _cooker(busy: bool = False, item: str | None = None, cooker_type: str | None = None,
            started_at: float | None = None, done_at: float | None = None,
            expired_at: float | None = None) -> CookerState:
    return CookerState(busy=busy, item_name=item, cooker_type=cooker_type,
                       started_at=started_at, done_at=done_at, expired_at=expired_at)


def _order(order_id: int, slug: str, rush: bool = False,
           created_at: float = 0.0, timeout_at: float = 80.0) -> Order:
    return Order(order_id=order_id, recipe_slug=slug, is_rush=rush,
                 created_at=created_at, timeout_at=timeout_at)


def _state(orders, cookers, assembly=None, stockpile=None,
           time: float = 10.0, total_visibility: float = 0.0) -> UnifiedState:
    return UnifiedState(
        time=time,
        orders=tuple(orders),
        cookers=cookers,
        assembly=assembly or AssemblyState(),
        stockpile=stockpile or {f"slot{i}": StockpileSlot() for i in range(3)},
        recipes=RECIPES,
        game_duration=90.0,
        is_in_animation_window=False,
        total_visibility=total_visibility,
    )


def _build_scenarios() -> list[dict]:
    """构造 10 个固定场景（顺序即快照顺序）。"""
    free = {
        "skillet": _cooker(cooker_type="skillet"),
        "oven": _cooker(cooker_type="oven"),
        "pot": _cooker(cooker_type="pot"),
        "grill": _cooker(cooker_type="grill"),
    }
    scenarios = []

    # 1. 可送餐：组装站 R1 齐料齐调料 → 送 slot 0
    scenarios.append({
        "name": "serve_complete_order",
        "description": "assembly complete for braisedNewYearFish -> serve slot 0",
        "state": _state(
            orders=[_order(1, "braisedNewYearFish"), None, None, None],
            cookers=free,
            assembly=AssemblyState(
                ingredients=[("clearwater_fish", "skillet", 0.0)],
                target_recipe_slug="braisedNewYearFish",
                condiments={"hearthspice": 1, "acacia_honey": 1},
            ),
        ),
    })

    # 2. 清理过期：skillet 食材已过期 → 清灶台
    scenarios.append({
        "name": "clear_expired_cooker",
        "description": "expired ingredient on skillet -> clear cooker",
        "state": _state(
            orders=[_order(1, "braisedNewYearFish"), None, None, None],
            cookers={
                "skillet": _cooker(True, "clearwater_fish", "skillet", 6.0, 6.0, 10.5),
                "oven": _cooker(cooker_type="oven"),
                "pot": _cooker(cooker_type="pot"),
                "grill": _cooker(cooker_type="grill"),
            },
            time=11.0,
        ),
    })

    # 3. 抢占组装：assembly 在做长 CP 的 R4，短 CP 的 R1 已就绪 → 清空组装站
    scenarios.append({
        "name": "assembly_preemption",
        "description": "assembly targets long-CP jiaozi while ready fish order waits -> preempt",
        "state": _state(
            orders=[_order(1, "newYearJiaozi"), _order(2, "braisedNewYearFish"),
                    None, None],
            cookers={
                "skillet": _cooker(True, "clearwater_fish", "skillet", 5.0, 9.0, 30.0),
                "oven": _cooker(cooker_type="oven"),
                "pot": _cooker(cooker_type="pot"),
                "grill": _cooker(cooker_type="grill"),
            },
            assembly=AssemblyState(
                ingredients=[("dough_wrappers", "pot", 0.0)],
                target_recipe_slug="newYearJiaozi",
            ),
        ),
    })

    # 4. 移动到组装站：skillet 鱼已完成且被需要 → 移入组装站
    scenarios.append({
        "name": "move_done_to_assembly",
        "description": "done clearwater_fish on skillet needed by order -> move to assembly",
        "state": _state(
            orders=[_order(1, "braisedNewYearFish"), None, None, None],
            cookers={
                "skillet": _cooker(True, "clearwater_fish", "skillet", 6.0, 9.0, 30.0),
                "oven": _cooker(cooker_type="oven"),
                "pot": _cooker(cooker_type="pot"),
                "grill": _cooker(cooker_type="grill"),
            },
        ),
    })

    # 5. 并行烹饪：R2 双食材、双灶空闲 → CPM 选分高的 clearwater_fish/oven 先开火
    scenarios.append({
        "name": "parallel_cooking_cpm",
        "description": "risotto order, free oven+pot -> cook highest-scored combo first",
        "state": _state(
            orders=[_order(1, "gildedShoreRisotto"), None, None, None],
            cookers=free,
        ),
    })

    # 6. 调料：R1 料齐缺调料 → 加第一味 hearthspice
    scenarios.append({
        "name": "add_condiment",
        "description": "assembly has fish, condiments missing -> add first condiment",
        "state": _state(
            orders=[_order(1, "braisedNewYearFish"), None, None, None],
            cookers=free,
            assembly=AssemblyState(
                ingredients=[("clearwater_fish", "skillet", 0.0)],
                target_recipe_slug="braisedNewYearFish",
            ),
        ),
    })

    # 7. 库存取：R2 组装中缺 rice，库存有 → 从库存取
    scenarios.append({
        "name": "pull_from_stockpile",
        "description": "risotto in progress missing rice, stockpile has it -> pull slot0",
        "state": _state(
            orders=[_order(1, "gildedShoreRisotto"), None, None, None],
            cookers=free,
            assembly=AssemblyState(
                ingredients=[("clearwater_fish", "oven", 0.0)],
                target_recipe_slug="gildedShoreRisotto",
            ),
            stockpile={
                "slot0": StockpileSlot(item_name="creamfield_rice",
                                       cooker_type="pot", count=1),
                "slot1": StockpileSlot(),
                "slot2": StockpileSlot(),
            },
        ),
    })

    # 8. 库存放：无人需要的已完成食材在 skillet，其余灶忙 → 入库
    scenarios.append({
        "name": "store_to_stockpile",
        "description": "done-but-unneeded rice on skillet, no free cooker -> store slot0",
        "state": _state(
            orders=[_order(1, "braisedNewYearFish"), None, None, None],
            cookers={
                "skillet": _cooker(True, "creamfield_rice", "skillet", 4.0, 8.0, 30.0),
                "oven": _cooker(True, "farmstead_pork", "oven", 9.0, 13.0, 20.0),
                "pot": _cooker(True, "dough_wrappers", "pot", 9.0, 14.0, 21.0),
                "grill": _cooker(True, "tender_lamb", "grill", 9.0, 16.0, 23.0),
            },
        ),
    })

    # 9. 预烹饪：无订单、pot 独闲、开局早期 → 预烹饪 pot 上时长最高的 dough
    scenarios.append({
        "name": "precook_without_orders",
        "description": "no orders, only pot free, early game -> precook dough_wrappers",
        "state": _state(
            orders=[None, None, None, None],
            cookers={
                "skillet": _cooker(True, "clearwater_fish", "skillet", 6.0, 12.0, 18.0),
                "oven": _cooker(True, "farmstead_pork", "oven", 9.0, 13.0, 20.0),
                "pot": _cooker(cooker_type="pot"),
                "grill": _cooker(True, "tender_lamb", "grill", 9.0, 14.0, 21.0),
            },
        ),
    })

    # 10. 空转：唯一订单的食材都在烹饪中，无任何可做动作 → None
    scenarios.append({
        "name": "idle_returns_none",
        "description": "fish cooking, all cookers busy, nothing to do -> decide None",
        "state": _state(
            orders=[_order(1, "braisedNewYearFish"), None, None, None],
            cookers={
                "skillet": _cooker(True, "clearwater_fish", "skillet", 6.0, 14.0, 20.0),
                "oven": _cooker(True, "farmstead_pork", "oven", 9.0, 13.0, 20.0),
                "pot": _cooker(True, "dough_wrappers", "pot", 9.0, 12.0, 19.0),
                "grill": _cooker(True, "tender_lamb", "grill", 9.0, 15.0, 22.0),
            },
        ),
    })
    return scenarios


def _serialize_decision(action) -> dict | None:
    """Action → {type, action: asdict}；None → None（dataclass asdict + 类型名）."""
    if action is None:
        return None
    return {"type": type(action).__name__, "action": dataclasses.asdict(action)}


RECIPES: dict = _load_recipes()


class TestGastronomeGoldenSnapshot(unittest.TestCase):
    """逐一比对快照；HAWARMA_REGEN_GOLDEN=1 时重写快照文件."""

    def test_decisions_match_golden_snapshot(self):
        strategy = GastronomeStrategy()
        strategy.on_game_start(RECIPES)
        scenarios = _build_scenarios()
        actual = []
        for scenario in scenarios:
            decision = strategy.decide(scenario["state"])
            repeat = strategy.decide(scenario["state"])
            self.assertEqual(_serialize_decision(decision), _serialize_decision(repeat))
            actual.append({
                "name": scenario["name"],
                "description": scenario["description"],
                "decision": _serialize_decision(decision),
            })

        if os.environ.get(REGEN_ENV) == "1":
            GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN_PATH.write_text(
                json.dumps({"strategy": "gastronome", "scenarios": actual},
                           indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.skipTest(f"golden regenerated: {GOLDEN_PATH}")

        self.assertTrue(
            GOLDEN_PATH.exists(),
            msg=f"golden snapshot missing: {GOLDEN_PATH}; regenerate with "
                f"{REGEN_ENV}=1 python -m unittest tests.test_gastronome_golden",
        )
        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(golden.get("strategy"), "gastronome")

        golden_names = [s["name"] for s in golden["scenarios"]]
        actual_names = [s["name"] for s in actual]
        self.assertEqual(
            actual_names, golden_names,
            msg="scenario set diverged from golden; if intentional, regenerate",
        )
        for expected, produced in zip(golden["scenarios"], actual):
            self.assertEqual(
                produced["decision"], expected["decision"],
                msg=(f"decision drift at scenario '{expected['name']}': "
                     f"expected {expected['decision']}, got {produced['decision']}. "
                     f"If the change is intentional, regenerate the golden with "
                     f"{REGEN_ENV}=1 python -m unittest tests.test_gastronome_golden"),
            )

    def test_scenarios_cover_required_categories(self):
        """护栏的护栏：场景集必须覆盖 issue #12 要求的决策类别."""
        strategy = GastronomeStrategy()
        strategy.on_game_start(RECIPES)
        produced_types = {
            type(strategy.decide(s["state"])).__name__ if strategy.decide(s["state"])
            else "NoneDecision"
            for s in _build_scenarios()
        }
        required = {
            "ServeOrderAction",       # 可送餐
            "ClearCookerAction",      # 清理过期
            "ClearAssemblyAction",    # 抢占组装
            "MoveToAssemblyAction",   # 移动到组装站
            "CookAction",             # 并行烹饪 / 预烹饪
            "AddCondimentAction",     # 调料
            "PullFromStockpileAction",  # 库存取
            "MoveToStockpileAction",  # 库存放
            "NoneDecision",           # 空转
        }
        self.assertEqual(required, produced_types)


if __name__ == "__main__":
    unittest.main()
