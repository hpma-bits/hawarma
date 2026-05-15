"""
SimEnv: RL 风格的游戏环境实现

基于 GameSimulator 重构，实现标准 RL 接口：
- reset() -> (obs, info)
- step(action) -> StepResult
- get_unified_state() -> UnifiedState

输入: Action (from Agent)
输出: UnifiedState, reward, done, info

延迟模拟（DDD 领域建模）：
- action_delay: 每次操作消耗的游戏时间（对应真实 swipe 物理耗时，默认 300ms）
- detection_delay: 新订单被扫描感知的滞后时间（对应真实模板匹配耗时，默认 400ms）

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hawarma.core.actions import (
    Action,
    CookAction,
    MoveToAssemblyAction,
    MoveToStockpileAction,
    PullFromStockpileAction,
    AddCondimentAction,
    ServeOrderAction,
    ClearCookerAction,
    ClearAssemblyAction,
)
from hawarma.core.models import Order
from playground.env_simulator import GameSimulator
from playground.env_simulator_types import Event, EventType, Recipe as SimRecipe

from .game_env import GameEnv
from .recipe_adapter import RecipeAdapter
from .reward import RewardFunction, GameDataReward, StepResult
from hawarma.core.state import UnifiedState


class SimEnv(GameEnv):
    """
    RL 风格的游戏环境实现。

    包装 GameSimulator，提供标准 RL 接口。

    延迟模拟（gastronome 模式）：
    - action_delay: 每次操作消耗的游戏时间（模拟 swipe 耗时，默认 300ms）
    - detection_delay: 新订单被扫描感知的滞后时间（模拟模板匹配耗时，默认 400ms）
    """

    TICK_INTERVAL = 0.1  # 每次 step 推进的时间（秒）
    DEFAULT_ACTION_DELAY = 0.3  # 默认操作延迟（秒）
    DEFAULT_DETECTION_DELAY = 0.4  # 默认检测延迟（秒）
    RECIPES_FILE = "data/recipes.json"

    def __init__(
        self,
        reward_fn: RewardFunction | None = None,
        recipes_file: str = RECIPES_FILE,
        tick_interval: float = TICK_INTERVAL,
        action_delay: float = DEFAULT_ACTION_DELAY,
        detection_delay: float = DEFAULT_DETECTION_DELAY,
    ):
        super().__init__(reward_fn=reward_fn or GameDataReward())
        self._recipes_file = recipes_file
        self._tick_interval = tick_interval
        self._action_delay = action_delay
        self._detection_delay = detection_delay
        self._sim: GameSimulator | None = None
        self._recipe_adapters: dict[str, RecipeAdapter] = {}

        # 统计
        self._orders_served = 0
        self._total_score = 0
        self._orders_timeout = 0
        self._actions_taken = 0

    # ------------------------------------------------------------------
    # RL 接口
    # ------------------------------------------------------------------

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
        """
        import random

        # 设置随机种子（在创建 simulator 之前，确保 __init__ 中的随机调用也是确定性的）
        if seed is not None:
            random.seed(seed)

        # 创建新的 simulator
        self._sim = GameSimulator(game_duration=game_duration)
        self._sim.load_recipes(self._recipes_file)

        # 选择配方
        if recipe_slugs is None:
            recipe_slugs = self._sim.select_recipes(count=4, random_seed=seed)

        # 配置游戏
        self._sim.setup_from_recipes(recipe_slugs)

        # 预创建 recipe adapters
        self._recipe_adapters = {}
        for slug in recipe_slugs:
            recipe = self._sim._recipes.get(slug)
            if recipe:
                self._recipe_adapters[slug] = RecipeAdapter(recipe)

        # 初始 tick（推进 0 秒，生成初始事件如第一个订单）
        # 实际上 setup_from_recipes 后需要至少一次 tick 才能看到第一个订单
        # 但为了保持 reset() 返回的是 t=0 的初始状态，我们不 tick

        obs = self.get_unified_state()
        info = {
            "recipes": self._recipe_adapters,
            "recipe_slugs": recipe_slugs,
            "seed": seed,
            "game_duration": self._sim._game_duration,
        }
        return obs, info

    def step(self, action: Action | None) -> StepResult:
        """
        执行一个动作，推进环境一个 tick。

        Args:
            action: 要执行的动作，None 表示等待

        Returns:
            StepResult: (observation, reward, terminated, truncated, info)
        """
        if self._sim is None:
            raise RuntimeError("Environment not initialized. Call reset() first.")

        prev_state = self.get_unified_state()

        # 1. 执行动作（如果提供了）
        action_events: list[Event] = []
        action_success = True
        error_message: str | None = None

        if action is not None:
            # 模拟操作延迟：swipe 物理执行消耗游戏时间
            self._sim.tick(self._action_delay)
            result = self._execute_action(action)
            action_events = list(result.events)
            action_success = result.success
            error_message = result.error_message

        # 2. 推进时间
        tick_events = self._sim.tick(self._tick_interval)

        # 3. 合并事件
        all_events = action_events + tick_events

        # 4. 构造新状态
        next_state = self.get_unified_state()

        # 5. 计算奖励
        reward = self.reward_fn.compute(prev_state, action, next_state, all_events)

        # 6. 判断结束
        terminated = self._sim.is_game_over()
        truncated = False  # 当前不实现步数限制截断

        # 7. 构造 info
        info = {
            "events": all_events,
            "action_success": action_success,
            "error_message": error_message,
            "sim_time": self._sim.time,
        }

        return StepResult(
            observation=next_state,
            reward=reward,
            terminated=terminated,
            truncated=truncated,
            info=info,
        )

    def get_unified_state(self) -> UnifiedState:
        """从 simulator 内部状态构造 UnifiedState"""
        if self._sim is None:
            raise RuntimeError("Environment not initialized. Call reset() first.")

        sim_state = self._sim._state

        orders = self._convert_orders(sim_state.orders)
        # 检测延迟：新订单在 detection_delay 内对 agent 不可见
        if self._detection_delay > 0:
            orders = self._apply_detection_delay(orders, sim_state.time)

        return UnifiedState(
            time=sim_state.time,
            orders=orders,
            cookers=sim_state.cookers,
            assembly=sim_state.assembly,
            stockpile=sim_state.stockpile,
            recipes=dict(self._recipe_adapters),
            game_duration=self._sim._game_duration,
            is_in_animation_window=self._sim.is_in_animation_window(),
            total_visibility=sim_state.total_visibility,
        )

    def is_game_over(self) -> bool:
        """游戏是否结束"""
        if self._sim is None:
            return True
        return self._sim.is_game_over()

    # ====================================================================
    # 统计接口
    # ====================================================================

    def get_stats(self) -> dict:
        return {
            "time": self.get_unified_state().time if self._sim else 0.0,
            "orders_served": self._orders_served,
            "total_score": self._total_score,
            "orders_timeout": self._orders_timeout,
            "actions_taken": self._actions_taken,
        }

    def on_order_served(self, score: int = 1) -> None:
        self._orders_served += 1
        self._total_score += score

    def on_order_timeout(self, order_id: int) -> None:
        self._orders_timeout += 1

    def on_action_taken(self) -> None:
        self._actions_taken += 1

    # ------------------------------------------------------------------
    # 动作执行
    # ------------------------------------------------------------------

    def _execute_action(self, action: Action):
        """将 Action 映射到 simulator 方法"""
        sim = self._sim
        assert sim is not None

        if isinstance(action, CookAction):
            return sim.start_cooking(action.ingredient, action.cooker)

        if isinstance(action, MoveToAssemblyAction):
            return sim.move_to_assembly(action.cooker)

        if isinstance(action, MoveToStockpileAction):
            return sim.move_to_stockpile(action.cooker, action.slot)

        if isinstance(action, PullFromStockpileAction):
            return sim.pull_from_stockpile(action.slot)

        if isinstance(action, AddCondimentAction):
            return sim.add_condiment(action.condiment)

        if isinstance(action, ServeOrderAction):
            return sim.serve_order(action.slot_idx)

        if isinstance(action, ClearCookerAction):
            return sim.clear_cooker(action.cooker)

        if isinstance(action, ClearAssemblyAction):
            return sim.clear_assembly()

        from playground.env_simulator import ActionResult
        return ActionResult.failure_result(f"Unknown action type: {type(action).__name__}")

    # ------------------------------------------------------------------
    # 状态转换
    # ------------------------------------------------------------------

    def _apply_detection_delay(
        self, orders: tuple[OrderInfo | None, ...], current_time: float
    ) -> tuple[OrderInfo | None, ...]:
        """过滤 detection_delay 内出现的新订单（模拟扫描滞后）"""
        result: list[OrderInfo | None] = []
        for order in orders:
            if order is None:
                result.append(None)
            elif current_time < order.created_at + self._detection_delay:
                result.append(None)
            else:
                result.append(order)
        return tuple(result)

    def _convert_orders(
        self, orders: list[Order | None]
    ) -> tuple[Order | None, ...]:
        """将 simulator 订单列表转为 tuple（类型已统一，无需转换）"""
        return tuple(orders)
