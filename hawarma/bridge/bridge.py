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

from loguru import logger

from hawarma.config import AppConfig
from hawarma.models import Recipe

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
        )

        self.scanner = OrderScanner(config, recipes)
        self.ui = UIRunner(config, recipes)
        self.agent = None

        self._running = False
        self._game_started = False

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
            if self.scanner.detect_timer():
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
        """订单扫描循环（每 0.5s）"""
        while self._running and not self.env.is_game_over():
            try:
                if not self.env.is_in_animation_window():
                    new_orders = self.scanner.scan_new_orders()
                    for order in new_orders:
                        self.env.add_order(
                            slot_idx=order.slot_idx,
                            recipe_slug=order.recipe_slug,
                            is_rush=order.is_rush,
                        )
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Scan loop error: {e}")
                await asyncio.sleep(0.5)

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
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"Timeout loop error: {e}")
                await asyncio.sleep(0.3)

    # ========================================================================
    # Agent 决策循环
    # ========================================================================

    async def _agent_loop(self) -> None:
        """Agent 决策循环（每 0.1s）"""
        while self._running and not self.env.is_game_over():
            try:
                action = self.agent.step()
                if action:
                    self.agent.stats["actions_taken"] += 1
                    await self._execute_action(action)
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Agent loop error: {e}")
                await asyncio.sleep(0.1)

    # ========================================================================
    # 动作执行
    # ========================================================================

    async def _execute_action(self, action) -> None:
        """执行 Agent 动作"""
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
        logger.info(f"[t={self.env.time:.1f}s] Cooking {action.ingredient} on {action.cooker} ({action.duration}s)")

    async def _exec_move_to_assembly(self, action) -> None:
        """移到组装站"""
        await self.ui.move_to_assembly(action.cooker)
        cooker_state = self.env.cookers.get(action.cooker)
        if cooker_state:
            ingredient = cooker_state.ingredient_name
            order_id = getattr(action, 'order_id', None)
            recipe_slug = None
            if order_id:
                order = self.env.get_order_by_id(order_id)
                if order:
                    recipe_slug = order.recipe_slug
            self.env.add_to_assembly(ingredient, action.cooker, order_id, recipe_slug)
            self.env.clear_cooker(action.cooker)
            logger.info(f"[t={self.env.time:.1f}s] Moved {ingredient} from {action.cooker} -> assembly")

    async def _exec_move_to_stockpile(self, action) -> None:
        """移到库存"""
        await self.ui.move_to_stockpile(action.cooker, action.slot)
        cooker = self.env.cookers.get(action.cooker)
        ingredient = cooker.ingredient_name if cooker else "?"
        self.env.move_to_stockpile(action.cooker, action.slot)
        logger.info(f"[t={self.env.time:.1f}s] Stored {ingredient} from {action.cooker} -> {action.slot}")

    async def _exec_pull_from_stockpile(self, action) -> None:
        """从库存取用"""
        await self.ui.pull_from_stockpile(action.slot)
        self.env.pull_from_stockpile(action.slot)
        logger.info(f"[t={self.env.time:.1f}s] Pulled {action.ingredient} from {action.slot} -> assembly")

    async def _exec_add_condiment(self, action) -> None:
        """添加调料"""
        await self.ui.add_condiment(action.condiment)
        self.env.add_condiment(action.condiment)
        logger.info(f"[t={self.env.time:.1f}s] Added condiment {action.condiment}")

    async def _exec_serve_order(self, action) -> None:
        """送餐"""
        await self.ui.serve_order(action.slot_idx)
        order = self.env.orders[action.slot_idx]
        if order:
            self.agent.on_order_served()
        self.env.serve_order(action.slot_idx)

    async def _exec_clear_cooker(self, action) -> None:
        """清理灶台"""
        await self.ui.clear_cooker(action.cooker)
        self.env.clear_cooker(action.cooker)
        logger.info(f"[t={self.env.time:.1f}s] Cleared cooker {action.cooker}")

    async def _exec_clear_assembly(self, action) -> None:
        """清空组装站"""
        discarded = self.env.assembly.ingredients.copy()
        await self.ui.clear_assembly()
        self.env.clear_assembly()
        logger.info(f"[t={self.env.time:.1f}s] Cleared assembly (discarded: {discarded})")

    def stop(self) -> None:
        """停止游戏"""
        self._running = False
