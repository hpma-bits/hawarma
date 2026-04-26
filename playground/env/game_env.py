"""
GameEnv: RL 风格的游戏环境

职责：维护状态机、构造 Observation、执行 Action、计算 Reward、判断 Done。

接口对应标准 RL 环境：
- reset() -> (obs, info)
- step(action) -> (obs, reward, terminated, truncated, info)
- get_unified_state() -> UnifiedState

输入: Action (from Agent)
输出: UnifiedState, reward, done, info

⚠️ 当前为接口框架，Phase 1 将实现基于 GameSimulator 的完整版本。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .unified_state import UnifiedState
    from .rewards import RewardFunction, StepResult
    from hawarma.agent.agent import Action


class GameEnv(ABC):
    """
    RL 风格的游戏环境抽象基类。

    对应标准 Gym/Gymnasium 接口：
    - reset() -> (observation, info)
    - step(action) -> StepResult
    """

    def __init__(self, reward_fn: RewardFunction | None = None):
        self.reward_fn = reward_fn

    @abstractmethod
    def reset(
        self,
        seed: int | None = None,
        recipe_slugs: list[str] | None = None,
        game_duration: float | None = None,
    ) -> tuple[UnifiedState, dict]:
        """
        重置环境，开始新一局游戏。

        Args:
            seed: 随机种子
            recipe_slugs: 指定使用的配方列表，None 则随机选择
            game_duration: 游戏时长（秒），None 使用默认值

        Returns:
            observation: 初始 UnifiedState
            info: 额外信息（如选中的 recipe_slugs）
        """
        ...

    @abstractmethod
    def step(self, action: Action | None) -> StepResult:
        """
        执行一个动作，推进环境。

        Args:
            action: 要执行的动作，None 表示等待一个 tick

        Returns:
            StepResult: 包含 (observation, reward, terminated, truncated, info)
        """
        ...

    @abstractmethod
    def get_unified_state(self) -> UnifiedState:
        """获取当前观测状态（不推进时间）"""
        ...

    @abstractmethod
    def is_game_over(self) -> bool:
        """游戏是否结束"""
        ...
