"""
Strategy（策略 / 决策脑）抽象基类

纯决策单元：接收 UnifiedState，返回 Action。
不直接接触环境，不处理动画等待，不处理错误恢复。

输入: UnifiedState
输出: Action | None
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .unified_state import UnifiedState
    from .agent import Action


class Strategy(ABC):
    """
    策略抽象基类。

    纯决策单元：接收 UnifiedState，返回 Action。
    不直接接触环境，不处理动画等待，不处理错误恢复。
    """

    @abstractmethod
    def decide(self, state: UnifiedState) -> Action | None:
        """
        给定当前状态，返回下一个动作。

        Args:
            state: 当前环境的统一观测状态

        Returns:
            Action: 要执行的动作
            None: 当前无动作可做（等待）
        """
        ...

    def on_game_start(self, recipes: dict[str, object]) -> None:
        """
        可选：游戏开始时调用。
        用于预计算、初始化缓存、分析食材频率等。

        Args:
            recipes: 当前局可用配方 slug -> RecipeAdapter 的映射
        """
        pass

    def on_episode_end(self, result: dict) -> None:
        """
        可选：一局游戏结束时调用。
        用于学习、统计、日志等。

        Args:
            result: 本局结果（total_reward, steps 等）
        """
        pass
