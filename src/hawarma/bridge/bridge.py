"""
真实游戏桥接器

地位：协调 Agent、环境、扫描器和 UI 执行器
      管理游戏生命周期，运行扫描和决策循环

输入：配置对象、配方列表
输出：游戏统计结果

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

import asyncio
import time

from airtest.core.api import G
from loguru import logger

from hawarma.config import AppConfig
from hawarma.models import Recipe

from .assembly_verifier import AssemblyVerifier
from .base_environment import OrderInfo
from .environment import GameEnvironment
from .scanner import OrderScanner
from .ui_runner import UIRunner


class RealGameBridge:
    """
    真实游戏桥接器

    管理游戏生命周期，协调各个组件：
    - OrderScanner: 检测订单
    - GameEnvironment: 追踪状态
    - UIRunner: 执行 UI 操作
    - Agent: 决策逻辑
    """

    def __init__(self, config: AppConfig, recipes: list[Recipe]):
        self.config = config
        self.recipes = recipes
        self._recipe_by_slug = {r.slug: r for r in recipes}

        self.env = GameEnvironment(
            cooker_names=list(config.cookers),
            stockpile_slots=len(config.screen.stockpile_positions),
            game_duration=config.episode_duration,
            recipes={r.slug: r for r in recipes},
            cooker_retention=config.game.cooker_retention,
        )

        self.scanner = OrderScanner(config, recipes)
        self.ui = UIRunner(config, recipes)
        self.verifier = AssemblyVerifier(config)
        self.agent = None

        self._running = False
        self._game_started = False
        self._executing_action = False  # 是否正在执行 UI 操作

    def set_agent(self, agent) -> None:
        """设置 Agent"""
        self.agent = agent

    async def run(self) -> dict:
        """
        运行游戏

        Returns:
            游戏统计结果
        """
        if self.agent is None:
            raise RuntimeError("Agent not set. Call set_agent() first.")

        # 1. 等待游戏开始
        await self._wait_for_game_start()

        # 2. 启动扫描和决策循环
        self._running = True

        try:
            await asyncio.gather(
                self._scan_loop(),
                self._timeout_loop(),
                self._agent_loop(),
            )
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

        # 3. 返回统计
        return self.agent.get_stats()

    async def _wait_for_game_start(self) -> None:
        """等待游戏开始：检测 timer，然后等待 3 秒"""
        logger.info("Waiting for game start (timer detection)...")

        while True:
            if await self.scanner.detect_timer():
                logger.info("Timer detected, waiting 3 seconds...")
                await asyncio.sleep(3)
                self.env.start_game()
                self._game_started = True
                logger.info("Game started!")
                break
            await asyncio.sleep(0.5)

    # ========================================================================
    # 扫描循环
    # ========================================================================

    async def _scan_loop(self) -> None:
        """订单扫描循环（自适应频率），动画窗口期间暂停"""
        while self._running and not self.env.is_game_over():
            try:
                if not self.env.is_in_animation_window():
                    await self._sync_orders_from_scan()

                interval = self._compute_scan_interval()
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"Scan loop error: {e}")
                await asyncio.sleep(1.0)

    def _compute_scan_interval(self) -> float:
        """
        根据游戏状态自适应计算扫描间隔。

        策略：
        - 有灶台空闲且有活跃订单：快速扫描（0.4s），尽快发现新订单启动烹饪
        - 所有灶台都在忙：中速扫描（0.5s），等烹饪完成再处理
        - 无活跃订单：中速扫描（0.5s），等待新订单出现
        """
        active_orders = [o for o in self.env.orders if o and not o.done]
        free_cookers = [c for c in self.env.cookers.values() if not c.busy]

        if not active_orders:
            return 0.5

        if free_cookers:
            return 0.4

        return 0.5

    async def _sync_orders_from_scan(self) -> None:
        """
        强制将 env.orders 与扫描结果同步。

        策略：
        1. 检查当前订单是否有 done=True 的，有则跳过
        2. 按扫描结果重建 env.orders
        3. 忽略 None 的 slot（表示该位置没有订单）
        """
        start_time = asyncio.get_event_loop().time()
        scanned = await self.scanner.scan_new_orders()
        scan_duration = asyncio.get_event_loop().time() - start_time

        # 构建扫描结果的 slot -> order 映射
        scan_by_slot: dict[int, tuple[str, bool]] = {}  # type: ignore
        for d in scanned:
            scan_by_slot[d.slot_idx] = (d.recipe_slug, d.is_rush)

        # 直接重建 env.orders：从左到右填充扫描到的订单
        new_orders: list[OrderInfo | None] = []
        for slot_idx in range(4):
            if slot_idx in scan_by_slot:
                recipe_slug, is_rush = scan_by_slot[slot_idx]
                now = time.time()
                timeout = 40.0 if is_rush else 70.0
                order = OrderInfo(
                    order_id=self.env._next_order_id,
                    recipe_slug=recipe_slug,
                    is_rush=is_rush,
                    created_at=now,
                    timeout_at=now + timeout,
                    done=False,
                )
                self.env._next_order_id += 1
                new_orders.append(order)
            else:
                new_orders.append(None)

        # 直接替换
        self.env._orders = new_orders

        self.env._log_orders_state("sync")
        logger.debug(
            f"[t={self.env.time:.1f}s] Scan completed: {len(scanned)} detected, duration={scan_duration * 1000:.1f}ms"
        )

    # ========================================================================
    # 超时检测循环
    # ========================================================================

    async def _timeout_loop(self) -> None:
        """订单超时检测循环（每 0.3s）"""
        while self._running and not self.env.is_game_over():
            try:
                timed_out = self.env.check_and_remove_timed_out_orders()
                for order_id in timed_out:
                    self.agent.on_order_timeout(order_id)
                # G.DEVICE.snapshot()  # 用于刷新缓存的截图
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"Timeout loop error: {e}")
                await asyncio.sleep(0.3)

    # ========================================================================
    # Agent 决策循环
    # ========================================================================

    async def _agent_loop(self) -> None:
        """Agent 决策循环（每 0.05s），带停滞检测，动画窗口期间允许烹饪"""
        while self._running and not self.env.is_game_over():
            try:
                if self._executing_action:
                    await asyncio.sleep(0.05)
                    continue

                in_animation = self.env.is_in_animation_window()

                action = await asyncio.to_thread(self.agent.step_with_diagnostics)
                if action:
                    action_type = type(action).__name__
                    if in_animation and action_type == "ServeOrderAction":
                        await asyncio.sleep(0.05)
                        continue

                    self.agent.stats["actions_taken"] += 1
                    self._executing_action = True
                    await self._execute_action(action)
                    self._executing_action = False
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Agent loop error: {e}")
                self._executing_action = False
                await asyncio.sleep(0.05)

    # ========================================================================
    # 动作执行
    # ========================================================================

    async def _execute_action(self, action) -> None:
        """执行 Agent 动作"""
        if self.env.is_game_over():
            logger.info(
                f"[t={self.env.time:.1f}s] Game over, skipping action: {type(action).__name__}"
            )
            self._running = False
            return

        action_type = type(action).__name__
        try:
            match action_type:
                case "CookAction":
                    await self._exec_cook(action)
                case "MoveToAssemblyAction":
                    await self._exec_move_to_assembly(action)
                case "MoveToStockpileAction":
                    await self._exec_move_to_stockpile(action)
                case "PullFromStockpileAction":
                    await self._exec_pull_from_stockpile(action)
                case "AddCondimentAction":
                    await self._exec_add_condiment(action)
                case "ServeOrderAction":
                    await self._exec_serve_order(action)
                case "ClearCookerAction":
                    await self._exec_clear_cooker(action)
                case "ClearAssemblyAction":
                    await self._exec_clear_assembly(action)
                case _:
                    logger.warning(f"Unknown action: {action_type}")
        except Exception as e:
            logger.error(f"Failed to execute {action_type}: {e}")

    async def _exec_cook(self, action) -> None:
        """烹饪"""
        await self.ui.cook(action.ingredient, action.cooker)
        self.env.start_cooking(action.ingredient, action.cooker, action.duration)
        logger.info(
            f"[t={self.env.time:.1f}s] Cooking {action.ingredient} on {action.cooker} ({action.duration}s)"
        )

    async def _exec_move_to_assembly(self, action) -> None:
        """移到组装站"""
        await self.ui.move_to_assembly(action.cooker)
        cooker_state = self.env.cookers.get(action.cooker)
        if cooker_state:
            ingredient = cooker_state.ingredient_name
            order_id = getattr(action, "order_id", None)
            recipe_slug = None
            if order_id:
                order = self.env.get_order_by_id(order_id)
                if order:
                    recipe_slug = order.recipe_slug
            self.env.add_to_assembly(ingredient, action.cooker, order_id, recipe_slug)
            self.env.clear_cooker(action.cooker)
            logger.info(
                f"[t={self.env.time:.1f}s] Moved {ingredient} from {action.cooker} -> assembly"
            )

    async def _exec_move_to_stockpile(self, action) -> None:
        """移到库存"""
        await self.ui.move_to_stockpile(action.cooker, action.slot)
        cooker = self.env.cookers.get(action.cooker)
        ingredient = cooker.ingredient_name if cooker else "?"
        self.env.move_to_stockpile(action.cooker, action.slot)
        logger.info(
            f"[t={self.env.time:.1f}s] Stored {ingredient} from {action.cooker} -> {action.slot}"
        )

    async def _exec_pull_from_stockpile(self, action) -> None:
        """从库存取用"""
        await self.ui.pull_from_stockpile(action.slot)
        self.env.pull_from_stockpile(action.slot)
        logger.info(
            f"[t={self.env.time:.1f}s] Pulled {action.ingredient} from {action.slot} -> assembly"
        )

    async def _exec_add_condiment(self, action) -> None:
        """添加调料"""
        await self.ui.add_condiment(action.condiment)
        self.env.add_condiment(action.condiment)
        logger.info(f"[t={self.env.time:.1f}s] Added condiment {action.condiment}")

    async def _exec_serve_order(self, action) -> None:
        """送餐（带验证和重试）"""
        success_slot = await self._serve_with_verify(action.slot_idx)

        if success_slot is not None:
            self.agent.on_order_served()
            self.env.clear_assembly()
            self.env.set_animation_window(1.5)
        else:
            logger.warning(
                f"[t={self.env.time:.1f}s] Serve failed after all retries. "
                f"Assembly cleared."
            )
            self.env.clear_assembly()

    async def _serve_with_verify(
        self, slot_idx: int, max_retries: int = 2
    ) -> int | None:
        """
        执行送餐并验证是否成功。

        新方案：使用快速重试机制取代扫描匹配
        1. 执行 serve swipe
        2. 多点 snapshot 验证（4张，用最后一张）
        3. 失败后快速重试所有 slot（0,1,2,3）
        4. 全部失败后清空 assembly

        Returns:
            成功的 slot_idx，如果失败返回 None
        """
        # 第一次尝试：原始 slot
        await self.ui.serve_order(slot_idx)
        if await self._verify_with_multi_snapshot():
            return slot_idx

        logger.warning(
            f"[t={self.env.time:.1f}s] Serve verification failed. "
            f"Assembly still has: {self.env.assembly.ingredients_cookers}"
        )

        # 快速重试所有 slot（0,1,2,3），跳过已尝试的
        for try_slot in range(4):
            if try_slot == slot_idx:
                continue

            await asyncio.sleep(0.05)
            await self.ui.serve_order(try_slot)
            if await self._verify_with_multi_snapshot():
                logger.info(
                    f"[t={self.env.time:.1f}s] Serve succeeded at slot {try_slot}"
                )
                return try_slot

        # 全部失败，清空 assembly
        logger.warning(
            f"[t={self.env.time:.1f}s] All serve attempts failed. Clearing assembly."
        )
        await self.ui.clear_assembly()
        self.env.clear_assembly()
        return None

    async def _verify_with_multi_snapshot(self) -> bool:
        """
        多点 snapshot 验证 assembly 是否为空。

        流程：连续获取 4 张 snapshot（间隔 0.05s），用第 4 张验证
        """
        for _ in range(3):
            G.DEVICE.snapshot()

        return self.verifier.is_assembly_empty()

    async def _exec_clear_cooker(self, action) -> None:
        """清理灶台"""
        await self.ui.clear_cooker(action.cooker)
        self.env.clear_cooker(action.cooker)
        logger.info(f"[t={self.env.time:.1f}s] Cleared cooker {action.cooker}")

    async def _exec_clear_assembly(self, action) -> None:
        """清空组装站"""
        discarded = self.env.assembly.ingredients_cookers.copy()
        await self.ui.clear_assembly()
        self.env.clear_assembly()
        logger.info(
            f"[t={self.env.time:.1f}s] Cleared assembly (discarded: {discarded})"
        )

    def stop(self) -> None:
        """停止游戏"""
        self._running = False
