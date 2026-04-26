"""
GameEnvImpl: RL 风格的游戏环境实现

基于 GameSimulator 重构，实现标准 RL 接口：
- reset() -> (obs, info)
- step(action) -> StepResult
- get_unified_state() -> UnifiedState

输入: Action (from Agent)
输出: UnifiedState, reward, done, info

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hawarma.agent.agent import (
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
from hawarma.bridge.base_environment import (
    AssemblyState as BaseAssemblyState,
    CookerState as BaseCookerState,
    OrderInfo,
    StockpileSlot as BaseStockpileSlot,
)
from hawarma.env_simulator import GameSimulator
from hawarma.env_simulator_types import Event, EventType

from .game_env import GameEnv
from .recipe_adapter import RecipeAdapter
from .rewards import RewardFunction, GameDataReward, StepResult
from .unified_state import UnifiedState


class GameEnvImpl(GameEnv):
    """
    RL 风格的游戏环境实现。

    包装 GameSimulator，提供标准 RL 接口。
    """

    TICK_INTERVAL = 0.1  # 每次 step 推进的时间（秒）
    RECIPES_FILE = "data/recipes.json"

    def __init__(
        self,
        reward_fn: RewardFunction | None = None,
        recipes_file: str = RECIPES_FILE,
        tick_interval: float = TICK_INTERVAL,
    ):
        super().__init__(reward_fn=reward_fn or GameDataReward())
        self._recipes_file = recipes_file
        self._tick_interval = tick_interval
        self._sim: GameSimulator | None = None
        self._recipe_adapters: dict[str, RecipeAdapter] = {}

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

        # 创建新的 simulator
        self._sim = GameSimulator(game_duration=game_duration)
        self._sim.load_recipes(self._recipes_file)

        # 设置随机种子
        if seed is not None:
            random.seed(seed)

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

        return UnifiedState(
            time=sim_state.time,
            orders=self._convert_orders(sim_state.orders),
            cookers=self._convert_cookers(sim_state.cookers),
            assembly=self._convert_assembly(sim_state.assembly),
            stockpile=self._convert_stockpile(sim_state.stockpile),
            recipes=dict(self._recipe_adapters),
            game_duration=self._sim._game_duration,
            is_in_animation_window=self._sim.is_in_animation_window(),
        )

    def is_game_over(self) -> bool:
        """游戏是否结束"""
        if self._sim is None:
            return True
        return self._sim.is_game_over()

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

        from hawarma.env_simulator import ActionResult
        return ActionResult.failure_result(f"Unknown action type: {type(action).__name__}")

    # ------------------------------------------------------------------
    # 状态转换
    # ------------------------------------------------------------------

    def _convert_orders(
        self, orders: list[Any]
    ) -> tuple[OrderInfo | None, ...]:
        """将 simulator Order 转换为 OrderInfo"""
        result = []
        for order in orders:
            if order is None:
                result.append(None)
            else:
                result.append(
                    OrderInfo(
                        order_id=order.order_id,
                        recipe_slug=order.recipe.slug,
                        is_rush=order.is_rush,
                        created_at=order.created_at,
                        timeout_at=order.timeout_at,
                        done=order.is_completed,
                    )
                )
        return tuple(result)

    def _convert_cookers(
        self, cookers: dict[str, Any]
    ) -> dict[str, BaseCookerState]:
        """将 simulator CookerState 转换为 base_environment CookerState"""
        result = {}
        for name, sim_cooker in cookers.items():
            cooker_type = sim_cooker.cooker_type if sim_cooker.cooker_type else name
            result[name] = BaseCookerState(
                busy=sim_cooker.busy,
                ingredient_name=sim_cooker.ingredient_name,
                cooker_type=cooker_type,
                started_at=sim_cooker.started_at,
                done_at=sim_cooker.done_at,
                expired_at=sim_cooker.expired_at,
            )
        return result

    def _convert_assembly(
        self, sim_assembly: Any
    ) -> BaseAssemblyState:
        """将 simulator AssemblyState 转换为 base_environment AssemblyState"""
        ingredients = [(ing[0], ing[1]) for ing in sim_assembly.ingredients]

        return BaseAssemblyState(
            ingredients_cookers=ingredients,
            target_recipe_slug=sim_assembly.target_recipe.slug
            if sim_assembly.target_recipe
            else None,
            owner_order_id=None,
            condiments=sim_assembly.condiments.copy(),
        )

    def _convert_stockpile(
        self, stockpile: dict[str, Any]
    ) -> dict[str, BaseStockpileSlot]:
        """将 simulator StockpileSlot 转换为 base_environment StockpileSlot"""
        result = {}
        for name, sim_slot in stockpile.items():
            result[name] = BaseStockpileSlot(
                ingredient_name=sim_slot.ingredient_name,
                cooker_type=sim_slot.cooker_type,
                count=sim_slot.count,
            )
        return result
