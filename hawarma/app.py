"""
Core Application

地位：管理会话生命周期，扫描循环，启动和停止。

输入：配置对象、配方列表
输出：应用运行状态、订单完成统计

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

import asyncio
import itertools

from loguru import logger

from hawarma.config import AppConfig
from hawarma.models import Recipe
from hawarma.scheduler import Scheduler
from hawarma.services import DetectionService, Executor, ResourceGuards
from hawarma.state import GameState, SessionState, init_game_state, init_session_state
from hawarma.ui_operation_manager import UIOperationManager


class CookingBotApp:
    """
    Thin application class. Lifecycle only.

    Responsibilities:
    - Initialize services and global state
    - Run scan loop (detect new orders)
    - Run tick loop (schedule + execute actions)
    - Stop and cleanup

    All business decisions are delegated to Scheduler.
    All physical actions are delegated to Executor.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.is_running = False
        self._setup_done = False

        self.scan_task: asyncio.Task | None = None
        self.tick_task: asyncio.Task | None = None

        self.detection_service: DetectionService | None = None
        self.scheduler: Scheduler | None = None
        self.executor: Executor | None = None
        self.ui_manager: UIOperationManager | None = None
        self.guards: ResourceGuards | None = None

        self.game_state: GameState | None = None
        self.session_state: SessionState | None = None

    def setup(self, ordered_recipes: list[Recipe]) -> None:
        """Initialize all services and global state."""
        logger.info("Setting up application services...")

        cookers_mapping = self._get_cookers_positions(ordered_recipes)
        raw_ingredients_mapping = self._get_raw_ingredients_positions(ordered_recipes)
        condiments_mapping = self._get_condiments_positions(ordered_recipes)

        self.ui_manager = UIOperationManager()

        self.guards = ResourceGuards(
            cookers=list(cookers_mapping.keys()),
            stockpile_slot_count=len(self.config.screen.stockpile_positions),
        )

        self.game_state = init_game_state(list(cookers_mapping.keys()))
        self.session_state = init_session_state(ordered_recipes)

        self.detection_service = DetectionService(
            recipes=ordered_recipes, config=self.config
        )

        self.scheduler = Scheduler(self.game_state, self.session_state)

        self.executor = Executor(
            game_state=self.game_state,
            session_state=self.session_state,
            raw_ingredients_mapping=raw_ingredients_mapping,
            cookers_mapping=cookers_mapping,
            condiments_mapping=condiments_mapping,
            assembly_station_pos=self.config.screen.assembly_station_position,
            pickup_stations_pos=self.config.screen.pickup_stations_positions,
            stockpile_positions=self.config.screen.stockpile_positions,
            ui_manager=self.ui_manager,
            guards=self.guards,
            ordered_recipes=ordered_recipes,
        )

        self._setup_done = True
        logger.info("Application setup complete.")

    async def run(self) -> None:
        """Main entry point. Starts scan and tick loops."""
        if not self._setup_done:
            raise RuntimeError("setup() must be called before run()")

        self.is_running = True
        logger.info("Cooking Bot is running. Press Ctrl+C to stop.")

        try:
            self.scan_task = asyncio.create_task(self._scan_loop())
            self.tick_task = asyncio.create_task(self._tick_loop())

            await asyncio.gather(self.scan_task, self.tick_task)

        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.warning("Application run loop interrupted.")
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop application and cleanup all tasks."""
        self.is_running = False
        logger.info("Stopping the Cooking Bot...")

        for task in [self.scan_task, self.tick_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        logger.info("Cooking Bot has been stopped.")

    async def _scan_loop(self) -> None:
        """
        Background task: continuously detect new orders.

        Detection runs outside the lock (I/O-bound).
        Only the state write is locked.
        Waits for slot animation to complete before scanning.
        """
        while self.is_running:
            now = asyncio.get_event_loop().time()
            async with self.game_state.lock:
                can_scan = self.game_state.is_ui_stable(now)

            if not can_scan:
                await asyncio.sleep(0.1)
                continue

            for slot_idx in range(len(self.game_state.orders)):
                # 跳过已有订单的 slot，避免重复检测
                async with self.game_state.lock:
                    if self.game_state.orders[slot_idx] is not None:
                        continue

                order = await asyncio.to_thread(
                    self.detection_service.detect_order, slot_idx
                )
                if order:
                    async with self.game_state.lock:
                        if self.game_state.orders[slot_idx] is None:
                            self.game_state.orders[slot_idx] = order
                            logger.info(f"New order in slot {slot_idx}: {order}")

            await asyncio.sleep(0.5)

    async def _tick_loop(self) -> None:
        """
        Main tick loop: ask scheduler for actions and execute them.

        Scheduler call is inside the lock (state read).
        Action execution is outside the lock.
        Only schedules when UI is stable.
        """
        while self.is_running:
            now = asyncio.get_event_loop().time()
            async with self.game_state.lock:
                if self.game_state.is_ui_stable(now):
                    actions = self.scheduler.get_next_actions()
                else:
                    actions = []

            if actions:
                await self.executor.execute_batch(actions)

            await asyncio.sleep(0.1)

    def _get_cookers_positions(
        self, recipes: list[Recipe]
    ) -> dict[str, tuple[int, int]]:
        """Calculate the positions of cookers based on selected recipes."""
        cookers_in_use = list(
            dict.fromkeys(
                itertools.chain.from_iterable(r.cookers_layout for r in recipes)
            )
        )
        count = len(cookers_in_use)
        positions = self.config.screen.cookers_positions
        logger.debug(f"Assigning positions for cookers: {cookers_in_use}")
        return {
            cooker: positions[idx + 1 if count < 3 else idx]
            for idx, cooker in enumerate(cookers_in_use)
        }

    def _get_raw_ingredients_positions(
        self, recipes: list[Recipe]
    ) -> dict[str, tuple[int, int]]:
        """Calculate the positions of raw ingredients based on selected recipes."""
        ingredients_in_use = list(
            dict.fromkeys(
                itertools.chain.from_iterable(r.raw_ingredients for r in recipes)
            )
        )
        ingredients_in_use.reverse()
        positions = self.config.screen.raw_ingredients_positions
        logger.debug(f"Assigning positions for ingredients: {ingredients_in_use}")
        return {
            ingredient: positions[idx]
            for idx, ingredient in enumerate(ingredients_in_use)
        }

    def _get_condiments_positions(
        self, recipes: list[Recipe]
    ) -> dict[str, tuple[int, int]]:
        """Calculate the positions of condiments based on selected recipes."""
        condiments_in_use = list(
            dict.fromkeys(itertools.chain.from_iterable(r.condiments for r in recipes))
        )
        positions = self.config.screen.condiments_positions
        logger.debug(f"Assigning positions for condiments: {condiments_in_use}")
        return {
            condiment: positions[idx] for idx, condiment in enumerate(condiments_in_use)
        }
