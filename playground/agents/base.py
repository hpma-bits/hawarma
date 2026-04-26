"""
Agent（交互壳）基类

持有 Strategy，接收 UnifiedState，输出 Action。
负责 Safety Layer：停滞检测、错误恢复、内部记忆维护。

Agent 是 Strategy 和 Env 之间的唯一桥梁。

输入: UnifiedState (from Env)
输出: Action (to Env)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..env.unified_state import UnifiedState
    from ..strategies.base import Strategy
    from hawarma.agent.agent import Action


class Agent:
    """
    Agent 交互壳。

    持有 Strategy，接收 UnifiedState，输出 Action。
    默认实现直接透传 Strategy 的输出，可子类化添加额外逻辑。
    """

    def __init__(self, strategy: Strategy):
        self.strategy = strategy

    def act(self, state: UnifiedState) -> Action | None:
        """
        接收状态，输出动作。

        默认实现：直接透传 strategy.decide(state)。
        子类可覆盖以添加额外逻辑（如动作过滤、记忆更新等）。

        Args:
            state: 当前环境的统一观测状态

        Returns:
            Action: 要执行的动作
            None: 当前无动作可做（等待）
        """
        return self.strategy.decide(state)

    def observe(
        self,
        state: UnifiedState,
        reward: float,
        terminated: bool,
        info: dict,
    ) -> None:
        """
        可选：观察执行结果。
        用于未来 RL 训练、在线学习。
        当前 rule-based strategy 不需要实现。

        Args:
            state: 执行动作后的新状态
            reward: 获得的奖励
            terminated: 是否自然结束
            info: 额外信息
        """
        pass

    def reset(self) -> None:
        """重置内部记忆（新一局游戏开始时调用）"""
        pass

    def on_game_start(self, recipes: dict[str, object]) -> None:
        """转发给 Strategy"""
        self.strategy.on_game_start(recipes)
