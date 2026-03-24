"""
游戏环境模拟器

地位：独立实现游戏规则的状态机，不依赖 Scheduler/Executor/Airtest。
      作为游戏规则的参考实现，用于验证真实系统的行为是否符合规则。

输入：手动注入订单、执行操作、推进时间
输出：事件序列（Event 列表）、可查询的当前状态

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新
"""

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


# ============================================================================
# 事件类型
# ============================================================================


class EventType(Enum):
    SWIPE = auto()
    ORDER_APPEARED = auto()
    ORDER_TIMEOUT = auto()
    COOKING_DONE = auto()
    INGREDIENT_EXPIRED = auto()
    ORDER_SERVED = auto()
    SLOTS_ADVANCED = auto()


@dataclass
class Event:
    type: EventType
    time: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)

    def __repr__(self):
        parts = [f"[{self.time:6.2f}s] {self.type.name}"]
        for k, v in self.detail.items():
            parts.append(f"{k}={v}")
        return " | ".join(parts)


# ============================================================================
# 数据结构
# ============================================================================


class OrderStage(Enum):
    PENDING = auto()
    HEATING = auto()
    READY_TO_SEASON = auto()
    SEASONING = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class Ingredient:
    name: str
    cooker: str
    duration: float


@dataclass
class Recipe:
    name: str
    ingredients: list[Ingredient]
    condiments: dict[str, int]  # condiment_name → count


@dataclass
class Order:
    recipe: Recipe
    is_rush: bool = False
    order_id: int = 0
    stage: OrderStage = OrderStage.PENDING
    ingredients_at_assembly: list[str] = field(default_factory=list)
    condiments_done: dict[str, int] = field(default_factory=dict)
    done: bool = False
    failed: bool = False
    created_at: float = 0.0
    served_at: float | None = None


@dataclass
class CookerState:
    busy: bool = False
    ingredient_name: str | None = None
    done_at: float | None = None  # 烹饪完成时刻
    clear_by: float | None = None  # 过期时刻（done_at + 5s）


@dataclass
class AssemblyState:
    owner_order_id: int | None = None
    ingredients: list[str] = field(default_factory=list)


@dataclass
class StockpileSlot:
    ingredient: str | None = None
    count: int = 0


# ============================================================================
# 游戏模拟器
# ============================================================================


class GameSimulator:
    """
    游戏环境模拟器。

    纯状态机，不执行真实 UI 操作。通过 tick(dt) 推进时间，
    通过 execute_* 方法执行玩家操作，通过 events 查询事件。
    """

    MAX_SLOTS = 4
    MAX_STOCKPILE = 5
    COOKER_RETENTION = 5.0  # 灶台食材保留时间（秒）
    ANIMATION_DURATION = 1.5  # slot 位移动画时间（秒）

    def __init__(self):
        self.time: float = 0.0

        self.orders: list[Order | None] = [None] * self.MAX_SLOTS
        self.cookers: dict[str, CookerState] = {}
        self.assembly = AssemblyState()
        self.stockpile: dict[str, StockpileSlot] = {}  # slot_name → StockpileSlot
        self.stockpile_positions: list[str] = []  # slot 名称列表

        self._events: list[Event] = []
        self._next_order_id: int = 1
        self._animation_until: float = 0.0  # 动画窗口结束时刻
        self._pending_orders: list[tuple[Order, float]] = []  # (order, appear_at)

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------

    def setup_cookers(self, names: list[str]) -> None:
        """初始化灶台"""
        self.cookers = {name: CookerState() for name in names}

    def setup_stockpile(self, slots: list[str]) -> None:
        """初始化库存区"""
        self.stockpile_positions = slots
        self.stockpile = {s: StockpileSlot() for s in slots}

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------

    def _emit(self, event_type: EventType, **detail: Any) -> None:
        self._events.append(Event(event_type, self.time, detail))

    def drain_events(self) -> list[Event]:
        """取出并清空事件队列"""
        events = self._events[:]
        self._events.clear()
        return events

    @property
    def events(self) -> list[Event]:
        """只读事件列表"""
        return list(self._events)

    # ------------------------------------------------------------------
    # 订单管理
    # ------------------------------------------------------------------

    def inject_order(
        self,
        slot_idx: int,
        recipe: Recipe,
        is_rush: bool = False,
        condiments: dict[str, int] | None = None,
    ) -> Order:
        """
        将订单注入指定 slot。

        Args:
            slot_idx: 0-3
            recipe: 配方
            is_rush: 是否 rush 订单
            condiments: 调料偏好，如 {"hearthspice": 1}。None 则用配方默认值。

        Returns:
            创建的 Order 对象
        """
        if slot_idx < 0 or slot_idx >= self.MAX_SLOTS:
            raise ValueError(f"slot_idx must be 0-{self.MAX_SLOTS - 1}, got {slot_idx}")
        if self.orders[slot_idx] is not None:
            raise ValueError(f"Slot {slot_idx} is occupied")

        order = Order(
            recipe=recipe,
            is_rush=is_rush,
            order_id=self._next_order_id,
            condiments_done={},
            created_at=self.time,
        )
        self._next_order_id += 1

        if condiments is not None:
            order.recipe = Recipe(
                name=recipe.name,
                ingredients=recipe.ingredients,
                condiments=dict(condiments),  # 深拷贝，避免与 condiments_done 共享
            )

        self.orders[slot_idx] = order
        self._emit(
            EventType.ORDER_APPEARED,
            order_id=order.order_id,
            recipe=recipe.name,
            slot=slot_idx,
            rush=is_rush,
        )
        return order

    def schedule_order(
        self,
        recipe: Recipe,
        is_rush: bool = False,
        condiments: dict[str, int] | None = None,
        appear_at: float = 0.0,
    ) -> None:
        """
        调度一个订单在未来出现（自动寻找空 slot）。
        """
        self._pending_orders.append(
            (Order(
                recipe=recipe,
                is_rush=is_rush,
                order_id=self._next_order_id,
                condiments_done={},
                created_at=appear_at,
            ), appear_at)
        )
        self._next_order_id += 1

    def get_order(self, slot_idx: int) -> Order | None:
        """获取指定 slot 的订单"""
        if 0 <= slot_idx < self.MAX_SLOTS:
            return self.orders[slot_idx]
        return None

    def get_order_slot(self, order_id: int) -> int:
        """查找订单所在 slot，未找到返回 -1"""
        for i, order in enumerate(self.orders):
            if order is not None and order.order_id == order_id:
                return i
        return -1

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------

    def start_cooking(self, ingredient_name: str, cooker_name: str) -> bool:
        """
        开始烹饪：食材区 → 灶台。

        不检查灶台是否 busy：并发执行中 scheduler 已保证分配正确，
        bridge 的状态可能和 executor 不同步。

        Returns:
            是否成功
        """
        if cooker_name not in self.cookers:
            return False
        cooker = self.cookers[cooker_name]

        duration = self._get_cook_duration(ingredient_name)
        if duration is None:
            return False

        cooker.busy = True
        cooker.ingredient_name = ingredient_name
        cooker.done_at = self.time + duration
        cooker.clear_by = None

        order_id = self._find_order_needing(ingredient_name)
        if order_id is not None:
            order = self._get_order_by_id(order_id)
            if order and order.stage == OrderStage.PENDING:
                order.stage = OrderStage.HEATING

        self._emit(
            EventType.SWIPE,
            action="cook",
            start=f"ingredient:{ingredient_name}",
            end=f"cooker:{cooker_name}",
        )
        return True

    def move_to_assembly(self, cooker_name: str) -> bool:
        """
        将灶台上的成品移到组装站。

        Returns:
            是否成功
        """
        if cooker_name not in self.cookers:
            return False
        cooker = self.cookers[cooker_name]
        if not cooker.busy or cooker.ingredient_name is None:
            return False
        if cooker.done_at is not None and self.time < cooker.done_at:
            return False  # 还没烹饪完

        ingredient = cooker.ingredient_name
        order_id = self.assembly.owner_order_id
        target_order_id = self._find_order_needing(ingredient)

        if order_id is None:
            if target_order_id is not None:
                self.assembly.owner_order_id = target_order_id
                order_id = target_order_id
            else:
                return False
        elif target_order_id is not None and target_order_id != order_id:
            return False  # 组装站被其他订单占用

        self.assembly.ingredients.append(ingredient)
        self._free_cooker(cooker_name)

        if order_id is not None:
            self._check_order_ready(order_id)

        self._emit(
            EventType.SWIPE,
            action="move_to_assembly",
            start=f"cooker:{cooker_name}",
            end="assembly",
        )
        return True

    def move_to_stockpile(self, cooker_name: str, slot_name: str) -> bool:
        """
        将灶台上的成品移到库存区。

        Returns:
            是否成功
        """
        if cooker_name not in self.cookers:
            return False
        cooker = self.cookers[cooker_name]
        if not cooker.busy or cooker.ingredient_name is None:
            return False
        if cooker.done_at is not None and self.time < cooker.done_at:
            return False
        if slot_name not in self.stockpile:
            return False

        ingredient = cooker.ingredient_name
        slot = self.stockpile[slot_name]

        if slot.ingredient is not None and slot.ingredient != ingredient:
            return False  # slot 存的是不同食材
        if slot.count >= self.MAX_STOCKPILE:
            return False

        slot.ingredient = ingredient
        slot.count += 1
        self._free_cooker(cooker_name)

        self._emit(
            EventType.SWIPE,
            action="move_to_stockpile",
            start=f"cooker:{cooker_name}",
            end=f"stockpile:{slot_name}",
        )
        return True

    def pull_from_stockpile(self, slot_name: str) -> bool:
        """
        从库存区取出食材到组装站。

        Returns:
            是否成功
        """
        if slot_name not in self.stockpile:
            return False
        slot = self.stockpile[slot_name]
        if slot.count <= 0 or slot.ingredient is None:
            return False

        ingredient = slot.ingredient
        order_id = self.assembly.owner_order_id
        target_order_id = self._find_order_needing(ingredient)

        if order_id is None:
            if target_order_id is not None:
                self.assembly.owner_order_id = target_order_id
                order_id = target_order_id
            else:
                return False
        elif target_order_id is not None and target_order_id != order_id:
            return False

        slot.count -= 1
        if slot.count == 0:
            slot.ingredient = None

        self.assembly.ingredients.append(ingredient)

        if order_id is not None:
            self._check_order_ready(order_id)

        self._emit(
            EventType.SWIPE,
            action="pull_from_stockpile",
            start=f"stockpile:{slot_name}",
            end="assembly",
        )
        return True

    def add_condiment(self, condiment_name: str) -> bool:
        """
        向当前组装站归属订单添加一份调料。

        Returns:
            是否成功
        """
        order_id = self.assembly.owner_order_id
        if order_id is None:
            return False
        order = self._get_order_by_id(order_id)
        if order is None:
            return False

        current = order.condiments_done.get(condiment_name, 0)
        needed = order.recipe.condiments.get(condiment_name, 0)
        if current >= needed:
            return False  # 已满足

        order.condiments_done[condiment_name] = current + 1
        order.stage = OrderStage.SEASONING

        self._emit(
            EventType.SWIPE,
            action="add_condiment",
            start=f"condiment:{condiment_name}",
            end="assembly",
        )

        self._check_order_ready(order_id)
        return True

    def serve_order(self, slot_idx: int) -> bool:
        """
        提交订单：组装站 → 取餐台，然后位移 slot。

        动画窗口内禁止提交（§2.3：禁送餐提交）。

        Returns:
            是否成功
        """
        if slot_idx < 0 or slot_idx >= self.MAX_SLOTS:
            return False
        order = self.orders[slot_idx]
        if order is None:
            return False
        if order.stage != OrderStage.READY_TO_SEASON:
            return False
        if self.time < self._animation_until:
            return False  # 动画窗口内禁止提交

        order.done = True
        order.served_at = self.time
        order.stage = OrderStage.COMPLETED

        served_order_id = order.order_id
        self.assembly.owner_order_id = None
        self.assembly.ingredients.clear()

        self._emit(
            EventType.SWIPE,
            action="serve",
            start="assembly",
            end=f"pickup:slot{slot_idx}",
            duration=0.2,
        )
        self._emit(
            EventType.ORDER_SERVED,
            order_id=served_order_id,
            slot=slot_idx,
            recipe=order.recipe.name,
        )

        self._advance_slots()
        return True

    def clear_cooker(self, cooker_name: str) -> bool:
        """
        清理过期食材：灶台 → 垃圾桶。

        Returns:
            是否成功
        """
        if cooker_name not in self.cookers:
            return False
        cooker = self.cookers[cooker_name]
        if not cooker.busy:
            return False
        if cooker.clear_by is None or self.time < cooker.clear_by:
            return False  # 未过期

        self._free_cooker(cooker_name)
        self._emit(
            EventType.SWIPE,
            action="clear_to_trash",
            start=f"cooker:{cooker_name}",
            end="trash",
        )
        return True

    # ------------------------------------------------------------------
    # 时间推进
    # ------------------------------------------------------------------

    def tick(self, dt: float) -> list[Event]:
        """
        推进一个时间步，处理自动事件。

        自动处理：
        - 灶台烹饪完成 → COOKING_DONE 事件
        - 灶台食材过期 → INGREDIENT_EXPIRED 事件
        - 订单超时 → ORDER_TIMEOUT 事件
        - 动画窗口结束 → 扫描新订单

        Args:
            dt: 时间步长（秒）

        Returns:
            本次 tick 产生的事件列表
        """
        prev_events = len(self._events)
        self.time += dt

        ui_stable = self.time >= self._animation_until

        # 检查订单超时
        for i, order in enumerate(self.orders):
            if order is not None and not order.done and not order.failed:
                if order.is_rush:
                    timeout = 20.0
                else:
                    timeout = 30.0
                if self.time - order.created_at > timeout:
                    order.failed = True
                    order.stage = OrderStage.FAILED
                    self._emit(
                        EventType.ORDER_TIMEOUT,
                        order_id=order.order_id,
                        slot=i,
                        recipe=order.recipe.name,
                    )

        # 检查灶台烹饪完成
        for cooker_name, cooker in self.cookers.items():
            if cooker.busy and cooker.done_at is not None and self.time >= cooker.done_at:
                if cooker.clear_by is None:
                    cooker.clear_by = cooker.done_at + self.COOKER_RETENTION
                    self._emit(
                        EventType.COOKING_DONE,
                        ingredient=cooker.ingredient_name,
                        cooker=cooker_name,
                    )

        # 检查灶台食材过期
        for cooker_name, cooker in self.cookers.items():
            if (
                cooker.busy
                and cooker.clear_by is not None
                and self.time >= cooker.clear_by
            ):
                self._emit(
                    EventType.INGREDIENT_EXPIRED,
                    ingredient=cooker.ingredient_name,
                    cooker=cooker_name,
                )

        # 扫描空 slot，注入待处理订单
        if ui_stable:
            still_pending: list[tuple[Order, float]] = []
            for order, appear_at in self._pending_orders:
                if self.time >= appear_at:
                    injected = False
                    for slot_idx in range(self.MAX_SLOTS):
                        if self.orders[slot_idx] is None:
                            self.orders[slot_idx] = order
                            self._emit(
                                EventType.ORDER_APPEARED,
                                order_id=order.order_id,
                                recipe=order.recipe.name,
                                slot=slot_idx,
                                rush=order.is_rush,
                            )
                            injected = True
                            break
                    if not injected:
                        still_pending.append((order, appear_at))
                else:
                    still_pending.append((order, appear_at))
            self._pending_orders = still_pending

        return self._events[prev_events:]

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_assembly_ingredients(self) -> list[str]:
        """获取组装站当前食材"""
        return list(self.assembly.ingredients)

    def get_stockpile_count(self, ingredient_name: str) -> int:
        """查询某食材的总库存量"""
        total = 0
        for slot in self.stockpile.values():
            if slot.ingredient == ingredient_name:
                total += slot.count
        return total

    def get_cooker_state(self, cooker_name: str) -> CookerState | None:
        return self.cookers.get(cooker_name)

    def is_assembly_free(self) -> bool:
        return self.assembly.owner_order_id is None

    def get_overdue_cookers(self) -> list[str]:
        """获取已过期但未清理的灶台"""
        overdue = []
        for name, cooker in self.cookers.items():
            if (
                cooker.busy
                and cooker.clear_by is not None
                and self.time >= cooker.clear_by
            ):
                overdue.append(name)
        return overdue

    def snapshot(self) -> dict:
        """返回当前状态快照，用于断言"""
        return {
            "time": self.time,
            "orders": [
                {
                    "order_id": o.order_id,
                    "recipe": o.recipe.name,
                    "stage": o.stage.name,
                    "done": o.done,
                    "failed": o.failed,
                    "is_rush": o.is_rush,
                    "assembly_ingredients": list(o.ingredients_at_assembly),
                }
                if o is not None
                else None
                for o in self.orders
            ],
            "cookers": {
                name: {
                    "busy": c.busy,
                    "ingredient": c.ingredient_name,
                    "done_at": c.done_at,
                    "clear_by": c.clear_by,
                }
                for name, c in self.cookers.items()
            },
            "assembly": {
                "owner": self.assembly.owner_order_id,
                "ingredients": list(self.assembly.ingredients),
            },
            "stockpile": {
                name: {"ingredient": s.ingredient, "count": s.count}
                for name, s in self.stockpile.items()
            },
            "assembly_free": self.is_assembly_free(),
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _free_cooker(self, cooker_name: str) -> None:
        cooker = self.cookers[cooker_name]
        cooker.busy = False
        cooker.ingredient_name = None
        cooker.done_at = None
        cooker.clear_by = None

    def _get_cook_duration(self, ingredient_name: str) -> float | None:
        """从已有订单的配方中查找烹饪时间"""
        for order in self.orders:
            if order is None or order.done or order.failed:
                continue
            for ing in order.recipe.ingredients:
                if ing.name == ingredient_name:
                    return ing.duration
        return None

    def _find_order_needing(self, ingredient_name: str) -> int | None:
        """找到第一个需要此食材且尚未拥有的订单"""
        for order in self.orders:
            if order is None or order.done or order.failed:
                continue
            if order.stage not in (
                OrderStage.PENDING,
                OrderStage.HEATING,
            ):
                continue
            for ing in order.recipe.ingredients:
                if ing.name == ingredient_name:
                    if ingredient_name not in order.ingredients_at_assembly:
                        return order.order_id
        return None

    def _get_order_by_id(self, order_id: int) -> Order | None:
        for order in self.orders:
            if order is not None and order.order_id == order_id:
                return order
        return None

    def _check_order_ready(self, order_id: int) -> None:
        """检查订单是否所有食材+调料都已到位"""
        order = self._get_order_by_id(order_id)
        if order is None:
            return

        required_ing = Counter(ing.name for ing in order.recipe.ingredients)
        at_assembly = Counter(self.assembly.ingredients)

        all_ingredients = all(
            at_assembly.get(name, 0) >= count
            for name, count in required_ing.items()
        )

        all_condiments = all(
            order.condiments_done.get(name, 0) >= count
            for name, count in order.recipe.condiments.items()
        )

        if all_ingredients and all_condiments:
            order.stage = OrderStage.READY_TO_SEASON

    def _advance_slots(self) -> None:
        """位移 slot：移除已完成/失败的订单，空位移到右侧"""
        non_empty = [
            o for o in self.orders
            if o is not None and not o.done and not o.failed
        ]
        self.orders = non_empty + [None] * (self.MAX_SLOTS - len(non_empty))
        self._animation_until = self.time + self.ANIMATION_DURATION
        self._emit(EventType.SLOTS_ADVANCED)
