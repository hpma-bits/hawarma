"""
Executor

地位：执行 UI 动作并更新状态，是游戏的唯一物理操作层。

设计原则：
1. Executor 只负责执行物理 UI 操作（swipe）和提交结果性状态。
2. 所有决策和资源预留由 Scheduler 完成，Executor 不做重复检查。
3. UI 成功后提交结果性状态（如入 assembly、扣库存、完成订单）。
4. Executor 负责 reservation 生命周期释放（release_prep/release_finish）。
5. 不在 state 中保存临时计算结果；临时变量仅存在于当前执行上下文。

输入：Action 对象（已由 Scheduler 预留资源）
输出：动作执行结果、状态更新

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的 md
"""

import asyncio
from collections import Counter
from typing import Any

from loguru import logger

from hawarma.actions import Action, CookIngredient, FinishOrder, PullFromStockpile
from hawarma.models import Order, OrderStage
from hawarma.services.resource_guards import ResourceGuards
from hawarma.state import GameState, SessionState
from hawarma.ui_operation_manager import UIOperationManager


class Executor:
    """
    Physical action executor.

    Responsibilities:
    - Execute serialized UI gestures through UIOperationManager
    - Update GameState safely under lock
    - Own reservation lifecycle for prep / finish
    - Advance order stages based on actual execution success
    """

    def __init__(
        self,
        game_state: GameState,
        session_state: SessionState,
        raw_ingredients_mapping: dict[str, tuple[int, int]],
        cookers_mapping: dict[str, tuple[int, int]],
        condiments_mapping: dict[str, tuple[int, int]],
        assembly_station_pos: tuple[int, int],
        pickup_stations_pos: list[tuple[int, int]],
        stockpile_positions: list[tuple[int, int]],
        ui_manager: UIOperationManager,
        guards: ResourceGuards,
        ordered_recipes: list[Any],
    ):
        self.game_state = game_state
        self.session = session_state

        self.raw_ingredients = raw_ingredients_mapping
        self.cookers = cookers_mapping
        self.condiments = condiments_mapping
        self.assembly_station = assembly_station_pos
        self.pickup_stations = pickup_stations_pos
        self.stockpile_positions = stockpile_positions

        self.ui = ui_manager
        self.guards = guards
        self.ordered_recipes = ordered_recipes

        self._cooker_clear_margin = 5.0

    async def execute(self, action: Action) -> bool:
        try:
            match action:
                case CookIngredient():
                    return await self._cook_ingredient(action)
                case PullFromStockpile():
                    return await self._pull_from_stockpile(action)
                case FinishOrder():
                    return await self._finish_order(action)
                case _:
                    logger.warning(f"Unknown action type: {type(action)}")
                    return False
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"Action {type(action).__name__} failed: {e}")
            return False

    async def execute_batch(self, actions: list[Action]) -> None:
        """
        Execute a batch of actions. CookIngredient actions on different
        cookers are executed concurrently (asyncio.gather).
        """
        cook_actions = [a for a in actions if isinstance(a, CookIngredient)]
        other_actions = [a for a in actions if not isinstance(a, CookIngredient)]

        if cook_actions:
            await self._cook_parallel(cook_actions)

        for action in other_actions:
            success = await self.execute(action)
            if not success:
                logger.warning(f"Action skipped/failed: {action}")

    async def _cook_ingredient(self, action: CookIngredient) -> bool:
        """
        Execute a single cooking action (blocking, for backward compatibility).
        For concurrent cooking, use _cook_parallel().
        """
        return await self._cook_single(action)

    async def _cook_parallel(self, actions: list[CookIngredient]) -> None:
        """
        Execute multiple CookIngredient actions concurrently.

        Different cookers cook in parallel:
        - Each task acquires its cooker lock for the full duration
        - UI lock is only held briefly for swipes
        - Cooking waits (asyncio.sleep) overlap across cookers

        Assembly station is serialized naturally:
        - First ingredient to finish acquires assembly lock
        - Others wait until released
        """
        tasks = [self._cook_single(a) for a in actions]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"Cook action failed: {actions[i]}: {result}")
            elif not result:
                logger.debug(f"Cook action skipped: {actions[i]}")

    async def _cook_single(self, action: CookIngredient) -> bool:
        """
        Execute one cooking task. Designed for concurrent execution.

        If the cooker already has a ready ingredient (ready_at <= now),
        skip cooking and only move to assembly/stockpile.
        """
        cooker_name = action.cooker_name
        ingredient = action.ingredient_name
        destination = action.destination
        order_id = action.order_id
        stockpile_slot = getattr(action, "stockpile_slot", None)
        move_only = getattr(action, "_move_only", False)

        acquired = await self.guards.acquire_cooker(cooker_name)
        if not acquired:
            return False

        try:
            if move_only:
                # 食材已烹饪完成，直接移到目标位置
                return await self._move_from_cooker(
                    cooker_name, ingredient, destination,
                    order_id, stockpile_slot,
                )

            # 获取烹饪时长并占用 cooker
            async with self.game_state.lock:
                order = (
                    self.game_state.get_order_by_id(order_id)
                    if order_id is not None
                    else None
                )
                duration = self._resolve_cook_duration(ingredient, order)
                if duration is None:
                    return False

                # 检查是否已经烹饪完成（之前被跳过的 move）
                cooker_state = self.game_state.cookers.get(cooker_name)
                if (
                    cooker_state
                    and cooker_state.busy
                    and cooker_state.ingredient_name == ingredient
                    and cooker_state.ready_at is not None
                    and asyncio.get_event_loop().time() >= cooker_state.ready_at
                ):
                    # 已烹饪完成，直接移动
                    return await self._move_from_cooker(
                        cooker_name, ingredient, destination,
                        order_id, stockpile_slot,
                    )

                now = asyncio.get_event_loop().time()
                occupied = self.game_state.occupy_cooker(
                    cooker_name=cooker_name,
                    ingredient_name=ingredient,
                    order_id=order_id,
                    destination=destination,
                    ready_at=now + duration,
                    clear_by=now + duration + self._cooker_clear_margin,
                )
                if not occupied:
                    return False

            cooker_pos = self.cookers[cooker_name]
            raw_pos = self.raw_ingredients[ingredient]

            # Swipe 1: 食材 → 灶台（短暂持有 UI lock）
            await self.ui.swipe(raw_pos, cooker_pos, duration=0.1)

            # 烹饪等待（不持任何锁，允许其他任务并发）
            await asyncio.sleep(duration)

            if destination == "assembly":
                # Swipe 2: 灶台 → 组装站
                async with self.game_state.lock:
                    can_move = (
                        self.game_state.is_assembly_free()
                        or self.game_state.is_assembly_owned_by(order_id)
                    )

                if not can_move:
                    # assembly 忙，fallback 到 stockpile
                    async with self.game_state.lock:
                        current_count = self.game_state.get_stock_count(ingredient)
                        can_stockpile = current_count < 5  # MAX_STOCKPILE

                    if can_stockpile:
                        # 找第一个 stockpile slot 位置
                        stockpile_pos = self.stockpile_positions[0]
                        await self.ui.swipe(
                            cooker_pos, stockpile_pos, duration=0.1,
                        )
                        async with self.game_state.lock:
                            self.game_state.increment_stock(ingredient)
                        return True

                    # 没有 stockpile 空间，标记等待
                    async with self.game_state.lock:
                        cooker_st = self.game_state.cookers.get(cooker_name)
                        if cooker_st:
                            cooker_st.cooked_waiting_assembly = True
                    return False

                await self.ui.swipe(
                    cooker_pos, self.assembly_station, duration=0.1
                )
                await asyncio.sleep(0.05)

                async with self.game_state.lock:
                    order = self.game_state.get_order_by_id(order_id)
                    if order is None or order.done:
                        return False

                    if not self.game_state.is_assembly_owned_by(order_id):
                        if not self.game_state.reserve_assembly(order_id):
                            return False

                    added = self.game_state.add_to_assembly(
                        order_id, ingredient
                    )
                    if not added:
                        return False
                    self._check_and_transition_ready(order_id)

            else:
                # Swipe 2: 灶台 → 库存
                if stockpile_slot is None:
                    return False
                await self.ui.swipe(
                    cooker_pos,
                    self.stockpile_positions[stockpile_slot],
                    duration=0.1,
                )
                await asyncio.sleep(0.05)
                async with self.game_state.lock:
                    self.game_state.increment_stock(ingredient)

            return True

        except Exception as e:
            logger.exception(f"Cook single failed: {e}")
            return False
        finally:
            # 如果在等待 assembly，不释放 cooker state（保留食材信息）
            async with self.game_state.lock:
                cooker_st = self.game_state.cookers.get(cooker_name)
                if cooker_st and not cooker_st.cooked_waiting_assembly:
                    self.game_state.release_cooker(cooker_name)
            self.guards.release_cooker(cooker_name)

    async def _move_from_cooker(
        self,
        cooker_name: str,
        ingredient: str,
        destination: str,
        order_id: int | None,
        stockpile_slot: int | None,
    ) -> bool:
        """
        Move an already-cooked ingredient from cooker to assembly or stockpile.
        Called when ingredient is waiting for assembly (cooked_waiting_assembly).
        """
        cooker_pos = self.cookers[cooker_name]

        if destination == "assembly":
            await self.ui.swipe(
                cooker_pos, self.assembly_station, duration=0.1
            )
            await asyncio.sleep(0.05)

            async with self.game_state.lock:
                order = self.game_state.get_order_by_id(order_id)
                if order is None or order.done:
                    return False
                added = self.game_state.add_to_assembly(
                    order_id, ingredient
                )
                if not added:
                    return False
                self._check_and_transition_ready(order_id)
                # 移动成功，释放 cooker
                self.game_state.release_cooker(cooker_name)

        else:
            if stockpile_slot is None:
                return False
            await self.ui.swipe(
                cooker_pos,
                self.stockpile_positions[stockpile_slot],
                duration=0.1,
            )
            await asyncio.sleep(0.05)
            async with self.game_state.lock:
                self.game_state.increment_stock(ingredient)
                self.game_state.release_cooker(cooker_name)

        return True

    async def _pull_from_stockpile(self, action: PullFromStockpile) -> bool:
        """
        Execute stockpile pull action. Scheduler 已完成所有决策和资源预留。
        Executor 只负责：
        1. 获取物理 stockpile slot guard
        2. 执行 UI swipe 操作
        3. UI 成功后提交结果状态并释放 prep
        """
        slot = action.stockpile_slot
        ingredient = action.ingredient_name
        order_id = action.order_id

        # 1. 获取物理资源锁（防止同一 slot 被并发使用）
        acquired = await self.guards.acquire_stockpile_slot(slot)
        if not acquired:
            logger.debug(f"Stockpile guard busy: slot={slot}")
            return False

        try:
            # 2. 执行 UI 操作（Scheduler 已预留所有资源）
            src = self.stockpile_positions[slot]
            await self.ui.swipe(src, self.assembly_station, duration=0.1)
            await asyncio.sleep(0.1)

            # 3. UI 成功后提交结果状态
            async with self.game_state.lock:
                order = self.game_state.get_order_by_id(order_id)
                if order is None or order.done:
                    logger.warning(
                        f"Order disappeared before stockpile add: {order_id}"
                    )
                    return False

                added = self.game_state.add_to_assembly(order_id, ingredient)
                if not added:
                    logger.warning(
                        f"Failed to add stockpile ingredient to assembly: order={order_id}, ingredient={ingredient}"
                    )
                    return False

                self._check_and_transition_ready(order_id)
                self.game_state.release_prep(order_id)

            return True

        finally:
            self.guards.release_stockpile_slot(slot)

    async def _finish_order(self, action: FinishOrder) -> bool:
        """
        Execute finish order action. Scheduler 已完成所有决策和资源预留。
        Executor 只负责：
        1. 执行 season UI 操作
        2. 执行 swipe 到 pickup slot
        3. UI 成功后提交完成状态并释放所有 reservation
        """
        order_id = action.order_id
        pickup_slot = action.pickup_slot

        try:
            # 1. 执行 season 操作
            async with self.game_state.lock:
                order = self.game_state.get_order_by_id(order_id)
                if order is None:
                    logger.warning(f"Order missing during finish: {order_id}")
                    return False

            await self._season(order)

            # 2. 执行 UI 操作
            # 位移后重新查询订单当前 slot，确保送餐目标正确
            async with self.game_state.lock:
                serve_slot = self.game_state.get_order_slot_index_by_id(order_id)
            if serve_slot < 0:
                serve_slot = pickup_slot  # fallback

            await self.ui.swipe(
                self.assembly_station,
                self.pickup_stations[serve_slot],
                duration=0.2,
            )
            await asyncio.sleep(0.3)

            # 3. UI 成功后提交完成状态
            now = asyncio.get_event_loop().time()

            async with self.game_state.lock:
                order = self.game_state.get_order_by_id(order_id)
                if order is None:
                    logger.warning(f"Order missing during finish commit: {order_id}")
                    return False

                order.done = True
                order.current_stage = OrderStage.COMPLETED
                order.served_ts = now

                self.game_state.record_order_completion(now)
                self.game_state.release_assembly_owner(order_id)
                self.game_state.clear_assembly_contents()

                self.game_state.release_finish(order_id)
                self.game_state.release_prep(order_id)
                self.game_state.clear_order_reservations(order_id)

                self.game_state.advance_slots()
                self.game_state.timestamps.slot_animation_until = now + 1.5
                self.game_state.timestamps.ui_cooldown_until = now + 0.3

            logger.info(f"Order {order_id} served to slot {serve_slot}")
            return True

        except Exception:
            async with self.game_state.lock:
                self.game_state.release_finish(order_id)
            raise

    async def _season(self, order: Order) -> None:
        for condiment, count in order.condiment_preference.items():
            if condiment not in self.condiments:
                logger.warning(f"Condiment not mapped: {condiment}")
                continue

            for _ in range(count):
                await self.ui.swipe(
                    self.condiments[condiment],
                    self.assembly_station,
                    duration=0.1,
                )
                await asyncio.sleep(0.05)

    def _check_and_transition_ready(self, order_id: int) -> None:
        """
        If all required ingredients for this order have arrived at assembly,
        transition the order to READY_TO_SEASON.
        """
        order = self.game_state.get_order_by_id(order_id)
        if order is None or order.done:
            return

        if order.current_stage not in {
            OrderStage.PENDING,
            OrderStage.HEATING,
            OrderStage.OFF_HEAT,
        }:
            return

        required = Counter(order.recipe.raw_ingredients)
        at_assembly = Counter(order.ingredients_at_assembly)

        if all(at_assembly[name] >= count for name, count in required.items()):
            order.current_stage = OrderStage.READY_TO_SEASON
            logger.info(f"Order {order_id} ready to season")
        else:
            order.current_stage = OrderStage.HEATING

    def _resolve_cook_duration(
        self, ingredient: str, order: Order | None
    ) -> float | None:
        """
        Resolve cook duration with order recipe preferred, then global fallback for stockpile refill.
        """
        if order is not None:
            duration = self.session.get_cook_duration(ingredient, order.recipe)
            if duration is not None:
                return duration

        for recipe in self.ordered_recipes:
            if ingredient in recipe.raw_ingredients:
                idx = recipe.raw_ingredients.index(ingredient)
                return recipe.cook_durations[idx]

        return None
