"""
真实游戏编排器

地位：协调 Agent、环境、扫描器和 UI 执行器
      管理游戏生命周期，运行扫描和决策循环
      通过 DI 注入所有组件
      设备 IO 已异步化（Issue #19）：多点 snapshot 与验证器的 snapshot+模板
      匹配均经 asyncio.to_thread 执行，验证期间三循环节拍不被打断。
      节拍收益待真机验证。

时基（#17）：
- 订单时间戳（created_at/timeout_at）取 env.time（局内相对秒数），与 GameEnv/模拟器同基
- 真实耗时测量（ghost 窗口、扫描计时、serve 验证等待打点）统一走注入的
  clock（默认 time.monotonic）——「游戏内时间」与「真实耗时」两个概念分离

订单生命周期（Issue #18）：
- Runner 不再直捅 env 私有状态（_orders/_next_order_id/_scoring）：
  扫描同步只收集扫描条目并调用 env.apply_scan_result（匹配/ghost 过滤/
  新建/删除在 env 内原子完成）；订单创建/超时查表收敛到 env.create_order
- serve 按 order_id 结算：_serve_with_verify 在每次尝试的 swipe 前锁定该槽
  当前 order_id，验证成功后经 env.serve_order_by_id 结算——验证窗口内订单
  被 timeout 移位/删除时绝不结算到错单（找不到则 warning + 不计分）

输入：Env, Operator, Scanner, Verifier, Strategy
      serve_verify_wait 读 config.game.serve_verify_wait（默认 0.2，Issue #22 接线）
输出：游戏统计结果

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from airtest.core.api import G
from loguru import logger

from hawarma.core.actions import Action, schedule_actions
from hawarma.agent.strategy import Strategy
from hawarma.recipe import Recipe

from .game_env import GameEnv
from .scanner import Scanner
from .operator import Operator
from .verifier import Verifier
from .timing import ExecutionTiming, Timer


class Runner:
    """
    游戏编排器

    通过 DI 注入所有组件。
    """

    def __init__(
        self,
        env: GameEnv,
        operator: Operator,
        scanner: Scanner,
        verifier: Verifier,
        strategy: Strategy,
        recipes: dict[str, Recipe],
        clock: Callable[[], float] | None = None,
        serve_verify_wait: float = 0.2,
    ):
        self.env = env
        self.ui = operator
        self.scanner = scanner
        self.verifier = verifier
        self.strategy = strategy
        self._recipe_by_slug = recipes
        # 送餐验证等待（秒）：serve swipe 后等动画渲染的时间，读 config.game.serve_verify_wait
        self._serve_verify_wait = serve_verify_wait

        # 墙钟（#17）：ghost 窗口/扫描计时等真实耗时测量统一走注入 clock
        # （默认 time.monotonic）；订单时间戳不经此（用 env.time 局内相对秒数）
        self._clock = clock if clock is not None else time.monotonic

        self.strategy.on_game_start(self._recipe_by_slug)

        self._running = False
        self._game_started = False
        self._executing_action = False
        self._agent_wakeup = asyncio.Event()
        self._last_served: dict[tuple[str, bool], float] = {}

        # 执行耗时观测（只观测不改行为）：送餐验证路径分段计时
        self._timing = ExecutionTiming()

        self._build_action_handlers()

    async def run(self) -> dict:
        """
        运行游戏

        Returns:
            游戏统计结果
        """
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

        # 3. 终局结算（幂等）后返回统计：含 total_score（逐单和）、
        #    total_visibility、final_score（逐单和+visibility）、scoring_version，
        #    以及执行耗时观测定时（timing，只观测不改行为）
        self.env.finalize()
        stats = self.env.get_stats()
        stats["timing"] = self._collect_timing()
        self._log_timing_summary(stats["timing"])
        return stats

    def _collect_timing(self) -> dict[str, dict[str, int | float]]:
        """汇总执行耗时观测：滑动往返（Operator）+ 送餐验证各段（Runner）。"""
        timing = self._timing.to_dict()
        timing["swipe"] = self.ui.timing.swipe.to_dict()
        return timing

    def _log_timing_summary(self, timing: dict[str, dict[str, int | float]]) -> None:
        """逐段输出耗时汇总（均值/次数），使「时间花在哪里」可见。"""
        logger.info("Execution timing summary:")
        for name, seg in timing.items():
            logger.info(
                f"  {name}: count={seg['count']}, total={seg['total']:.3f}s, "
                f"avg={seg['avg']:.4f}s, max={seg['max']:.3f}s"
            )

    async def _wait_for_game_start(self) -> None:
        """等待游戏开始：优先检测 timer，兜底检测订单是否出现，然后等待 3 秒

        已知问题：仅靠 timer 模板匹配会在匹配失败（阈值/区域/出现时间过短）
        时永远卡住。这里增加订单出现作为兜底信号，并周期性打印等待状态，
        避免 "waiting for game start" 无反应且无线索。
        """
        logger.info("Waiting for game start (timer/order detection)...")

        waited = 0.0
        while True:
            if await self.scanner.detect_timer():
                logger.info("Timer detected, waiting 3 seconds for first orders...")
                await asyncio.sleep(3)
                self._mark_game_started()
                return

            # 兜底：timer 未匹配到，但订单已经出现（游戏实际已开始）
            try:
                orders = await self.scanner.scan_new_orders()
            except Exception as e:
                logger.debug(f"Order scan during wait failed: {e}")
                orders = []
            if orders:
                logger.info(
                    f"Orders detected ({len(orders)}), treating game as started "
                    f"(timer not matched)"
                )
                self._mark_game_started()
                return

            await asyncio.sleep(0.5)
            waited += 0.5
            if int(waited) % 5 == 0:
                logger.warning(
                    f"Still waiting for game start... ({int(waited)}s) timer and "
                    f"orders not detected. Check timer icon asset / timer_region "
                    f"or that the game has actually begun."
                )

    def _mark_game_started(self) -> None:
        self.env.start_game()
        self._game_started = True
        logger.info("Game started!")

    # ========================================================================
    # 扫描循环
    # ========================================================================

    async def _scan_loop(self) -> None:
        """订单扫描循环（自适应频率），动画窗口期间暂停"""
        while self._running and not self.env.is_game_over():
            try:
                if self.env.is_in_animation_window():
                    # 动画窗口期间：sleep 到动画结束后再扫描
                    remaining = self.env.animation_window_remaining()
                    logger.debug(
                        f"[t={self.env.time:.1f}s] Animation window remaining: "
                        f"{remaining:.2f}s"
                    )
                    if remaining > 0:
                        await asyncio.sleep(remaining + 0.1)
                    # 动画结束后唤醒 agent
                    self._agent_wakeup.set()
                    continue

                await self._sync_orders_from_scan()
                # 扫描完成后唤醒 agent（有新信息）
                self._agent_wakeup.set()

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
        将 env.orders 与扫描结果增量同步（Issue #18）。

        Runner 只负责扫描与动画窗口防护；订单匹配/ghost 过滤/新建/删除的
        变更决策整体收敛进 env.apply_scan_result（同步方法，无 await）——
        单线程事件循环下与 serve/timeout 变更天然互斥，消除旧帧覆盖竞态：
        - 已 serve/已超时删除的订单不被旧扫描帧复活（env 记忆窗口校验）
        - 订单连续 2 次扫描未出现才删除（防单次漏检误删）

        动画窗口保护：若扫描过程中进入动画窗口（serve 后 1.5s），
        扫描可能捕获到动画前的旧帧，导致 ghost 防护失效。
        此时跳过本次 sync，避免视觉/env 错位。
        """
        if self.env.is_in_animation_window():
            logger.debug(
                f"[t={self.env.time:.1f}s] Skipping order sync: in animation window"
            )
            return

        start_time = self._clock()
        scanned = await self.scanner.scan_new_orders()
        if self.env.is_in_animation_window():
            logger.debug(
                f"[t={self.env.time:.1f}s] Discarding scan result: "
                f"animation started during scan (stale frame)"
            )
            return
        scan_duration = self._clock() - start_time

        # 收集扫描到的订单类型，按扫描 slot 排序（扫描器通常从左到右）
        scanned_types: list[tuple[str, bool]] = []
        for d in sorted(scanned, key=lambda x: x.slot_idx):
            scanned_types.append((d.recipe_slug, d.is_rush))

        # 增量同步在 env 内原子完成（无 await）：匹配/ghost 过滤/新建/删除。
        # _last_served 提供 serve 图像延迟的幽灵窗口（墙钟），与 env 的
        # 防复活记忆互补。
        stats = self.env.apply_scan_result(
            scanned_types,
            recently_served=self._last_served,
            now_wall=self._clock(),
        )
        logger.debug(
            f"[t={self.env.time:.1f}s] Scan completed: duration="
            f"{scan_duration * 1000:.1f}ms, detected={stats['detected']}, "
            f"reused={stats['reused']}, created={stats['created']}, "
            f"ghost_skipped={stats['ghost_skipped']}, "
            f"resurrection_blocked={stats['resurrection_blocked']}, "
            f"kept_pending_removal={stats['kept_pending_removal']}, "
            f"removed={stats['removed']}"
        )

    # ========================================================================
    # 超时检测循环
    # ========================================================================

    async def _timeout_loop(self) -> None:
        """订单超时检测循环（每 0.3s），有变化时唤醒 agent"""
        while self._running and not self.env.is_game_over():
            try:
                timed_out = self.env.check_and_remove_timed_out_orders()
                if timed_out:
                    for order_id in timed_out:
                        self.env.on_order_timeout(order_id)
                    # 订单超时后唤醒 agent（状态变化）
                    self._agent_wakeup.set()
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"Timeout loop error: {e}")
                await asyncio.sleep(0.3)

    # ========================================================================
    # Agent 决策循环
    # ========================================================================

    async def _agent_loop(self) -> None:
        """Agent 决策循环（事件驱动），只在有信息变化时唤醒"""
        while self._running and not self.env.is_game_over():
            try:
                if self._executing_action:
                    # 等待操作完成后的自动唤醒
                    await asyncio.wait_for(
                        self._agent_wakeup.wait(), timeout=2.0
                    )
                    self._agent_wakeup.clear()
                    continue

                # 等待被唤醒（扫描完成 / 操作完成 / 动画结束 / 超时 / 定时器）
                try:
                    await asyncio.wait_for(
                        self._agent_wakeup.wait(), timeout=0.5
                    )
                    self._agent_wakeup.clear()
                except asyncio.TimeoutError:
                    # 0.5s 内无事件：被动唤醒（安全检查，防止死锁）
                    pass

                in_animation = self.env.is_in_animation_window()

                action = self.strategy.decide(self.env.get_unified_state())
                if action:
                    action_type = type(action).__name__
                    if in_animation and action_type in ("ServeOrderAction", "ServeFromCookerAction"):
                        # serve 在动画窗口期间被跳过，等待动画结束
                        continue

                    self.env.on_action_taken()
                    self._executing_action = True
                    await self._execute_action(action)
                    self._executing_action = False
                    # 操作完成后立即触发下一次决策（状态已变化）
                    self._agent_wakeup.set()
            except Exception as e:
                logger.error(f"Agent loop error: {e}")
                self._executing_action = False
                # 错误后也唤醒一次，避免永久阻塞
                self._agent_wakeup.set()

    # ========================================================================
    # 动作执行
    # ========================================================================

    async def _execute_action(self, action: Action) -> None:
        """执行 Agent 动作（dispatch table 分发）

        已取消的动作直接跳过：无 UI 调用、无状态变化（Ticket #11）。
        默认 cancelled=False，既有策略行为不变。
        """
        if action.cancelled:
            logger.info(
                f"[t={self.env.time:.1f}s] Skipping cancelled action: {action.action_type}"
            )
            return

        if self.env.is_game_over():
            logger.info(
                f"[t={self.env.time:.1f}s] Game over, skipping action: {type(action).__name__}"
            )
            self._running = False
            return

        action_type = type(action).__name__
        handler_name = self._action_handlers.get(action_type)
        if handler_name:
            try:
                await getattr(self, handler_name)(action)
            except Exception as e:
                logger.error(f"Failed to execute {action_type}: {e}")
        else:
            logger.warning(f"Unknown action: {action_type}")

    def _build_action_handlers(self) -> None:
        """构建 action type → exec 方法的映射表"""
        self._action_handlers = {
            "CookAction": "_exec_cook",
            "MoveToAssemblyAction": "_exec_move_to_assembly",
            "MoveToStockpileAction": "_exec_move_to_stockpile",
            "PullFromStockpileAction": "_exec_pull_from_stockpile",
            "AddCondimentAction": "_exec_add_condiment",
            "ServeOrderAction": "_exec_serve_order",
            "ClearCookerAction": "_exec_clear_cooker",
            "ClearAssemblyAction": "_exec_clear_assembly",
            "MoveToMixingBowlAction": "_exec_move_to_mixing_bowl",
            "AddCondimentToMixingBowlAction": "_exec_add_condiment_to_mixing_bowl",
            "StirAction": "_exec_stir",
            "MoveMixingBowlToCookerAction": "_exec_move_mixing_bowl_to_cooker",
            "ServeFromCookerAction": "_exec_serve_from_cooker",
            "ClearMixingBowlAction": "_exec_clear_mixing_bowl",
        }

    async def dispatch_batch(self, actions: list[Action]) -> list[Action]:
        """批量分发：按共享调度排序后逐个执行，返回实际调度的动作.

        与 SimEnv.run_action_sequence 同调 schedule_actions，
        同一序列两端执行顺序与取消语义一致（Ticket #11）。
        """
        scheduled = schedule_actions(actions)
        for action in scheduled:
            await self._execute_action(action)
        return scheduled

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
            ingredient = cooker_state.item_name
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
        cooker = self.env.cookers.get(action.cooker)
        if cooker is None or not cooker.busy:
            logger.warning(
                f"[t={self.env.time:.1f}s] Cooker {action.cooker} not busy, skipping stockpile move"
            )
            return
        await self.ui.move_to_stockpile(action.cooker, action.slot)
        ingredient = cooker.item_name
        if self.env.move_to_stockpile(action.cooker, action.slot):
            logger.info(
                f"[t={self.env.time:.1f}s] Stored {ingredient} from {action.cooker} -> {action.slot}"
            )
        else:
            logger.warning(
                f"[t={self.env.time:.1f}s] Failed to update stockpile state for {ingredient} on {action.cooker} -> {action.slot} (slot may be full or incompatible)"
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
        """送餐（带验证和重试）；验证成功后按 serve 前锁定的 order_id 结算（Issue #18）。

        _serve_with_verify 总耗时 ≥0.25s，期间 timeout 循环可能删除目标订单并使
        槽位左移——按 slot 结算会打错单。结算改经 env.serve_order_by_id：
        找不到（已被 timeout 删）则 warning + 不计分。
        """
        result = await self._serve_with_verify(action.slot_idx)

        if result is None:
            logger.warning(
                f"[t={self.env.time:.1f}s] Serve verification failed, assembly discarded."
            )
            # 不再自动清空 assembly，让 agent 的 _try_clear_assembly 决策是否清理
            return

        success_slot, target_order_id = result

        if target_order_id is None:
            logger.warning(
                f"[t={self.env.time:.1f}s] Serve verified at slot {success_slot} but "
                f"no active order was there when the swipe started "
                f"(timed out during verification?); no settlement"
            )
            return

        # 必须在结算清空 assembly 之前读取 condiments（serve_order_by_id 会 reset）
        has_condiments = bool(self.env.assembly.condiments)
        order = self.env.serve_order_by_id(target_order_id)
        if order is not None:
            self.env.on_order_served(order, has_condiments)
            # 记录刚 serve 的订单类型（墙钟时刻），用于扫描时识别幽灵订单
            self._last_served[(order.recipe_slug, order.is_rush)] = self._clock()
        else:
            logger.warning(
                f"[t={self.env.time:.1f}s] Order {target_order_id} disappeared before "
                f"settlement (timed out during serve verification); not scored"
            )

    async def _serve_with_verify(self, slot_idx: int) -> tuple[int, int | None] | None:
        """
        执行送餐并验证是否成功。

        1. 锁定本次尝试目标槽位上的 order_id（serve 验证窗口内 timeout 移位的
           安全锚点，Issue #18）
        2. 执行 serve swipe 到目标 slot
        3. 等待动画 + 多点 snapshot 验证
        4. 失败后重试相邻左侧 slot（slot_idx - 1），重试前重新锁定该槽 order_id
        5. 两次都失败则丢弃菜品，清空 assembly

        只观测不改行为：沿途对「验证等待 / 截图验证 / 重试 / 清理」
        分别埋耗时打点（swipe 自身由 Operator 观测）。

        Returns:
            (成功槽位, 该次尝试 swipe 前锁定的 order_id)——order_id 可能为 None
            （swipe 开始时该槽无活跃订单）；两次尝试都失败返回 None
        """
        # 第一次尝试：原始 slot（先锁定目标 order_id 再 swipe）
        target = self.env.orders[slot_idx] if slot_idx < len(self.env.orders) else None
        target_order_id = target.order_id if target is not None else None
        await self.ui.serve_order(slot_idx)

        wait_timer = Timer(self._timing.serve_verify_wait)
        await asyncio.sleep(self._serve_verify_wait)  # 等待动画渲染
        wait_timer.record()

        snapshot_timer = Timer(self._timing.serve_verify_snapshot)
        verified = await self._verify_with_multi_snapshot()
        snapshot_timer.record()
        if verified:
            return slot_idx, target_order_id

        logger.warning(
            f"[t={self.env.time:.1f}s] Serve verification failed. "
            f"Assembly still has: {self.env.assembly.ingredients_cookers}"
        )

        # 重试相邻左侧 slot（整个重试段计时；无左侧 slot 时不重试不计时）
        retry_slot = slot_idx - 1
        if retry_slot >= 0:
            retry_timer = Timer(self._timing.serve_retry)
            # 重试前重新锁定该槽当前 order_id（槽位可能已位移）
            retry_target = (
                self.env.orders[retry_slot]
                if retry_slot < len(self.env.orders)
                else None
            )
            retry_order_id = retry_target.order_id if retry_target is not None else None
            await asyncio.sleep(0.05)
            await self.ui.serve_order(retry_slot)
            await asyncio.sleep(self._serve_verify_wait)  # 等待动画渲染
            retry_result = await self._verify_with_multi_snapshot()
            retry_timer.record()
            if retry_result:
                logger.info(
                    f"[t={self.env.time:.1f}s] Serve succeeded at slot {retry_slot}"
                )
                return retry_slot, retry_order_id

        # 两次都失败，丢弃菜品（清理段计时）
        cleanup_timer = Timer(self._timing.serve_cleanup)
        await self.ui.clear_assembly()
        self.env.clear_assembly()
        cleanup_timer.record()
        logger.warning(
            f"[t={self.env.time:.1f}s] Both serve attempts failed. Assembly discarded."
        )
        return None

    async def _verify_with_multi_snapshot(self) -> bool:
        """
        多点 snapshot 验证 assembly 是否为空。

        流程：连续获取 4 张 snapshot（间隔 0.05s），用第 4 张验证

        设备 IO 经 asyncio.to_thread 移出事件循环（Issue #19）：snapshot 与
        验证器的 snapshot+模板匹配在 worker 线程执行，事件循环在此期间
        照常推进（timeout/scan 循环不停摆）。Verifier 保持同步签名，
        由本调用点负责线程化。
        """
        for _ in range(3):
            await asyncio.to_thread(G.DEVICE.snapshot)

        return await asyncio.to_thread(self.verifier.is_assembly_empty)

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

    # ========================================================================
    # Dessert 动作执行
    # ========================================================================

    async def _exec_move_to_mixing_bowl(self, action) -> None:
        """食材 → 搅拌盆"""
        await self.ui.move_to_mixing_bowl(action.ingredient)
        self.env.add_to_mixing_bowl(action.ingredient)
        logger.info(f"[t={self.env.time:.1f}s] Moved {action.ingredient} to mixing bowl")

    async def _exec_add_condiment_to_mixing_bowl(self, action) -> None:
        """调料 → 搅拌盆"""
        await self.ui.add_condiment_to_mixing_bowl(action.condiment)
        self.env.add_condiment_to_mixing_bowl(action.condiment)
        logger.info(f"[t={self.env.time:.1f}s] Added condiment {action.condiment} to mixing bowl")

    async def _exec_stir(self, action) -> None:
        """搅拌"""
        await self.ui.stir(action.distance, action.duration, action.steps)
        self.env.stir_mixing_bowl()
        logger.info(f"[t={self.env.time:.1f}s] Stirred mixing bowl")

    async def _exec_move_mixing_bowl_to_cooker(self, action) -> None:
        """搅拌盆 → 灶台"""
        await self.ui.move_mixing_bowl_to_cooker(action.cooker)
        self.env.move_mixing_bowl_to_cooker(action.cooker)
        logger.info(f"[t={self.env.time:.1f}s] Moved mixing bowl to {action.cooker}")

    async def _exec_serve_from_cooker(self, action) -> None:
        """灶台 → 取餐台（甜点单食材直送，无调料）"""
        order = self.env.orders[action.slot_idx] if action.slot_idx < len(self.env.orders) else None
        await self.ui.serve_from_cooker(action.cooker, action.slot_idx)
        if self.env.serve_from_cooker(action.cooker, action.slot_idx):
            if order:
                self.env.on_order_served(order, has_condiments=False)
                self._last_served[(order.recipe_slug, order.is_rush)] = self._clock()
        logger.info(f"[t={self.env.time:.1f}s] Served from {action.cooker} to slot {action.slot_idx}")

    async def _exec_clear_mixing_bowl(self, action) -> None:
        """清空搅拌盆"""
        await self.ui.clear_mixing_bowl()
        self.env.clear_mixing_bowl()
        logger.info(f"[t={self.env.time:.1f}s] Cleared mixing bowl")

    def stop(self) -> None:
        """停止游戏"""
        self._running = False
