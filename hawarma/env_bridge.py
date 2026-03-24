"""
环境桥接器

地位：连接 Executor（真实系统）和 GameSimulator（参考实现），
      将 Executor 的坐标操作实时翻译为符号操作并验证。

输入：Executor 的 swipe 操作（坐标）
输出：验证结果、同步的模拟器状态

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新
"""

from dataclasses import dataclass, field

from loguru import logger

from hawarma.env_simulator import Event, EventType, GameSimulator


@dataclass
class SwipeRecord:
    """一次 swipe 记录，包含坐标和翻译后的符号"""

    start_pos: tuple[int, int]
    end_pos: tuple[int, int]
    symbol_start: str
    symbol_end: str
    action: str
    success: bool
    time: float = 0.0


class EnvBridge:
    """
    环境桥接器。

    拦截 Executor 的 swipe 操作，翻译为 GameSimulator 的符号操作，
    实时验证规则并同步状态。

    用法：
        bridge = EnvBridge(simulator, executor)
        # 替换 executor 的 ui_manager
        executor.ui = bridge
        # Executor 的每次 swipe 自动经过 bridge 验证
    """

    def __init__(
        self,
        simulator: GameSimulator,
        raw_ingredients_mapping: dict[str, tuple[int, int]],
        cookers_mapping: dict[str, tuple[int, int]],
        condiments_mapping: dict[str, tuple[int, int]],
        assembly_pos: tuple[int, int],
        stockpile_positions: list[tuple[int, int]],
        pickup_positions: list[tuple[int, int]],
        trash_pos: tuple[int, int] = (130, 560),
    ):
        self.sim = simulator
        self.assembly_pos = assembly_pos
        self.trash_pos = trash_pos
        self.pickup_positions = pickup_positions
        self.stockpile_positions = stockpile_positions

        # 坐标 → 符号名 反查表
        self._pos_to_ingredient = {v: k for k, v in raw_ingredients_mapping.items()}
        self._pos_to_cooker = {v: k for k, v in cookers_mapping.items()}
        self._pos_to_condiment = {v: k for k, v in condiments_mapping.items()}
        self._pos_to_stockpile = {v: f"stk{i}" for i, v in enumerate(stockpile_positions)}

        # 验证记录
        self.records: list[SwipeRecord] = []
        self.violations: list[str] = []

        # MockUI 兼容接口
        self.operations: list = []

    # ------------------------------------------------------------------
    # 核心：拦截 swipe
    # ------------------------------------------------------------------

    async def swipe(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        duration: float = 0.1,
    ) -> None:
        """
        拦截 Executor 的 swipe 操作。

        翻译为符号操作，推进模拟器时间以满足前置条件，
        然后调用 GameSimulator 验证。
        """
        sym_start = self._resolve(start)
        sym_end = self._resolve(end)
        action = self._infer_action(sym_start, sym_end)

        # 推进模拟器时间以满足操作前置条件
        self._advance_for(action, sym_start, sym_end)

        success = self._execute_sim(action, sym_start, sym_end)
        violation_msg = None

        if action == "unknown":
            success = False

        if not success:
            violation_msg = (
                f"Invalid swipe: {action} "
                f"{sym_start} -> {sym_end}"
            )
            self.violations.append(violation_msg)
            logger.warning(f"[EnvBridge] {violation_msg}")

        record = SwipeRecord(
            start_pos=start,
            end_pos=end,
            symbol_start=sym_start,
            symbol_end=sym_end,
            action=action,
            success=success,
            time=self.sim.time,
        )
        self.records.append(record)

        # 兼容 MockUI：记录操作
        self.operations.append(_SwipeOp(start, end, duration, self.sim.time))

        # 推进模拟器时间（每个 swipe 消耗时间）
        self.sim.tick(duration)

    async def execute(self, operation: str, *args, **kwargs) -> None:
        """兼容 UIOperationManager 接口"""
        if operation == "swipe":
            await self.swipe(args[0], args[1], **kwargs)

    # ------------------------------------------------------------------
    # 时间推进
    # ------------------------------------------------------------------

    def _advance_for(self, action: str, sym_start: str, sym_end: str) -> None:
        """
        推进模拟器时间以满足操作前置条件。
        """
        if action == "serve":
            if self.sim.time < self.sim._animation_until:
                dt = self.sim._animation_until - self.sim.time
                self.sim.tick(dt)

        elif action in ("move_to_assembly", "move_to_stockpile", "clear_to_trash"):
            cooker_name = sym_start.split(":", 1)[1]
            cooker = self.sim.cookers.get(cooker_name)
            if cooker and cooker.done_at is not None and self.sim.time < cooker.done_at:
                # done_at 基于 sim.time 设置，直接用差值推进
                dt = cooker.done_at - self.sim.time
                self.sim.tick(dt)

    # ------------------------------------------------------------------
    # 坐标翻译
    # ------------------------------------------------------------------

    def _resolve(self, pos: tuple[int, int]) -> str:
        """将坐标解析为符号名"""
        if pos in self._pos_to_ingredient:
            return f"ingredient:{self._pos_to_ingredient[pos]}"
        if pos in self._pos_to_cooker:
            return f"cooker:{self._pos_to_cooker[pos]}"
        if pos in self._pos_to_condiment:
            return f"condiment:{self._pos_to_condiment[pos]}"
        if pos in self._pos_to_stockpile:
            return f"stockpile:{self._pos_to_stockpile[pos]}"
        if pos == self.assembly_pos:
            return "assembly"
        if pos == self.trash_pos:
            return "trash"
        if pos in self.pickup_positions:
            idx = self.pickup_positions.index(pos)
            return f"pickup:slot{idx}"
        return f"unknown:{pos}"

    def _infer_action(self, sym_start: str, sym_end: str) -> str:
        """根据起点/终点符号推断操作类型"""
        if sym_start.startswith("ingredient:") and sym_end.startswith("cooker:"):
            return "cook"
        if sym_start.startswith("cooker:") and sym_end == "assembly":
            return "move_to_assembly"
        if sym_start.startswith("cooker:") and sym_end.startswith("stockpile:"):
            return "move_to_stockpile"
        if sym_start.startswith("stockpile:") and sym_end == "assembly":
            return "pull_from_stockpile"
        if sym_start.startswith("condiment:") and sym_end == "assembly":
            return "add_condiment"
        if sym_start == "assembly" and sym_end.startswith("pickup:"):
            return "serve"
        if sym_start.startswith("cooker:") and sym_end == "trash":
            return "clear_to_trash"
        return "unknown"

    # ------------------------------------------------------------------
    # 符号操作执行
    # ------------------------------------------------------------------

    def _execute_sim(self, action: str, sym_start: str, sym_end: str) -> bool:
        """调用 GameSimulator 执行符号操作"""
        if action == "cook":
            ingredient = sym_start.split(":", 1)[1]
            cooker = sym_end.split(":", 1)[1]
            return self.sim.start_cooking(ingredient, cooker)

        if action == "move_to_assembly":
            cooker = sym_start.split(":", 1)[1]
            return self.sim.move_to_assembly(cooker)

        if action == "move_to_stockpile":
            cooker = sym_start.split(":", 1)[1]
            slot = sym_end.split(":", 1)[1]
            return self.sim.move_to_stockpile(cooker, slot)

        if action == "pull_from_stockpile":
            slot = sym_start.split(":", 1)[1]
            return self.sim.pull_from_stockpile(slot)

        if action == "add_condiment":
            condiment = sym_start.split(":", 1)[1]
            return self.sim.add_condiment(condiment)

        if action == "serve":
            # 从 pickup:slotN 提取 slot index
            slot_str = sym_end.split(":", 1)[1]  # "slot0"
            pickup_slot = int(slot_str.replace("slot", ""))

            # 找到组装站归属的订单在 sim 中的实际 slot
            owner_id = self.sim.assembly.owner_order_id
            if owner_id is not None:
                actual_slot = self.sim.get_order_slot(owner_id)
                if actual_slot >= 0:
                    return self.sim.serve_order(actual_slot)

            # fallback: 用 executor 的 pickup_slot
            return self.sim.serve_order(pickup_slot)

        if action == "clear_to_trash":
            cooker = sym_start.split(":", 1)[1]
            return self.sim.clear_cooker(cooker)

        return True  # unknown action, don't block

    # ------------------------------------------------------------------
    # 时间控制
    # ------------------------------------------------------------------

    def tick(self, dt: float) -> list[Event]:
        """推进模拟器时间"""
        return self.sim.tick(dt)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        """获取模拟器状态快照"""
        return self.sim.snapshot()

    def has_violations(self) -> bool:
        return len(self.violations) > 0

    def get_swipe_symbols(self) -> list[tuple[str, str, str]]:
        """返回 [(action, start, end), ...] 符号序列"""
        return [(r.action, r.symbol_start, r.symbol_end) for r in self.records]


# ============================================================================
# 兼容 MockUI 的 swipe 操作记录
# ============================================================================


class _SwipeOp:
    """兼容 MockUIOperationManager.operations 中的 Swipe 对象"""

    def __init__(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        duration: float,
        timestamp: float,
    ):
        self.type = "swipe"
        self.start = start
        self.end = end
        self.duration = duration
        self.timestamp = timestamp

    def __repr__(self):
        return f"Swipe({self.start} -> {self.end}, {self.duration:.2f}s)"
