"""
Reward 计算接口（Playground 层）

可插拔的奖励函数设计。
数据查表类（RecipeRewardLookup, RecipeTimeoutLookup）已下沉到 hawarma.rewards。

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


class GameDataReward(RewardFunction):
    """
    基于游戏真实数据的精确奖励函数。

    从 reward.csv 查表计算 serve 得分，替代 simulator 的近似 score。
    """

    def __init__(self, csv_path: str = "playground/reward.csv"):
        from hawarma.rewards import RecipeRewardLookup
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

                # 从 event details 读取订单生成时锁定的 visibility
                spawned_vis = event.details.get("spawned_at_visibility", 0.0)
                score = self._lookup.get_score(
                    recipe_name, has_condiments, is_rush,
                    total_visibility=spawned_vis,
                )
                total += score
        return total
