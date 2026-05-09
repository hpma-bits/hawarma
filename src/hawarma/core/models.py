"""
core/models: 核心数据模型
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

    def is_done(self, current_time: float) -> bool:
        """检查烹饪是否已完成"""
        return self.done_at is not None and current_time >= self.done_at

    def is_expired(self, current_time: float) -> bool:
        """检查食材是否已过期"""
        return self.expired_at is not None and current_time > self.expired_at


@dataclass
class AssemblyState:
    """组装站状态"""

    ingredients_cookers: list[tuple[str, str]] = field(default_factory=list)
    target_recipe_slug: str | None = None
    owner_order_id: int | None = None
    condiments: dict[str, int] = field(default_factory=dict)

    @property
    def is_free(self) -> bool:
        """组装站是否空闲"""
        return len(self.ingredients_cookers) == 0 and self.target_recipe_slug is None

    def reset(self) -> None:
        """重置组装站状态"""
        self.ingredients_cookers.clear()
        self.target_recipe_slug = None
        self.owner_order_id = None
        self.condiments.clear()


@dataclass
class StockpileSlot:
    """库存槽位"""

    ingredient_name: str | None = None
    cooker_type: str | None = None
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


@dataclass
class OrderInfo:
    """
    订单信息

    统一的订单数据结构，用于真实环境和模拟器
    """

    order_id: int
    recipe_slug: str
    is_rush: bool
    created_at: float
    timeout_at: float
    done: bool = False


# ============================================================================
# Env 抽象基类
# ============================================================================


