"""
Runtime State

地位：游戏运行期的唯一状态入口，所有组件通过它读写共享状态。
它不是单纯的数据容器，而是显式建模运行时资源、订单映射和执行保留信息的状态对象。

设计原则：
1. GameState 是运行期共享真相入口，但内部同时容纳：
   - 检测得到的可见订单映射（orders）
   - 执行期资源占用状态（cookers / assembly / stockpile）
   - 调度保留状态（reservations）
2. 所有状态修改都必须在 `async with state.lock:` 下进行。
3. 订单身份统一以 `order_id` 为准，禁止依赖对象 identity。
4. 不使用 asyncio.Task 是否存在来表达业务状态；调度/执行中的占位使用显式 reservation 字段。
5. SessionState 仅保存会话级静态配置，不保存运行期动态状态。

输入：DetectionService 检测结果、Executor 执行结果
输出：供 Scheduler 决策的完整运行时状态快照

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的 md
"""

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from hawarma.models import Order, OrderStage, Recipe


AssemblyStatus = Literal["idle", "occupied"]
CookerDestination = Literal["assembly", "stockpile"]


@dataclass
class AssemblyState:
    """
    Runtime state of the shared assembly station.

    owner_order_id:
        Which order currently owns the assembly station.
    ingredients:
        Cooked ingredients currently placed on assembly for that order.
    reserved_ts:
        Timestamp when the station was reserved, useful for debugging/recovery.
    """
    owner_order_id: int | None = None
    ingredients: list[str] = field(default_factory=list)
    reserved_ts: float | None = None

    def is_free(self) -> bool:
        return self.owner_order_id is None


@dataclass
class CookerState:
    """
    Runtime state of a single cooker.

    busy:
        Whether the cooker is currently occupied by some work.
    ingredient_name:
        Which ingredient is currently assigned to this cooker.
    order_id:
        The target order, or None if this is a stockpile refill.
    destination:
        Whether the cooked result is intended for assembly or stockpile.
    ready_at:
        Expected timestamp when cooking is done.
    clear_by:
        Latest safe timestamp to clear cooked ingredient from cooker.
        The game allows at most ~5 seconds after completion.
    """
    busy: bool = False
    ingredient_name: str | None = None
    order_id: int | None = None
    destination: CookerDestination | None = None
    ready_at: float | None = None
    clear_by: float | None = None
    cooked_waiting_assembly: bool = False

    def is_free(self) -> bool:
        """Truly free: not busy, or waiting for assembly (can be reassigned)."""
        return not self.busy or self.cooked_waiting_assembly

    def is_ready(self, now: float) -> bool:
        return self.busy and self.ready_at is not None and now >= self.ready_at

    def is_overdue(self, now: float) -> bool:
        return self.busy and self.clear_by is not None and now >= self.clear_by


@dataclass
class OrderReservation:
    """
    Explicit scheduler/executor reservations for an order.

    prep_reserved:
        This order is currently being prepared / has inflight ingredient work.
    finish_reserved:
        This order is currently being finished (season + serve).
    """
    prep_reserved: bool = False
    finish_reserved: bool = False


@dataclass
class RuntimeTimestamps:
    """
    Runtime timing markers used to avoid scanning / scheduling on unstable UI frames.
    """
    last_scan_ts: float = 0.0
    last_ui_action_ts: float = 0.0
    last_order_completion_ts: float = 0.0
    slot_animation_until: float = 0.0
    ui_cooldown_until: float = 0.0


@dataclass
class GameState:
    """
    Single shared runtime state entry for the whole game session.

    Important semantics:
    - orders:
        Current visible order-slot mapping. Slot is UI position only, not business identity.
    - stockpile_counts:
        Runtime inventory ledger by ingredient.
    - cookers / assembly:
        Runtime resource states used by scheduler and executor.
    - reservations:
        Explicit inflight scheduling/execution reservations keyed by order_id.
    - timestamps:
        Timing windows for animation / cooldown / observability.

    Locking contract:
    - All writes must happen under `async with state.lock:`.
    - Reads that require a consistent snapshot should also happen under the same lock.
    """
    orders: list[Order | None] = field(default_factory=lambda: [None] * 4)

    # Runtime stock ledger only. Slot-to-ingredient assignment belongs to SessionState.
    stockpile_counts: Counter[str] = field(default_factory=Counter)

    # Explicit runtime resource states.
    cookers: dict[str, CookerState] = field(default_factory=dict)
    assembly: AssemblyState = field(default_factory=AssemblyState)

    # Explicit inflight reservations, keyed by order_id.
    reservations: dict[int, OrderReservation] = field(default_factory=dict)

    completed_orders_count: int = 0
    rush_order_timeout: float = 20.0

    timestamps: RuntimeTimestamps = field(default_factory=RuntimeTimestamps)

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # -------------------------------------------------------------------------
    # Order lookup / slot mapping
    # -------------------------------------------------------------------------

    def get_order_by_id(self, order_id: int) -> Order | None:
        """Find an order by business identity across all visible slots."""
        for order in self.orders:
            if order is not None and order.order_id == order_id:
                return order
        return None

    def get_order_slot_index_by_id(self, order_id: int) -> int:
        """Return current visible slot index for an order_id, or -1 if not found."""
        for idx, order in enumerate(self.orders):
            if order is not None and order.order_id == order_id:
                return idx
        return -1

    def get_order_by_slot(self, slot_idx: int) -> Order | None:
        """Get order at a specific slot. Raises IndexError for invalid slot."""
        return self.orders[slot_idx]

    def set_order_at_slot(self, slot_idx: int, order: Order | None) -> None:
        """Place or replace visible order at slot."""
        self.orders[slot_idx] = order
        if order is not None:
            self._ensure_reservation(order.order_id)

    def remove_order_by_id(self, order_id: int) -> int | None:
        """
        Remove visible order by business identity.
        Returns original slot index if found, else None.
        """
        for idx, order in enumerate(self.orders):
            if order is not None and order.order_id == order_id:
                self.orders[idx] = None
                return idx
        return None

    def advance_slots(self) -> None:
        """
        Compact visible order slots leftward after a submit/timeout.

        Note:
        This only updates internal slot mapping. It does not mean the actual UI
        animation has already finished. Callers should update timing windows
        (e.g. timestamps.slot_animation_until) separately.
        """
        new_orders: list[Order | None] = [
            o for o in self.orders
            if o is not None and not o.done
        ]
        while len(new_orders) < len(self.orders):
            new_orders.append(None)
        self.orders = new_orders

    def replace_visible_orders(self, new_orders: list[Order | None]) -> None:
        """
        Replace the full visible slot mapping from detection result.
        Reservations are preserved by order_id.
        """
        if len(new_orders) != len(self.orders):
            raise ValueError(f"Expected {len(self.orders)} order slots, got {len(new_orders)}")
        self.orders = list(new_orders)
        for order in self.orders:
            if order is not None:
                self._ensure_reservation(order.order_id)

    # -------------------------------------------------------------------------
    # Reservation helpers
    # -------------------------------------------------------------------------

    def _ensure_reservation(self, order_id: int) -> OrderReservation:
        if order_id not in self.reservations:
            self.reservations[order_id] = OrderReservation()
        return self.reservations[order_id]

    def get_reservation(self, order_id: int) -> OrderReservation:
        """Get or create reservation record for an order."""
        return self._ensure_reservation(order_id)

    def reserve_prep(self, order_id: int) -> bool:
        """Reserve ingredient preparation for an order."""
        reservation = self._ensure_reservation(order_id)
        if reservation.prep_reserved:
            return False
        reservation.prep_reserved = True
        return True

    def release_prep(self, order_id: int) -> None:
        """Release ingredient preparation reservation for an order."""
        reservation = self._ensure_reservation(order_id)
        reservation.prep_reserved = False

    def reserve_finish(self, order_id: int) -> bool:
        """Reserve finishing (season + serve) for an order."""
        reservation = self._ensure_reservation(order_id)
        if reservation.finish_reserved:
            return False
        reservation.finish_reserved = True
        return True

    def release_finish(self, order_id: int) -> None:
        """Release finishing reservation for an order."""
        reservation = self._ensure_reservation(order_id)
        reservation.finish_reserved = False

    def clear_order_reservations(self, order_id: int) -> None:
        """Clear all explicit reservations for an order."""
        self.reservations.pop(order_id, None)

    # -------------------------------------------------------------------------
    # Assembly helpers
    # -------------------------------------------------------------------------

    def is_assembly_free(self) -> bool:
        """Check if assembly station is free."""
        return self.assembly.is_free()

    def is_assembly_owned_by(self, order_id: int) -> bool:
        """Check whether assembly is currently owned by the given order."""
        return self.assembly.owner_order_id == order_id

    def reserve_assembly(self, order_id: int, ts: float | None = None) -> bool:
        """
        Reserve assembly for an order.
        Returns False if assembly is already owned by another order.
        """
        if self.assembly.owner_order_id is not None:
            return False
        self.assembly.owner_order_id = order_id
        self.assembly.reserved_ts = ts
        return True

    def release_assembly_owner(self, order_id: int) -> None:
        """
        Release assembly ownership only.
        Does not automatically clear ingredients.
        """
        if self.assembly.owner_order_id == order_id:
            self.assembly.owner_order_id = None
            self.assembly.reserved_ts = None

    def clear_assembly_contents(self) -> None:
        """Clear all ingredients currently tracked on assembly."""
        owner_id = self.assembly.owner_order_id
        self.assembly.ingredients.clear()
        if owner_id is not None:
            order = self.get_order_by_id(owner_id)
            if order is not None:
                order.ingredients_at_assembly.clear()

    def reset_assembly(self) -> None:
        """Fully reset assembly state."""
        self.assembly.owner_order_id = None
        self.assembly.ingredients.clear()
        self.assembly.reserved_ts = None

    def add_to_assembly(self, order_id: int, ingredient: str) -> bool:
        """
        Add cooked ingredient to assembly.
        Returns False if the assembly is not owned by this order.
        Also updates the order's ingredients_at_assembly list.
        """
        if self.assembly.owner_order_id != order_id:
            return False
        self.assembly.ingredients.append(ingredient)
        order = self.get_order_by_id(order_id)
        if order is not None:
            order.ingredients_at_assembly.append(ingredient)
        return True

    # -------------------------------------------------------------------------
    # Cooker helpers
    # -------------------------------------------------------------------------

    def is_cooker_free(self, cooker_name: str) -> bool:
        """Check if cooker is free."""
        cooker = self.cookers.get(cooker_name)
        return cooker is not None and cooker.is_free()

    def occupy_cooker(
        self,
        cooker_name: str,
        ingredient_name: str,
        order_id: int | None,
        destination: CookerDestination,
        ready_at: float | None = None,
        clear_by: float | None = None,
    ) -> bool:
        """
        Occupy a cooker with explicit runtime metadata.
        Returns False if the cooker is already busy or not found.
        """
        cooker = self.cookers.get(cooker_name)
        if cooker is None or cooker.busy:
            return False

        cooker.busy = True
        cooker.ingredient_name = ingredient_name
        cooker.order_id = order_id
        cooker.destination = destination
        cooker.ready_at = ready_at
        cooker.clear_by = clear_by
        return True

    def release_cooker(self, cooker_name: str) -> None:
        """Fully reset a cooker to free state."""
        cooker = self.cookers[cooker_name]
        cooker.busy = False
        cooker.ingredient_name = None
        cooker.order_id = None
        cooker.destination = None
        cooker.ready_at = None
        cooker.clear_by = None

    def get_cooker_state(self, cooker_name: str) -> CookerState:
        """Get a cooker state object. Raises KeyError if cooker doesn't exist."""
        return self.cookers[cooker_name]

    def get_ready_cookers(self, now: float) -> list[tuple[str, CookerState]]:
        """Return all cookers whose items should be ready by now."""
        return [
            (name, cooker)
            for name, cooker in self.cookers.items()
            if cooker.is_ready(now)
        ]

    def get_overdue_cookers(self, now: float) -> list[tuple[str, CookerState]]:
        """Return all cookers that passed their safe clear deadline."""
        return [
            (name, cooker)
            for name, cooker in self.cookers.items()
            if cooker.is_overdue(now)
        ]

    # -------------------------------------------------------------------------
    # Stockpile helpers
    # -------------------------------------------------------------------------

    def get_stock_count(self, ingredient: str) -> int:
        """Get current runtime stock count for an ingredient."""
        return self.stockpile_counts.get(ingredient, 0)

    def increment_stock(self, ingredient: str, amount: int = 1) -> None:
        """Increase stockpile count."""
        self.stockpile_counts[ingredient] += amount

    def decrement_stock(self, ingredient: str, amount: int = 1) -> bool:
        """
        Decrease stockpile count.
        Returns False if insufficient stock.
        """
        current = self.stockpile_counts.get(ingredient, 0)
        if current < amount:
            return False

        new_value = current - amount
        if new_value == 0:
            self.stockpile_counts.pop(ingredient, None)
        else:
            self.stockpile_counts[ingredient] = new_value
        return True

    # -------------------------------------------------------------------------
    # Completion / lifecycle helpers
    # -------------------------------------------------------------------------

    def record_order_completion(self, ts: float) -> None:
        """Record successful order completion."""
        self.completed_orders_count += 1
        self.timestamps.last_order_completion_ts = ts

    def remove_completed_or_missing_reservations(self) -> None:
        """
        Best-effort cleanup for reservation records that no longer correspond to visible orders.
        Useful after reconciliation or timeout processing.

        Note:
        If you want reservations to persist even after an order leaves the visible slots,
        do not call this method automatically.
        """
        visible_order_ids = {
            order.order_id
            for order in self.orders
            if order is not None
        }
        stale_ids = [order_id for order_id in self.reservations if order_id not in visible_order_ids]
        for order_id in stale_ids:
            self.reservations.pop(order_id, None)

    # -------------------------------------------------------------------------
    # Query helpers for scheduler
    # -------------------------------------------------------------------------

    def count_active_orders(self) -> int:
        """Count visible orders that are not done."""
        return sum(1 for order in self.orders if order is not None and not order.done)

    def has_pending_orders(self) -> bool:
        """Whether there is any visible order not yet done."""
        return any(order is not None and not order.done for order in self.orders)

    def get_pending_orders(self) -> list[tuple[int, Order]]:
        """Get visible unfinished orders with current slot indices."""
        return [
            (idx, order)
            for idx, order in enumerate(self.orders)
            if order is not None and not order.done
        ]

    def get_orders_needing_prep(self) -> list[tuple[int, Order]]:
        """
        Get unfinished visible orders that are still in PENDING stage
        and are not currently prep-reserved.
        """
        result: list[tuple[int, Order]] = []
        for idx, order in enumerate(self.orders):
            if order is None or order.done:
                continue
            if order.current_stage != OrderStage.PENDING:
                continue

            reservation = self._ensure_reservation(order.order_id)
            if reservation.prep_reserved:
                continue

            result.append((idx, order))
        return result

    def get_orders_ready_to_season(self) -> list[tuple[int, Order]]:
        """
        Get unfinished visible orders that are in READY_TO_SEASON stage
        and are not currently finish-reserved.
        """
        result: list[tuple[int, Order]] = []
        for idx, order in enumerate(self.orders):
            if order is None or order.done:
                continue
            if order.current_stage != OrderStage.READY_TO_SEASON:
                continue

            reservation = self._ensure_reservation(order.order_id)
            if reservation.finish_reserved:
                continue

            result.append((idx, order))
        return result

    def is_ui_stable(self, now: float) -> bool:
        """
        Whether the UI is currently outside known animation/cooldown windows.
        """
        return (
            now >= self.timestamps.slot_animation_until
            and now >= self.timestamps.ui_cooldown_until
        )


class SessionState:
    """
    Session-scoped static state.

    Holds recipe references and stockpile slot assignments selected at session start.
    It must not hold runtime-mutating inventory/resource state.
    """

    def __init__(
        self,
        ordered_recipes: list[Recipe],
        stockpile_assignments: list[str] | None = None,
    ):
        self.ordered_recipes = ordered_recipes
        self.stockpile_assignments: list[str] = stockpile_assignments or []

    def get_cooker_for(self, ingredient: str, recipe: Recipe) -> str | None:
        """Find which cooker an ingredient uses in a specific recipe."""
        try:
            idx = recipe.raw_ingredients.index(ingredient)
            return recipe.cookers[idx]
        except ValueError:
            return None

    def get_cook_duration(self, ingredient: str, recipe: Recipe) -> float | None:
        """Find cook duration for an ingredient in a specific recipe."""
        try:
            idx = recipe.raw_ingredients.index(ingredient)
            return recipe.cook_durations[idx]
        except ValueError:
            return None

    def get_stockpile_ingredient(self, slot_idx: int) -> str | None:
        """Get which ingredient is assigned to a stockpile slot."""
        if 0 <= slot_idx < len(self.stockpile_assignments):
            return self.stockpile_assignments[slot_idx]
        return None


_global_game_state: GameState | None = None
_global_session_state: SessionState | None = None


def init_game_state(cookers: list[str]) -> GameState:
    """
    Initialize global GameState once per session.

    Raises:
        RuntimeError: if GameState has already been initialized.
    """
    global _global_game_state
    if _global_game_state is not None:
        raise RuntimeError("GameState already initialized. Reset before re-initializing.")

    _global_game_state = GameState(
        orders=[None] * 4,
        stockpile_counts=Counter(),
        cookers={name: CookerState() for name in cookers},
        assembly=AssemblyState(),
        reservations={},
    )
    return _global_game_state


def init_session_state(
    ordered_recipes: list[Recipe],
    stockpile_assignments: list[str] | None = None,
) -> SessionState:
    """
    Initialize global SessionState once per session.

    Raises:
        RuntimeError: if SessionState has already been initialized.
    """
    global _global_session_state
    if _global_session_state is not None:
        raise RuntimeError("SessionState already initialized. Reset before re-initializing.")

    _global_session_state = SessionState(ordered_recipes, stockpile_assignments)
    return _global_session_state


def get_game_state() -> GameState:
    """Get the global GameState instance. Raises if not initialized."""
    if _global_game_state is None:
        raise RuntimeError("GameState not initialized. Call init_game_state() first.")
    return _global_game_state


def get_session_state() -> SessionState:
    """Get the global SessionState instance. Raises if not initialized."""
    if _global_session_state is None:
        raise RuntimeError("SessionState not initialized. Call init_session_state() first.")
    return _global_session_state


def reset_global_state() -> None:
    """Reset global state holders. Intended for tests or clean session teardown."""
    global _global_game_state, _global_session_state
    _global_game_state = None
    _global_session_state = None