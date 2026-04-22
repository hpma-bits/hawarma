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
from typing import Optional

from loguru import logger

from .base_environment import (
    BaseEnvironment,
    CookerState,
    AssemblyState,
    StockpileSlot,
    OrderInfo,
)


class GameEnvironment(BaseEnvironment):
    """
    真实游戏环境

    继承 BaseEnvironment，通过程序逻辑追踪游戏状态，不依赖图像检测。
    """

    def __init__(
        self,
        cooker_names: list[str],
        stockpile_slots: int = 3,
        game_duration: float = 90.0,
        recipes: Optional[dict[str, object]] = None,
        cooker_retention: float = 5.0,
    ):
        self._cooker_retention = cooker_retention
        self._cookers: dict[str, CookerState] = {
            name: CookerState(cooker_type=name) for name in cooker_names
        }

        self._assembly = AssemblyState()

        self._stockpile: dict[str, StockpileSlot] = {
            f"slot{i}": StockpileSlot() for i in range(stockpile_slots)
        }

        self._orders: list[Optional[OrderInfo]] = [None] * 4

        self._game_start_time: Optional[float] = None
        self._game_duration = game_duration
        self._animation_until: float = 0.0
        self._next_order_id = 1

        # 配方数据（用于校验组装站操作）
        self._recipes = recipes or {}

        logger.info(
            f"GameEnvironment initialized: {len(cooker_names)} cookers, {stockpile_slots} stockpile slots"
        )

    # ========================================================================
    # BaseEnvironment 接口实现
    # ========================================================================

    @property
    def time(self) -> float:
        """当前游戏时间（秒）"""
        if self._game_start_time is None:
            return 0.0
        return time.time() - self._game_start_time

    @property
    def orders(self) -> list[Optional[OrderInfo]]:
        """当前订单列表"""
        return self._orders

    @property
    def cookers(self) -> dict[str, CookerState]:
        """灶台状态"""
        return self._cookers

    @property
    def assembly(self) -> AssemblyState:
        """组装站状态"""
        return self._assembly

    @property
    def stockpile(self) -> dict[str, StockpileSlot]:
        """库存状态"""
        return self._stockpile

    def is_in_animation_window(self) -> bool:
        """是否在动画窗口期间"""
        return time.time() < self._animation_until

    def start_cooking(self, ingredient: str, cooker: str, duration: float) -> bool:
        """开始烹饪"""
        if cooker not in self._cookers:
            logger.error(f"Unknown cooker: {cooker}")
            return False

        cooker_state = self._cookers[cooker]
        if cooker_state.busy:
            logger.warning(f"Cooker {cooker} is busy")
            return False

        cooker_state.busy = True
        cooker_state.ingredient_name = ingredient
        cooker_state.started_at = self.time
        cooker_state.done_at = self.time + duration
        cooker_state.expired_at = self.time + duration + self._cooker_retention
        return True

    def move_to_assembly(self, cooker: str) -> bool:
        """将灶台完成的食材移动到组装站"""
        if cooker not in self._cookers:
            return False

        cooker_state = self._cookers[cooker]
        if not cooker_state.busy or cooker_state.done_at is None:
            return False

        ingredient = cooker_state.ingredient_name
        if ingredient is None:
            return False

        # 食材已过期，拒绝移动
        if cooker_state.is_expired(self.time):
            logger.warning(
                f"[t={self.time:.1f}s] Ingredient {ingredient} on {cooker} expired, cannot move to assembly"
            )
            return False

        self._assembly.ingredients.append(ingredient)
        cooker_state.reset()
        return True

    def move_to_stockpile(self, cooker: str, slot: str) -> bool:
        """将灶台食材移动到库存"""
        if cooker not in self._cookers:
            return False

        cooker_state = self._cookers[cooker]
        if not cooker_state.busy:
            return False

        # 食材已过期，拒绝存入
        if cooker_state.is_expired(self.time):
            logger.warning(
                f"[t={self.time:.1f}s] Ingredient {cooker_state.ingredient_name} on {cooker} expired, cannot move to stockpile"
            )
            return False

        if slot not in self._stockpile:
            return False

        stockpile_slot = self._stockpile[slot]
        if not stockpile_slot.add(
            cooker_state.ingredient_name, cooker_state.cooker_type
        ):
            return False

        self._cookers[cooker].reset()
        return True

    def pull_from_stockpile(self, slot: str) -> bool:
        """从库存取用食材到组装站"""
        if slot not in self._stockpile:
            return False

        stockpile_slot = self._stockpile[slot]
        if stockpile_slot.count <= 0:
            return False

        ingredient = stockpile_slot.ingredient_name

        # 如果组装站为空，根据食材推断目标配方
        if self._assembly.is_free:
            inferred_slug = self._infer_recipe_slug_from_ingredient(ingredient)
            if inferred_slug:
                self._assembly.target_recipe_slug = inferred_slug

        self._assembly.ingredients.append(ingredient)
        stockpile_slot.remove()
        return True

    def add_condiment(self, condiment: str) -> bool:
        """添加调料到组装站（校验目标配方）"""
        if self._assembly.target_recipe_slug:
            recipe = self._recipes.get(self._assembly.target_recipe_slug)
            if recipe is not None:
                recipe_condiments = getattr(recipe, "condiments", [])
                # Recipe model uses list[str]; simulator adapter uses dict[str, int]
                if isinstance(recipe_condiments, dict):
                    max_count = recipe_condiments.get(condiment, 0)
                    valid = max_count > 0
                else:
                    max_count = recipe_condiments.count(condiment)
                    valid = condiment in recipe_condiments

                if not valid:
                    logger.warning(
                        f"[t={self.time:.1f}s] Condiment {condiment} not in recipe {self._assembly.target_recipe_slug}"
                    )
                    return False
                current = self._assembly.condiments.get(condiment, 0)
                if current >= max_count:
                    logger.warning(
                        f"[t={self.time:.1f}s] Condiment {condiment} already at max ({max_count}) for recipe {self._assembly.target_recipe_slug}"
                    )
                    return False

        current = self._assembly.condiments.get(condiment, 0)
        self._assembly.condiments[condiment] = current + 1
        return True

    def serve_order(self, slot_idx: int) -> bool:
        """送餐"""
        if slot_idx < 0 or slot_idx >= len(self._orders):
            return False

        order = self._orders[slot_idx]
        if order is None:
            return False

        order.done = True
        self._assembly.reset()
        self.set_animation_window(1.5)

        # 送餐后移除该订单
        self._orders[slot_idx] = None
        # 左移槽位
        self._shift_orders_left()

        logger.info(
            f"[t={self.time:.1f}s] Served order {order.order_id} ({order.recipe_slug}) slot {slot_idx} {'RUSH' if order.is_rush else 'normal'}"
        )
        return True

    def clear_cooker(self, cooker: str) -> bool:
        """清理灶台"""
        if cooker not in self._cookers:
            return False
        self._cookers[cooker].reset()
        return True

    def clear_assembly(self) -> bool:
        """清空组装站"""
        if not self._assembly.ingredients:
            return False
        self._assembly.reset()
        return True

    # ========================================================================
    # 扩展方法（GameEnvironment 特有）
    # ========================================================================

    def start_game(self) -> None:
        """开始游戏计时"""
        self._game_start_time = time.time()

    def is_game_over(self) -> bool:
        """游戏是否结束"""
        if self._game_start_time is None:
            return False
        return self.time >= self._game_duration

    def set_animation_window(self, duration: float = 1.5) -> None:
        """设置动画窗口"""
        self._animation_until = time.time() + duration

    def add_to_assembly(
        self,
        ingredient: str,
        cooker: str,
        order_id: Optional[int] = None,
        recipe_slug: Optional[str] = None,
    ) -> bool:
        """添加食材到组装站（带配方关联，校验食材合法性）"""
        if self._assembly.is_free:
            self._assembly.owner_order_id = order_id
            if recipe_slug:
                self._assembly.target_recipe_slug = recipe_slug
            elif order_id:
                order = self.get_order_by_id(order_id)
                if order:
                    self._assembly.target_recipe_slug = order.recipe_slug
                else:
                    self._assembly.target_recipe_slug = (
                        self._infer_recipe_slug_from_ingredient(ingredient)
                    )
            else:
                self._assembly.target_recipe_slug = (
                    self._infer_recipe_slug_from_ingredient(ingredient)
                )

        # 如果组装站有食材但没有目标配方，尝试推断
        if not self._assembly.target_recipe_slug and self._assembly.ingredients:
            all_ings = [t[0] for t in self._assembly.ingredients] + [ingredient]
            inferred = self._infer_recipe_slug_from_ingredients(all_ings)
            if inferred:
                self._assembly.target_recipe_slug = inferred

        # 校验食材是否属于目标配方
        raw_ings = []
        if self._assembly.target_recipe_slug:
            recipe = self._recipes.get(self._assembly.target_recipe_slug)
            if recipe is not None:
                raw_ings = getattr(recipe, "raw_ingredients", [])
                if ingredient not in raw_ings:
                    logger.warning(
                        f"[t={self.time:.1f}s] Ingredient {ingredient} not in recipe {self._assembly.target_recipe_slug}"
                    )
                    return False

        # 检查是否重复添加（按 ingredient 名称统计，不区分 cooker）
        already_added = sum(1 for t in self._assembly.ingredients if t[0] == ingredient)
        needed = raw_ings.count(ingredient) if raw_ings else 1
        if already_added >= needed:
            logger.warning(
                f"[t={self.time:.1f}s] Ingredient {ingredient} already at max ({needed}) for recipe {self._assembly.target_recipe_slug}"
            )
            return False

        self._assembly.ingredients.append((ingredient, cooker))
        return True

    def get_condiment_count(self, condiment: str) -> int:
        """获取已添加的调料数量"""
        return self._assembly.condiments.get(condiment, 0)

    def _shift_orders_left(self) -> None:
        """压缩订单槽位，将 None 移到末尾"""
        non_null = [o for o in self._orders if o is not None]
        self._orders = non_null + [None] * (4 - len(non_null))
        self._log_orders_state("_shift")

    def _log_orders_state(self, reason: str = "") -> None:
        """输出完整的订单状态列表"""
        slots = []
        for i, order in enumerate(self._orders):
            if order is None:
                slots.append(f"slot{i}=None")
            else:
                rush_mark = "R" if order.is_rush else ""
                slots.append(f"slot{i}={order.recipe_slug}({rush_mark})")
        logger.info(
            f"[t={self.time:.1f}s] Orders state [{reason}]: [{', '.join(slots)}]"
        )

    # ========================================================================
    # 订单操作
    # ========================================================================

    def add_order(self, recipe_slug: str, is_rush: bool) -> int | None:
        """添加新订单到最左边的空槽位"""
        # 找到最左边的空槽位
        target_slot = None
        for i, order in enumerate(self._orders):
            if order is None:
                target_slot = i
                break

        if target_slot is None:
            return None

        order_id = self._next_order_id
        self._next_order_id += 1

        now = time.time()
        timeout = 40.0 if is_rush else 70.0

        self._orders[target_slot] = OrderInfo(
            order_id=order_id,
            recipe_slug=recipe_slug,
            is_rush=is_rush,
            created_at=now,
            timeout_at=now + timeout,
        )

        logger.info(
            f"[t={self.time:.1f}s] New order {order_id}: {recipe_slug} ({'RUSH' if is_rush else 'normal'}) slot {target_slot}"
        )
        self._log_orders_state("add")
        return order_id

    def check_and_remove_timed_out_orders(self) -> list[int]:
        """检查并移除超时订单，返回超时订单ID列表"""
        timed_out = []
        now = time.time()
        for i, order in enumerate(self._orders):
            if order is not None and not order.done and now >= order.timeout_at:
                timed_out.append(order.order_id)
                logger.warning(
                    f"[t={self.time:.1f}s] Order {order.order_id} ({order.recipe_slug}) timed out in slot {i}"
                )
                self._orders[i] = None

        if timed_out:
            self._shift_orders_left()
        else:
            self._log_orders_state("timeout_check")

        return timed_out

    def get_order_by_id(self, order_id: int) -> Optional[OrderInfo]:
        """根据ID获取订单"""
        for order in self._orders:
            if order and order.order_id == order_id:
                return order
        return None

    def get_order_slot(self, order_id: int) -> Optional[int]:
        """获取订单所在的槽位索引"""
        for i, order in enumerate(self._orders):
            if order and order.order_id == order_id:
                return i
        return None

    # ========================================================================
    # 状态查询
    # ========================================================================

    def get_free_cookers(self) -> list[str]:
        """获取空闲灶台列表"""
        return [name for name, cooker in self._cookers.items() if not cooker.busy]

    def get_done_cookers(self) -> list[str]:
        """获取烹饪完成的灶台列表"""
        return [
            name
            for name, cooker in self._cookers.items()
            if cooker.busy and cooker.done_at and self.time >= cooker.done_at
        ]

    def get_stockpile_count(self, ingredient: str) -> int:
        """获取指定食材的库存数量"""
        for slot in self._stockpile.values():
            if slot.ingredient_name == ingredient:
                return slot.count
        return 0

    def find_stockpile_slot(self, ingredient: str) -> Optional[str]:
        """找到存储指定食材的库存槽位"""
        for slot_name, slot in self._stockpile.items():
            if slot.ingredient_name == ingredient and slot.count > 0:
                return slot_name
        return None

    def find_empty_stockpile_slot(self) -> Optional[str]:
        """找到空的库存槽位"""
        for slot_name, slot in self._stockpile.items():
            if slot.ingredient_name is None or slot.count == 0:
                return slot_name
        return None

    def _infer_recipe_slug_from_ingredient(self, ingredient: str) -> Optional[str]:
        """根据单个食材和活跃订单推断目标配方"""
        for order in self._orders:
            if order and not order.done:
                recipe = self._recipes.get(order.recipe_slug)
                if recipe:
                    raw_ings = getattr(recipe, "raw_ingredients", [])
                    if ingredient in raw_ings:
                        return order.recipe_slug
        return None

    def _infer_recipe_slug_from_ingredients(
        self, ingredients: list[str]
    ) -> Optional[str]:
        """根据多个食材和活跃订单推断目标配方"""
        for order in self._orders:
            if order and not order.done:
                recipe = self._recipes.get(order.recipe_slug)
                if recipe:
                    raw_ings = set(getattr(recipe, "raw_ingredients", []))
                    if all(ing in raw_ings for ing in ingredients):
                        return order.recipe_slug
        return None
