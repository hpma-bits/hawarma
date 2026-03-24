"""
Unified Scheduler

地位：游戏的唯一决策中心，决定下一刻应该执行什么动作。

输入：GameState快照、所有可用资源状态、SessionState
输出：Action列表供Executor执行

调度策略（三阶段）：
  1. Finish: 完成可上菜的订单（rush 优先）
  2. MoveToAssembly: 将 cooker 上已完成烹饪的食材移到组装站
  3. Cook: 为所有待处理订单启动烹饪，填满所有空闲 cooker

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

import asyncio
from collections import Counter

from loguru import logger

from hawarma.actions import (
    Action,
    CookIngredient,
    FinishOrder,
    PullFromStockpile,
)
from hawarma.models import OrderStage
from hawarma.scheduler.order_policy import OrderPolicy
from hawarma.scheduler.stockpile_policy import StockpilePolicy
from hawarma.state import GameState, SessionState


class Scheduler:
    """
    The only brain in the system.

    Three-phase scheduling each tick:
    1. Finish ready orders (rush first)
    2. Move cooked ingredients to assembly
    3. Start cooking on all free cookers (cross-order, rush first)

    The scheduler returns a list of actions to execute.
    """

    def __init__(
        self,
        game_state: GameState,
        session_state: SessionState,
        order_policy: OrderPolicy | None = None,
        stockpile_policy: StockpilePolicy | None = None,
    ):
        self.game_state = game_state
        self.session_state = session_state
        self.order_policy = order_policy or OrderPolicy()
        self.stockpile_policy = stockpile_policy or StockpilePolicy(session_state)

    def get_next_actions(self) -> list[Action]:
        """
        Main entry point. Called by app._tick_loop() each tick.

        Animation window: only serve (finish) is blocked. Move and cook
        can proceed during slot animation.

        Caller holds state.lock. Scheduler reads state and returns actions.
        """
        state = self.game_state
        actions: list[Action] = []

        # Phase 1: 移动 cooker 上已完成烹饪的食材到组装站（不受动画限制）
        actions.extend(self._get_move_actions(state))

        # Phase 2: 从库存拉取食材到组装站（不受动画限制）
        actions.extend(self._get_pull_actions(state))

        # Phase 3: 完成可上菜的订单（动画窗口内禁入）
        if state.is_ui_stable(asyncio.get_event_loop().time()):
            actions.extend(self._get_finish_actions(state))

        # Phase 4: 为所有订单启动烹饪（不受动画限制）
        actions.extend(self._get_cook_actions(state))

        return actions

    def _get_finish_actions(self, state: GameState) -> list[Action]:
        """
        Phase 1: Finish orders ready for seasoning (rush first).
        """
        ready_orders = self.order_policy.get_orders_needing_seasoning(state)

        for slot_idx, order in ready_orders:
            owns_assembly = state.is_assembly_owned_by(order.order_id)
            if not owns_assembly and not state.is_assembly_free():
                continue

            reserved = state.reserve_finish(order.order_id)
            if not reserved:
                continue

            return [
                FinishOrder(
                    order_id=order.order_id,
                    pickup_slot=slot_idx,
                )
            ]

        return []

    def _get_move_actions(self, state: GameState) -> list[Action]:
        """
        Phase 2: Move cooked ingredients from cookers to assembly.

        For each cooker in cooked_waiting_assembly state:
        1. Reserve assembly for the order if not already owned
        2. Generate move action
        3. If assembly is busy, skip (retry next tick)
        """
        actions: list[Action] = []

        for cooker_name, cooker_state in state.cookers.items():
            if not cooker_state.cooked_waiting_assembly:
                continue
            if cooker_state.ingredient_name is None:
                continue

            order_id = cooker_state.order_id
            if order_id is None:
                continue

            # 检查/获取组装站归属
            owns_assembly = state.is_assembly_owned_by(order_id)
            if not owns_assembly:
                if not state.is_assembly_free():
                    continue  # assembly 忙，下个 tick 重试
                reserved = state.reserve_assembly(order_id)
                if not reserved:
                    continue

            # 生成 move action
            actions.append(
                CookIngredient(
                    order_id=order_id,
                    ingredient_name=cooker_state.ingredient_name,
                    cooker_name=cooker_name,
                    destination="assembly",
                    _move_only=True,
                )
            )

        return actions

    def _get_pull_actions(self, state: GameState) -> list[Action]:
        """
        Phase 2b: Pull cooked ingredients from stockpile to assembly.

        For each order missing ingredients, check if stockpile has them.
        Generate PullFromStockpile if assembly is available for the order.
        """
        actions: list[Action] = []
        pulled: set[str] = set()

        pending_orders = self.order_policy.get_sorted_active_orders(state)

        for slot_idx, order in pending_orders:
            if order.current_stage not in (
                OrderStage.PENDING,
                OrderStage.HEATING,
                OrderStage.OFF_HEAT,
            ):
                continue

            required = Counter(order.recipe.raw_ingredients)
            at_station = Counter(state.assembly.ingredients)

            for ingredient, count in required.items():
                at = at_station.get(ingredient, 0)
                needed = count - at
                if needed <= 0:
                    continue
                if ingredient in pulled:
                    continue

                stockpile_count = state.get_stock_count(ingredient)
                if stockpile_count <= 0:
                    continue

                # 检查 assembly 归属
                owns_assembly = state.is_assembly_owned_by(order.order_id)
                if not owns_assembly:
                    if not state.is_assembly_free():
                        continue
                    if not state.reserve_assembly(order.order_id):
                        continue

                slot = self.stockpile_policy.get_stockpile_slot_for(ingredient)
                if slot is None:
                    continue

                if state.decrement_stock(ingredient):
                    actions.append(
                        PullFromStockpile(
                            order_id=order.order_id,
                            ingredient_name=ingredient,
                            stockpile_slot=slot,
                        )
                    )
                    pulled.add(ingredient)

        return actions

    def _get_cook_actions(self, state: GameState) -> list[Action]:
        """
        Phase 3: Start cooking on all free cookers (cross-order).

        Cooking does NOT require assembly. All pending orders can start
        cooking simultaneously on different cookers. Assembly is only
        needed when moving ingredients (Phase 2).
        """
        actions: list[Action] = []
        assigned_cookers: set[str] = set()

        pending_orders = self.order_policy.get_sorted_active_orders(state)

        for slot_idx, order in pending_orders:
            if order.current_stage not in (
                OrderStage.PENDING,
                OrderStage.HEATING,
            ):
                continue

            # 标记为 HEATING
            if order.current_stage == OrderStage.PENDING:
                order.current_stage = OrderStage.HEATING

            # 计算缺失食材
            required = Counter(order.recipe.raw_ingredients)
            at_station = Counter(state.assembly.ingredients)

            for ingredient, count in required.items():
                at = at_station.get(ingredient, 0)
                needed = count - at

                for _ in range(needed):
                    # 优先使用库存
                    if self.stockpile_policy.should_use_stockpile(
                        ingredient, state
                    ):
                        slot = self.stockpile_policy.get_stockpile_slot_for(
                            ingredient
                        )
                        if slot is not None:
                            if state.decrement_stock(ingredient):
                                actions.append(
                                    PullFromStockpile(
                                        order_id=order.order_id,
                                        ingredient_name=ingredient,
                                        stockpile_slot=slot,
                                    )
                                )
                                continue

                    # 找空闲 cooker（跳过等待 assembly 的 cooker）
                    cooker = self.session_state.get_cooker_for(
                        ingredient, order.recipe
                    )
                    if cooker is None:
                        continue
                    cooker_state = state.cookers.get(cooker)
                    if cooker_state is not None and cooker_state.busy:
                        continue  # 正在烹饪或等待 assembly
                    if cooker in assigned_cookers:
                        continue

                    assigned_cookers.add(cooker)
                    actions.append(
                        CookIngredient(
                            order_id=order.order_id,
                            ingredient_name=ingredient,
                            cooker_name=cooker,
                            destination="assembly",
                        )
                    )

        return actions
