"""
游戏环境（真实游戏）

地位：追踪真实游戏的状态，通过程序逻辑维护灶台、组装站、库存状态
      接口供 Agent 使用

输入：UI操作结果、订单检测结果
输出：游戏状态供Agent决策

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger


# ============================================================================
# 状态数据结构
# ============================================================================

@dataclass
class CookerState:
    """灶台状态"""
    busy: bool = False
    ingredient_name: Optional[str] = None
    cooker_type: Optional[str] = None
    started_at: Optional[float] = None
    done_at: Optional[float] = None

    def reset(self) -> None:
        """重置灶台状态"""
        self.busy = False
        self.ingredient_name = None
        self.cooker_type = None
        self.started_at = None
        self.done_at = None


@dataclass
class AssemblyState:
    """组装站状态"""
    ingredients: list[str] = field(default_factory=list)
    target_recipe_slug: Optional[str] = None
    owner_order_id: Optional[int] = None
    condiments: dict[str, int] = field(default_factory=dict)

    @property
    def is_free(self) -> bool:
        """组装站是否空闲"""
        return len(self.ingredients) == 0 and self.target_recipe_slug is None

    def reset(self) -> None:
        """重置组装站状态"""
        self.ingredients.clear()
        self.target_recipe_slug = None
        self.owner_order_id = None
        self.condiments.clear()


@dataclass
class StockpileSlot:
    """库存槽位"""
    ingredient_name: Optional[str] = None
    cooker_type: Optional[str] = None
    count: int = 0

    def can_add(self, ingredient: str, cooker: str) -> bool:
        """检查是否可以添加食材"""
        if self.ingredient_name is None:
            return True
        return self.ingredient_name == ingredient and self.cooker_type == cooker

    def add(self, ingredient: str, cooker: str) -> bool:
        """添加食材"""
        if not self.can_add(ingredient, cooker):
            return False
        if self.ingredient_name is None:
            self.ingredient_name = ingredient
            self.cooker_type = cooker
        self.count += 1
        return True

    def remove(self) -> bool:
        """移除一个食材"""
        if self.count <= 0:
            return False
        self.count -= 1
        if self.count == 0:
            self.ingredient_name = None
            self.cooker_type = None
        return True


@dataclass
class OrderInfo:
    """订单信息"""
    order_id: int
    recipe_slug: str
    is_rush: bool
    created_at: float
    timeout_at: float
    done: bool = False


# ============================================================================
# GameEnvironment
# ============================================================================

class GameEnvironment:
    """
    真实游戏环境

    通过程序逻辑追踪游戏状态，不依赖图像检测。
    """

    def __init__(
        self,
        cooker_names: list[str],
        stockpile_slots: int = 3,
        game_duration: float = 90.0,
    ):
        self.cookers: dict[str, CookerState] = {
            name: CookerState(cooker_type=name) for name in cooker_names
        }

        self.assembly = AssemblyState()

        self.stockpile: dict[str, StockpileSlot] = {
            f"slot{i}": StockpileSlot() for i in range(stockpile_slots)
        }

        self.orders: list[Optional[OrderInfo]] = [None] * 4

        self._game_start_time: Optional[float] = None
        self._game_duration = game_duration
        self._animation_until: float = 0.0
        self._next_order_id = 1

        logger.info(f"GameEnvironment initialized: {len(cooker_names)} cookers, {stockpile_slots} stockpile slots")

    # ========================================================================
    # 时间相关
    # ========================================================================

    @property
    def time(self) -> float:
        """当前游戏时间（秒）"""
        if self._game_start_time is None:
            return 0.0
        return time.time() - self._game_start_time

    def start_game(self) -> None:
        """开始游戏计时"""
        self._game_start_time = time.time()

    def is_game_over(self) -> bool:
        """游戏是否结束"""
        if self._game_start_time is None:
            return False
        return self.time >= self._game_duration

    def is_in_animation_window(self) -> bool:
        """是否在动画窗口期间"""
        return time.time() < self._animation_until

    def set_animation_window(self, duration: float = 1.5) -> None:
        """设置动画窗口"""
        self._animation_until = time.time() + duration

    # ========================================================================
    # 灶台操作
    # ========================================================================

    def start_cooking(self, ingredient: str, cooker: str, duration: float) -> bool:
        """开始烹饪"""
        if cooker not in self.cookers:
            logger.error(f"Unknown cooker: {cooker}")
            return False

        cooker_state = self.cookers[cooker]
        if cooker_state.busy:
            logger.warning(f"Cooker {cooker} is busy")
            return False

        now = time.time()
        cooker_state.busy = True
        cooker_state.ingredient_name = ingredient
        cooker_state.started_at = now
        cooker_state.done_at = now + duration
        return True

    def clear_cooker(self, cooker: str) -> bool:
        """清理灶台"""
        if cooker not in self.cookers:
            return False
        self.cookers[cooker].reset()
        return True

    # ========================================================================
    # 组装站操作
    # ========================================================================

    def add_to_assembly(
        self,
        ingredient: str,
        cooker: str,
        order_id: Optional[int] = None,
        recipe_slug: Optional[str] = None,
    ) -> bool:
        """添加食材到组装站"""
        if self.assembly.is_free:
            self.assembly.owner_order_id = order_id
            if recipe_slug:
                self.assembly.target_recipe_slug = recipe_slug
            elif order_id:
                order = self.get_order_by_id(order_id)
                if order:
                    self.assembly.target_recipe_slug = order.recipe_slug

        self.assembly.ingredients.append(ingredient)
        return True

    def add_condiment(self, condiment: str) -> bool:
        """添加调料到组装站"""
        current = self.assembly.condiments.get(condiment, 0)
        self.assembly.condiments[condiment] = current + 1
        return True

    def get_condiment_count(self, condiment: str) -> int:
        """获取已添加的调料数量"""
        return self.assembly.condiments.get(condiment, 0)

    def serve_order(self, slot_idx: int) -> bool:
        """送餐"""
        if slot_idx < 0 or slot_idx >= len(self.orders):
            return False

        order = self.orders[slot_idx]
        if order is None:
            return False

        order.done = True
        self.assembly.reset()
        self.set_animation_window(1.5)

        # 送餐后移除该订单
        self.orders[slot_idx] = None
        # 左移槽位
        self._shift_orders_left()

        logger.info(f"[t={self.time:.1f}s] Served order {order.order_id} ({order.recipe_slug}) slot {slot_idx} {'RUSH' if order.is_rush else 'normal'}")
        return True

    def _shift_orders_left(self) -> None:
        """压缩订单槽位，将 None 移到末尾"""
        non_null = [o for o in self.orders if o is not None]
        self.orders = non_null + [None] * (4 - len(non_null))

    # ========================================================================
    # 库存操作
    # ========================================================================

    def move_to_stockpile(self, cooker: str, slot: str) -> bool:
        """将灶台食材移动到库存"""
        if cooker not in self.cookers:
            return False

        cooker_state = self.cookers[cooker]
        if not cooker_state.busy:
            return False

        if slot not in self.stockpile:
            return False

        stockpile_slot = self.stockpile[slot]
        if not stockpile_slot.add(cooker_state.ingredient_name, cooker_state.cooker_type):
            return False

        self.cookers[cooker].reset()
        return True

    def pull_from_stockpile(self, slot: str) -> bool:
        """从库存取用食材到组装站"""
        if slot not in self.stockpile:
            return False

        stockpile_slot = self.stockpile[slot]
        if stockpile_slot.count <= 0:
            return False

        ingredient = stockpile_slot.ingredient_name
        self.assembly.ingredients.append(ingredient)
        stockpile_slot.remove()
        return True

    # ========================================================================
    # 订单操作
    # ========================================================================

    def add_order(self, slot_idx: int, recipe_slug: str, is_rush: bool) -> int | None:
        """添加新订单"""
        if slot_idx < 0 or slot_idx >= len(self.orders):
            return None

        order_id = self._next_order_id
        self._next_order_id += 1

        now = time.time()
        timeout = 40.0 if is_rush else 70.0

        self.orders[slot_idx] = OrderInfo(
            order_id=order_id,
            recipe_slug=recipe_slug,
            is_rush=is_rush,
            created_at=now,
            timeout_at=now + timeout,
        )

        logger.info(f"[t={self.time:.1f}s] New order {order_id}: {recipe_slug} ({'RUSH' if is_rush else 'normal'}) slot {slot_idx}")
        return order_id

    def check_and_remove_timed_out_orders(self) -> list[int]:
        """检查并移除超时订单，返回超时订单ID列表"""
        timed_out = []
        now = time.time()
        for i, order in enumerate(self.orders):
            if order is not None and not order.done and now >= order.timeout_at:
                timed_out.append(order.order_id)
                logger.warning(f"[t={self.time:.1f}s] Order {order.order_id} ({order.recipe_slug}) timed out in slot {i}")
                self.orders[i] = None

        if timed_out:
            self._shift_orders_left()

        return timed_out

    def get_order_by_id(self, order_id: int) -> Optional[OrderInfo]:
        """根据ID获取订单"""
        for order in self.orders:
            if order and order.order_id == order_id:
                return order
        return None

    def get_order_slot(self, order_id: int) -> Optional[int]:
        """获取订单所在的槽位索引"""
        for i, order in enumerate(self.orders):
            if order and order.order_id == order_id:
                return i
        return None

    # ========================================================================
    # 状态查询
    # ========================================================================

    def get_free_cookers(self) -> list[str]:
        """获取空闲灶台列表"""
        return [name for name, cooker in self.cookers.items() if not cooker.busy]

    def get_done_cookers(self) -> list[str]:
        """获取烹饪完成的灶台列表"""
        now = time.time()
        return [
            name for name, cooker in self.cookers.items()
            if cooker.busy and cooker.done_at and now >= cooker.done_at
        ]

    def get_stockpile_count(self, ingredient: str) -> int:
        """获取指定食材的库存数量"""
        for slot in self.stockpile.values():
            if slot.ingredient_name == ingredient:
                return slot.count
        return 0

    def find_stockpile_slot(self, ingredient: str) -> Optional[str]:
        """找到存储指定食材的库存槽位"""
        for slot_name, slot in self.stockpile.items():
            if slot.ingredient_name == ingredient and slot.count > 0:
                return slot_name
        return None

    def find_empty_stockpile_slot(self) -> Optional[str]:
        """找到空的库存槽位"""
        for slot_name, slot in self.stockpile.items():
            if slot.ingredient_name is None or slot.count == 0:
                return slot_name
        return None
