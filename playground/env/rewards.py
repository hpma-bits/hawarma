"""
Reward 计算接口

可插拔的奖励函数设计。
当前默认 SparseReward（仅 serve 成功时给予分数），
未来可扩展为 ShapedReward。

输入: (prev_state, action, next_state, events)
输出: float reward
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hawarma.env_simulator_types import Event
    from .unified_state import UnifiedState


@dataclass
class StepResult:
    """
    一步执行后的完整结果。
    对应 RL 中的 (observation, reward, terminated, truncated, info)。
    """

    observation: UnifiedState
    """执行动作后的新状态"""

    reward: float
    """该步获得的奖励"""

    terminated: bool
    """是否自然结束（游戏时间到、所有订单处理完毕）"""

    truncated: bool
    """是否被截断（如手动停止、超出步数限制）"""

    info: dict
    """额外信息（events, error_message, action_success 等）"""


class RewardFunction(ABC):
    """奖励函数抽象基类"""

    @abstractmethod
    def compute(
        self,
        prev_state: UnifiedState,
        action: object,  # Action type, avoid circular import
        next_state: UnifiedState,
        events: list[Event],
    ) -> float:
        """
        计算该步的奖励。

        Args:
            prev_state: 执行动作前的状态
            action: 执行的动作（可能为 None）
            next_state: 执行动作后的状态
            events: 该步触发的事件列表

        Returns:
            float: 奖励值
        """
        ...


class SparseReward(RewardFunction):
    """
    稀疏奖励：仅 serve 成功时给予分数，其他动作 reward = 0。
    与游戏真实得分一致。
    """

    def compute(
        self,
        prev_state: UnifiedState,
        action: object,
        next_state: UnifiedState,
        events: list[Event],
    ) -> float:
        from hawarma.env_simulator_types import EventType

        total = 0.0
        for event in events:
            if event.event_type == EventType.ORDER_SERVED:
                total += float(event.details.get("score", 0))
        return total


class RecipeRewardLookup:
    """
    加载 reward.csv 并提供精确的分数查表。

    CSV 格式：
        recipe,base points with cond,base points without cond,
               visibility with cond,visibility without cond
    """

    def __init__(self, csv_path: str = "playground/reward.csv"):
        self._data: dict[str, dict[str, int]] = {}
        self._load(csv_path)

    def _load(self, csv_path: str) -> None:
        import csv
        from pathlib import Path

        path = Path(csv_path)
        if not path.exists():
            # 尝试从项目根目录查找
            path = Path(__file__).parent.parent.parent / csv_path

        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row["recipe"].strip()
                self._data[name] = {
                    "base_with_cond": int(row["base points with cond"]),
                    "base_without_cond": int(row["base points without cond"]),
                    "visibility_with_cond": int(row["visibility with cond"]),
                    "visibility_without_cond": int(row["visibility without cond"]),
                }

    def get_score(
        self,
        recipe_name: str,
        has_condiments: bool,
        is_rush: bool,
        visibility_level: int | None = None,
    ) -> float:
        """
        计算 serve 的精确分数。

        Args:
            recipe_name: 菜品名称
            has_condiments: 是否添加了调料
            is_rush: 是否为 rush 订单
            visibility_level: visibility 等级 (0-6)，None 表示使用 CSV 中的默认值

        Returns:
            float: 该订单的得分
        """
        row = self._data.get(recipe_name)
        if not row:
            return 0.0

        if has_condiments:
            base = row["base_with_cond"]
            vis = row["visibility_with_cond"]
        else:
            base = row["base_without_cond"]
            vis = row["visibility_without_cond"]

        # TODO: visibility 实际应该根据 visibility_level 动态计算
        # 当前使用 CSV 中的默认值（近似），日后再完善动态加成机制
        total = base + vis

        # rush 订单：基础分数 × 2（简化处理）
        if is_rush:
            total *= 2

        return float(total)

    def __contains__(self, recipe_slug: str) -> bool:
        return recipe_slug in self._data


class RecipeTimeoutLookup:
    """
    加载 recipe_timeout.csv 并提供精确的超时查表。
    
    CSV 格式：
        recipe,normal_timeout,rush_timeout
    """

    def __init__(self, csv_path: str = "playground/recipe_timeout.csv"):
        self._data: dict[str, dict[str, float]] = {}
        self._load(csv_path)

    def _load(self, csv_path: str) -> None:
        import csv
        from pathlib import Path

        path = Path(csv_path)
        if not path.exists():
            path = Path(__file__).parent.parent.parent / csv_path

        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                slug = row["recipe"].strip()
                self._data[slug] = {
                    "normal_timeout": float(row["normal_timeout"]),
                    "rush_timeout": float(row["rush_timeout"]),
                }

    def get_timeout(self, recipe_slug: str, is_rush: bool) -> float | None:
        """
        获取订单超时时间。
        
        Args:
            recipe_slug: 配方的 slug
            is_rush: 是否为 rush 订单
            
        Returns:
            float: 超时时间（秒），如果找不到返回 None
        """
        row = self._data.get(recipe_slug)
        if not row:
            return None
        return row["rush_timeout"] if is_rush else row["normal_timeout"]

    def __contains__(self, recipe_slug: str) -> bool:
        return recipe_slug in self._data


class GameDataReward(RewardFunction):
    """
    基于游戏真实数据的精确奖励函数。

    从 reward.csv 查表计算 serve 得分，替代 simulator 的近似 score。
    """

    def __init__(self, csv_path: str = "playground/reward.csv"):
        self._lookup = RecipeRewardLookup(csv_path)

    def compute(
        self,
        prev_state: UnifiedState,
        action: object,
        next_state: UnifiedState,
        events: list[Event],
    ) -> float:
        from hawarma.env_simulator_types import EventType

        total = 0.0
        for event in events:
            if event.event_type == EventType.ORDER_SERVED:
                recipe_name = event.details.get("recipe", "")
                order_id = event.details.get("order_id")

                # 从 prev_state 获取订单是否 rush
                is_rush = False
                for order in prev_state.orders:
                    if order and order.order_id == order_id:
                        is_rush = order.is_rush
                        break

                # 从 prev_state.assembly 判断是否有调料（serve 前 assembly 还未清空）
                has_condiments = bool(prev_state.assembly.condiments)

                score = self._lookup.get_score(recipe_name, has_condiments, is_rush)
                total += score
        return total
