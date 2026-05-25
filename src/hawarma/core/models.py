"""
core/models: 核心数据模型

统一的状态类型，供真实环境和模拟器共享。
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class CookerState:
    """灶台状态"""

    busy: bool = False
    item_name: str | None = None
    cooker_type: str | None = None
    started_at: float | None = None
    done_at: float | None = None
    expired_at: float | None = None

    def reset(self) -> None:
        """重置灶台状态"""
        self.busy = False
        self.item_name = None
        self.started_at = None
        self.done_at = None
        self.expired_at = None

    def clear(self) -> None:
        """清空灶台状态（reset 的别名）"""
        self.reset()

    def is_done(self, current_time: float) -> bool:
        """检查烹饪是否已完成"""
        return self.done_at is not None and current_time >= self.done_at

    def is_expired(self, current_time: float) -> bool:
        """检查食材是否已过期"""
        return self.expired_at is not None and current_time > self.expired_at


@dataclass
class AssemblyState:
    """组装站状态"""

    ingredients: list[tuple[str, str, float]] = field(default_factory=list)
    """(ingredient_name, cooker_type, added_at) — 真实环境中 added_at 可设为 0.0"""
    target_recipe_slug: str | None = None
    owner_order_id: int | None = None
    condiments: dict[str, int] = field(default_factory=dict)

    @property
    def ingredients_cookers(self) -> list[tuple[str, str]]:
        """兼容旧接口：返回 (ingredient, cooker) 二元组列表"""
        return [(ing[0], ing[1]) for ing in self.ingredients]

    @property
    def is_free(self) -> bool:
        """组装站是否空闲"""
        return len(self.ingredients) == 0 and self.target_recipe_slug is None

    @property
    def is_complete(self) -> bool:
        """是否所有食材已到齐"""
        return self.target_recipe_slug is not None and len(self.ingredients) > 0

    def can_add_ingredient(self, ing_name: str, cooker: str) -> bool:
        """检查食材是否与当前组装兼容"""
        if not self.ingredients:
            return True
        present_names = {ing[0] for ing in self.ingredients}
        return ing_name not in present_names

    def reset(self) -> None:
        """重置组装站状态"""
        self.ingredients.clear()
        self.target_recipe_slug = None
        self.owner_order_id = None
        self.condiments.clear()

    def clear(self) -> None:
        """清空组装站（reset 的别名）"""
        self.reset()


@dataclass
class StockpileSlot:
    """库存槽位"""

    item_name: str | None = None
    cooker_type: str | None = None
    count: int = 0

    def can_add(self, ingredient: str, cooker: str) -> bool:
        """检查是否可以添加食材"""
        if self.item_name is None:
            return True
        return self.item_name == ingredient and self.cooker_type == cooker

    def add(self, ingredient: str, cooker: str) -> bool:
        """添加食材"""
        if not self.can_add(ingredient, cooker):
            return False
        if self.item_name is None:
            self.item_name = ingredient
            self.cooker_type = cooker
        self.count += 1
        return True

    def remove(self) -> bool:
        """移除一个食材"""
        if self.count <= 0:
            return False
        self.count -= 1
        if self.count == 0:
            self.item_name = None
            self.cooker_type = None
        return True

    def remove_one(self) -> bool:
        """从槽位取出一个食材（remove 的别名）"""
        return self.remove()

    def clear(self) -> None:
        """清空槽位"""
        self.item_name = None
        self.cooker_type = None
        self.count = 0


@dataclass
class MixingBowlState:
    """搅拌盆状态（甜点专用）"""

    ingredients: list[str] = field(default_factory=list)
    condiments: dict[str, int] = field(default_factory=dict)
    target_recipe_slug: str | None = None
    is_stirred: bool = False

    @property
    def is_empty(self) -> bool:
        return len(self.ingredients) == 0

    @property
    def is_free(self) -> bool:
        """搅拌盆是否空闲"""
        return self.is_empty and self.target_recipe_slug is None

    @property
    def is_ready_to_cook(self) -> bool:
        """食材齐全 + 已搅拌"""
        return len(self.ingredients) >= 2 and self.is_stirred

    def reset(self) -> None:
        """重置搅拌盆状态"""
        self.ingredients.clear()
        self.condiments.clear()
        self.target_recipe_slug = None
        self.is_stirred = False

    def clear(self) -> None:
        """清空搅拌盆（reset 的别名）"""
        self.reset()


@dataclass
class Order:
    """
    订单信息

    统一的订单数据结构，用于真实环境和模拟器。
    """

    order_id: int
    recipe_slug: str
    is_rush: bool
    created_at: float
    timeout_at: float
    done: bool = False
    served_at: float | None = None
    spawned_at_visibility: float = 0.0
    recipe: object | None = None
    """完整 Recipe 对象（模拟器专用，真实环境为 None）"""
    condiments_applied: dict[str, int] = field(default_factory=dict)
    """已添加的调料（模拟器专用）"""

    @property
    def is_completed(self) -> bool:
        """订单是否已完成"""
        return self.done or self.served_at is not None

    def is_expired(self, current_time: float) -> bool:
        """订单是否已超时"""
        return current_time >= self.timeout_at and not self.is_completed

    def time_remaining(self, current_time: float) -> float:
        """订单剩余时间（秒）"""
        if self.is_completed:
            return 0.0
        return max(0.0, self.timeout_at - current_time)





# ========================================================================
# Env 抽象基类
# ========================================================================
