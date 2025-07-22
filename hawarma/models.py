# hawarma/models.py
import asyncio
import itertools
from dataclasses import dataclass, field
from enum import Enum, auto

@dataclass(frozen=True)
class Recipe:
    """Represents a cooking recipe."""
    slug: str
    name: str
    raw_ingredients: list[str]
    cookers: list[str]
    cook_durations: list[float]
    condiments: list[str]

    def __post_init__(self):
        if len(self.cook_durations) != len(self.cookers):
            raise ValueError("cook_durations length must match cookers length")

class OrderStage(Enum):
    PENDING = auto()
    HEATING = auto()
    OFF_HEAT = auto()
    SEASONING = auto()
    SERVING = auto()
    COMPLETED = auto()
    FAILED = auto()

@dataclass
class Order:
    """Represents a single cooking order."""
    recipe: Recipe
    is_rush: bool
    condiment_preference: dict[str, int]
    order_id: int = field(default_factory=itertools.count().__next__)
    done: bool = False
    current_stage: OrderStage = OrderStage.PENDING
    processing_task: asyncio.Task | None = None
    served_ts: float | None = None

    def __repr__(self) -> str:
        return f"Order(id={self.order_id}, recipe={self.recipe.name}, rush={self.is_rush})"
