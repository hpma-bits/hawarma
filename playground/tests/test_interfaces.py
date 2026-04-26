"""
Playground 接口验证测试

验证 Phase 0 定义的接口是否能正确组合：
- UnifiedState 构造
- Strategy.decide() -> Action
- Agent.act() -> Action
- GameEnv.reset() / step()

不需要启动真实 Simulator，使用 mock 数据。
"""

import pytest
from dataclasses import replace, FrozenInstanceError

from playground.env.unified_state import UnifiedState
from playground.env.rewards import SparseReward, StepResult
from playground.strategies.base import Strategy
from playground.agents.base import Agent
from playground.env.game_env import GameEnv

from hawarma.agent.agent import (
    Action,
    CookAction,
    ServeOrderAction,
)
from hawarma.bridge.base_environment import (
    CookerState,
    AssemblyState,
    StockpileSlot,
    OrderInfo,
)


# ============================================================================
# Mock 数据构造
# ============================================================================

def mock_unified_state(time: float = 0.0) -> UnifiedState:
    """构造一个 mock UnifiedState"""
    return UnifiedState(
        time=time,
        orders=(
            OrderInfo(order_id=1, recipe_slug="burger", is_rush=False, created_at=0.0, timeout_at=60.0),
            None,
            None,
            None,
        ),
        cookers={
            "grill": CookerState(),
            "oven": CookerState(),
        },
        assembly=AssemblyState(),
        stockpile={
            "stk0": StockpileSlot(),
            "stk1": StockpileSlot(),
        },
        recipes={"burger": object()},  # mock recipe adapter
        game_duration=90.0,
        is_in_animation_window=False,
    )


# ============================================================================
# Mock Strategy
# ============================================================================

class MockStrategy(Strategy):
    """测试用的 mock strategy：总是返回 CookAction"""

    def __init__(self, action: Action | None = None):
        self.action = action or CookAction(ingredient="beef", cooker="grill", duration=3.0)

    def decide(self, state: UnifiedState) -> Action | None:
        return self.action


class NoneStrategy(Strategy):
    """测试用的 mock strategy：总是返回 None"""

    def decide(self, state: UnifiedState) -> Action | None:
        return None


# ============================================================================
# Mock Agent
# ============================================================================

class MockAgent(Agent):
    """测试用的 mock agent：透传 strategy 的输出"""

    def __init__(self, strategy: Strategy):
        super().__init__(strategy)
        self.call_count = 0

    def act(self, state: UnifiedState) -> Action | None:
        self.call_count += 1
        return self.strategy.decide(state)


# ============================================================================
# Mock GameEnv
# ============================================================================

class MockGameEnv(GameEnv):
    """测试用的 mock env：不推进真实状态，只返回预定义结果"""

    def __init__(self):
        super().__init__(reward_fn=SparseReward())
        self._state = mock_unified_state(time=0.0)
        self._step_count = 0
        self._max_steps = 10

    def reset(
        self,
        seed: int | None = None,
        recipe_slugs: list[str] | None = None,
        game_duration: float | None = None,
    ) -> tuple[UnifiedState, dict]:
        self._state = mock_unified_state(time=0.0)
        self._step_count = 0
        info = {"recipes": ["burger"], "seed": seed}
        return self._state, info

    def step(self, action: Action | None) -> StepResult:
        self._step_count += 1
        self._state = replace(self._state, time=self._state.time + 1.0)

        terminated = self._step_count >= self._max_steps
        truncated = False
        reward = 0.0
        info = {"action": action, "step": self._step_count}

        return StepResult(
            observation=self._state,
            reward=reward,
            terminated=terminated,
            truncated=truncated,
            info=info,
        )

    def get_unified_state(self) -> UnifiedState:
        return self._state

    def is_game_over(self) -> bool:
        return self._step_count >= self._max_steps


# ============================================================================
# 测试用例
# ============================================================================

class TestUnifiedState:
    """测试 UnifiedState"""

    def test_creation(self):
        state = mock_unified_state()
        assert state.time == 0.0
        assert state.game_duration == 90.0
        assert state.remaining_time == 90.0
        assert len(state.orders) == 4
        assert "grill" in state.cookers

    def test_immutable(self):
        state = mock_unified_state()
        with pytest.raises(FrozenInstanceError):
            state.time = 10.0

    def test_remaining_time(self):
        state = mock_unified_state()
        state = replace(state, time=80.0)
        assert state.remaining_time == 10.0

        state = replace(state, time=95.0)
        assert state.remaining_time == 0.0


class TestStrategy:
    """测试 Strategy 协议"""

    def test_mock_strategy_returns_action(self):
        strategy = MockStrategy()
        state = mock_unified_state()
        action = strategy.decide(state)
        assert isinstance(action, CookAction)
        assert action.ingredient == "beef"

    def test_none_strategy_returns_none(self):
        strategy = NoneStrategy()
        state = mock_unified_state()
        action = strategy.decide(state)
        assert action is None

    def test_on_game_start(self):
        strategy = MockStrategy()
        recipes = {"burger": object()}
        strategy.on_game_start(recipes)  # 不应抛异常


class TestAgent:
    """测试 Agent 基类"""

    def test_agent_holds_strategy(self):
        strategy = MockStrategy()
        agent = MockAgent(strategy)
        assert agent.strategy is strategy

    def test_agent_act(self):
        strategy = MockStrategy()
        agent = MockAgent(strategy)
        state = mock_unified_state()
        action = agent.act(state)
        assert isinstance(action, CookAction)
        assert agent.call_count == 1

    def test_agent_reset(self):
        agent = MockAgent(MockStrategy())
        agent.reset()  # 不应抛异常


class TestGameEnv:
    """测试 GameEnv 接口"""

    def test_reset(self):
        env = MockGameEnv()
        obs, info = env.reset(seed=42)
        assert isinstance(obs, UnifiedState)
        assert obs.time == 0.0
        assert info["seed"] == 42

    def test_step(self):
        env = MockGameEnv()
        env.reset()
        action = CookAction(ingredient="beef", cooker="grill", duration=3.0)
        result = env.step(action)

        assert isinstance(result, StepResult)
        assert result.observation.time == 1.0
        assert result.reward == 0.0
        assert result.terminated is False
        assert result.info["action"] is action

    def test_step_none_action(self):
        env = MockGameEnv()
        env.reset()
        result = env.step(None)
        assert result.observation.time == 1.0
        assert result.info["action"] is None

    def test_episode_completion(self):
        env = MockGameEnv()
        env.reset()
        for _ in range(10):
            result = env.step(None)
        assert result.terminated is True
        assert env.is_game_over()


class TestRLEpisode:
    """测试完整的 RL 游戏循环"""

    def test_run_episode(self):
        env = MockGameEnv()
        agent = MockAgent(MockStrategy())

        obs, info = env.reset(seed=42)
        agent.on_game_start(info.get("recipes", {}))

        total_reward = 0.0
        steps = 0
        history = []

        while True:
            action = agent.act(obs)
            history.append((obs.time, action))

            result = env.step(action)
            agent.observe(result.observation, result.reward, result.terminated, result.info)

            total_reward += result.reward
            steps += 1
            obs = result.observation

            if result.terminated or result.truncated:
                break

        assert steps == 10
        assert len(history) == 10
        assert all(isinstance(a, CookAction) for _, a in history)

    def test_strategy_vs_none(self):
        """对比有动作和无动作的 agent"""
        env1 = MockGameEnv()
        env2 = MockGameEnv()

        agent1 = MockAgent(MockStrategy())
        agent2 = MockAgent(NoneStrategy())

        # 两个 agent 跑完一局
        for env, agent in [(env1, agent1), (env2, agent2)]:
            obs, _ = env.reset(seed=42)
            while True:
                action = agent.act(obs)
                result = env.step(action)
                obs = result.observation
                if result.terminated:
                    break

        # mock env 中 reward 始终为 0，但步骤数应该相同
        assert env1._step_count == env2._step_count


# ============================================================================
# Reward 测试
# ============================================================================

class TestSparseReward:
    """测试 SparseReward"""

    def test_no_events_zero_reward(self):
        reward_fn = SparseReward()
        state = mock_unified_state()
        reward = reward_fn.compute(state, None, state, [])
        assert reward == 0.0

    def test_serve_event_gives_score(self):
        from hawarma.env_simulator_types import Event, EventType
        reward_fn = SparseReward()
        state = mock_unified_state()
        events = [
            Event(event_type=EventType.ORDER_SERVED, timestamp=0.0, details={"score": 150})
        ]
        reward = reward_fn.compute(state, None, state, events)
        assert reward == 150.0
