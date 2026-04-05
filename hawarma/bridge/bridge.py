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
from .assembly_verifier import AssemblyVerifier


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
        )

        self.scanner = OrderScanner(config, recipes)
        self.ui = UIRunner(config, recipes)
        self.verifier = AssemblyVerifier(config)
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
        """订单扫描循环（自适应频率）"""
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
        - 有灶台空闲且有活跃订单：快速扫描（0.5s），尽快发现新订单启动烹饪
        - 所有灶台都在忙：慢速扫描（2.0s），等烹饪完成再处理
        - 无活跃订单：中速扫描（1.0s），等待新订单出现
        """
        active_orders = [o for o in self.env.orders if o and not o.done]
        free_cookers = [c for c in self.env.cookers.values() if not c.busy]

        if not active_orders:
            return 1.0

        if free_cookers:
            return 0.5

        return 2.0

    async def _sync_orders_from_scan(self) -> None:
        """
        扫描屏幕并与 env.orders 对比，只添加真正的新订单。
        
        env.orders 在 serve 后已经左移补位，所以直接按 slot 对比即可。
        同一个 recipe_slug 的多个订单按出现顺序匹配。
        """
        scanned = await self.scanner.scan_new_orders()
        
        # 统计 env 中已有的订单（按 recipe_slug 计数）
        env_counts: dict[str, int] = {}
        for order in self.env.orders:
            if order is not None:
                env_counts[order.recipe_slug] = env_counts.get(order.recipe_slug, 0) + 1
        
        # 统计扫描结果中每个 recipe_slug 的数量
        scan_counts: dict[str, int] = {}
        for detected in scanned:
            scan_counts[detected.recipe_slug] = scan_counts.get(detected.recipe_slug, 0) + 1
        
        # 找出真正新增的订单
        for detected in scanned:
            slug = detected.recipe_slug
            env_n = env_counts.get(slug, 0)
            scan_n = scan_counts.get(slug, 0)
            
            # 如果扫描到的数量 > env 中的数量，说明有新订单
            if scan_n > env_n:
                self.env.add_order(
                    slot_idx=detected.slot_idx,
                    recipe_slug=detected.recipe_slug,
                    is_rush=detected.is_rush,
                )
                env_counts[slug] = env_n + 1

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
        """Agent 决策循环（每 0.05s），带停滞检测"""
        while self._running and not self.env.is_game_over():
            try:
                action = self.agent.step_with_diagnostics()
                if action:
                    self.agent.stats["actions_taken"] += 1
                    await self._execute_action(action)
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Agent loop error: {e}")
                await asyncio.sleep(0.05)

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
        """送餐（带验证和重试）"""
        served = await self._serve_with_verify(action.slot_idx, max_retries=2)

        if served:
            order = self.env.orders[action.slot_idx]
            if order:
                self.agent.on_order_served()
            self.env.serve_order(action.slot_idx)
        else:
            logger.warning(
                f"[t={self.env.time:.1f}s] Serve failed after retries. "
                f"Clearing assembly and continuing."
            )
            await self.ui.clear_assembly()
            self.env.clear_assembly()

    async def _serve_with_verify(self, slot_idx: int, max_retries: int = 2) -> bool:
        """
        执行送餐并验证是否成功。

        流程：
        1. 执行 UI 送餐操作
        2. 等待动画窗口结束
        3. 验证组装站是否为空
        4. 如果为空 → 成功
        5. 如果不为空 → 重新扫描订单，找到匹配的槽位重试
        6. 重试 max_retries 次后仍失败 → 返回 False

        Returns:
            True 如果送餐成功，False 如果失败
        """
        for attempt in range(max_retries + 1):
            await self.ui.serve_order(slot_idx)
            await asyncio.sleep(0.5)

            if self.verifier.is_assembly_empty():
                if attempt > 0:
                    logger.info(f"[t={self.env.time:.1f}s] Serve succeeded on retry {attempt}")
                return True

            logger.warning(
                f"[t={self.env.time:.1f}s] Serve verification failed (attempt {attempt + 1}/{max_retries + 1}). "
                f"Assembly still has: {self.env.assembly.ingredients}"
            )

            if attempt < max_retries:
                matching_slot = await self._find_matching_order_slot()
                if matching_slot is not None and matching_slot != slot_idx:
                    logger.info(
                        f"[t={self.env.time:.1f}s] Re-scanning found matching order at slot {matching_slot}. Retrying..."
                    )
                    slot_idx = matching_slot
                else:
                    logger.info(
                        f"[t={self.env.time:.1f}s] No matching order found. Retrying same slot {slot_idx}..."
                    )

        return False

    async def _find_matching_order_slot(self) -> int | None:
        """
        重新扫描订单，找到与组装站食材匹配的槽位。

        Returns:
            匹配的槽位索引，如果没有匹配则返回 None
        """
        scanned = await self.scanner.scan_new_orders()

        assembly = self.env.assembly
        assembly_names = [ing[0] if isinstance(ing, tuple) else ing for ing in assembly.ingredients]

        for detected in scanned:
            recipe = self._recipe_by_slug.get(detected.recipe_slug)
            if recipe:
                raw_ings = getattr(recipe, 'raw_ingredients', [])
                if sorted(assembly_names) == sorted(raw_ings):
                    return detected.slot_idx

        return None

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
