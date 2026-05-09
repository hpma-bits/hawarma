"""
SimEnv: RL 椋庢牸鐨勬父鎴忕幆澧冨疄鐜?

鍩轰簬 GameSimulator 閲嶆瀯锛屽疄鐜版爣鍑?RL 鎺ュ彛锛?
- reset() -> (obs, info)
- step(action) -> StepResult
- get_unified_state() -> UnifiedState

杈撳叆: Action (from Agent)
杈撳嚭: UnifiedState, reward, done, info

鈿狅笍 涓€鏃︽枃浠跺唴瀹规湁鏇存柊锛屽姟蹇呭寮€澶存敞閲婅繘琛岀浉搴旂殑蹇呰鏇存柊锛屽悓鏃舵洿鏂版墍灞炵洰褰曠殑md
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
from hawarma.core.models import (
    AssemblyState as BaseAssemblyState,
    CookerState as BaseCookerState,
    OrderInfo,
    StockpileSlot as BaseStockpileSlot,
)
from playground.env_simulator import GameSimulator
from playground.env_simulator_types import Event, EventType

from .game_env import GameEnv
from .recipe_adapter import RecipeAdapter
from .reward import RewardFunction, GameDataReward, StepResult
from hawarma.core.state import UnifiedState


class SimEnv(GameEnv):
    """
    RL 椋庢牸鐨勬父鎴忕幆澧冨疄鐜般€?

    鍖呰 GameSimulator锛屾彁渚涙爣鍑?RL 鎺ュ彛銆?
    """

    TICK_INTERVAL = 0.1  # 姣忔 step 鎺ㄨ繘鐨勬椂闂达紙绉掞級
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

        # 缁熻
        self._orders_served = 0
        self._total_score = 0
        self._orders_timeout = 0
        self._actions_taken = 0

    # ------------------------------------------------------------------
    # RL 鎺ュ彛
    # ------------------------------------------------------------------

    def reset(
        self,
        seed: int | None = None,
        recipe_slugs: list[str] | None = None,
        game_duration: float | None = None,
    ) -> tuple[UnifiedState, dict]:
        """
        閲嶇疆鐜锛屽紑濮嬫柊涓€灞€娓告垙銆?

        Args:
            seed: 闅忔満绉嶅瓙
            recipe_slugs: 鎸囧畾浣跨敤鐨勯厤鏂瑰垪琛紝None 鍒欓殢鏈洪€夋嫨
            game_duration: 娓告垙鏃堕暱锛堢锛夛紝None 浣跨敤榛樿鍊?
        """
        import random

        # 璁剧疆闅忔満绉嶅瓙锛堝湪鍒涘缓 simulator 涔嬪墠锛岀‘淇?__init__ 涓殑闅忔満璋冪敤涔熸槸纭畾鎬х殑锛?
        if seed is not None:
            random.seed(seed)

        # 鍒涘缓鏂扮殑 simulator
        self._sim = GameSimulator(game_duration=game_duration)
        self._sim.load_recipes(self._recipes_file)

        # 閫夋嫨閰嶆柟
        if recipe_slugs is None:
            recipe_slugs = self._sim.select_recipes(count=4, random_seed=seed)

        # 閰嶇疆娓告垙
        self._sim.setup_from_recipes(recipe_slugs)

        # 棰勫垱寤?recipe adapters
        self._recipe_adapters = {}
        for slug in recipe_slugs:
            recipe = self._sim._recipes.get(slug)
            if recipe:
                self._recipe_adapters[slug] = RecipeAdapter(recipe)

        # 鍒濆 tick锛堟帹杩?0 绉掞紝鐢熸垚鍒濆浜嬩欢濡傜涓€涓鍗曪級
        # 瀹為檯涓?setup_from_recipes 鍚庨渶瑕佽嚦灏戜竴娆?tick 鎵嶈兘鐪嬪埌绗竴涓鍗?
        # 浣嗕负浜嗕繚鎸?reset() 杩斿洖鐨勬槸 t=0 鐨勫垵濮嬬姸鎬侊紝鎴戜滑涓?tick

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
        鎵ц涓€涓姩浣滐紝鎺ㄨ繘鐜涓€涓?tick銆?

        Args:
            action: 瑕佹墽琛岀殑鍔ㄤ綔锛孨one 琛ㄧず绛夊緟

        Returns:
            StepResult: (observation, reward, terminated, truncated, info)
        """
        if self._sim is None:
            raise RuntimeError("Environment not initialized. Call reset() first.")

        prev_state = self.get_unified_state()

        # 1. 鎵ц鍔ㄤ綔锛堝鏋滄彁渚涗簡锛?
        action_events: list[Event] = []
        action_success = True
        error_message: str | None = None

        if action is not None:
            result = self._execute_action(action)
            action_events = list(result.events)
            action_success = result.success
            error_message = result.error_message

        # 2. 鎺ㄨ繘鏃堕棿
        tick_events = self._sim.tick(self._tick_interval)

        # 3. 鍚堝苟浜嬩欢
        all_events = action_events + tick_events

        # 4. 鏋勯€犳柊鐘舵€?
        next_state = self.get_unified_state()

        # 5. 璁＄畻濂栧姳
        reward = self.reward_fn.compute(prev_state, action, next_state, all_events)

        # 6. 鍒ゆ柇缁撴潫
        terminated = self._sim.is_game_over()
        truncated = False  # 褰撳墠涓嶅疄鐜版鏁伴檺鍒舵埅鏂?

        # 7. 鏋勯€?info
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
        """浠?simulator 鍐呴儴鐘舵€佹瀯閫?UnifiedState"""
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
            total_visibility=sim_state.total_visibility,
        )

    def is_game_over(self) -> bool:
        """娓告垙鏄惁缁撴潫"""
        if self._sim is None:
            return True
        return self._sim.is_game_over()

    # ====================================================================
    # 缁熻鎺ュ彛
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
    # 鍔ㄤ綔鎵ц
    # ------------------------------------------------------------------

    def _execute_action(self, action: Action):
        """灏?Action 鏄犲皠鍒?simulator 鏂规硶"""
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
    # 鐘舵€佽浆鎹?
    # ------------------------------------------------------------------

    def _convert_orders(
        self, orders: list[Any]
    ) -> tuple[OrderInfo | None, ...]:
        """灏?simulator Order 杞崲涓?OrderInfo"""
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
        """灏?simulator CookerState 杞崲涓?base_environment CookerState"""
        result = {}
        for name, sim_cooker in cookers.items():
            cooker_type = sim_cooker.cooker_type if sim_cooker.cooker_type else name
            result[name] = BaseCookerState(
                busy=sim_cooker.busy,
                ingredient_name=sim_cooker.item_name,
                cooker_type=cooker_type,
                started_at=sim_cooker.started_at,
                done_at=sim_cooker.done_at,
                expired_at=sim_cooker.expired_at,
            )
        return result

    def _convert_assembly(
        self, sim_assembly: Any
    ) -> BaseAssemblyState:
        """灏?simulator AssemblyState 杞崲涓?base_environment AssemblyState"""
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
        """灏?simulator StockpileSlot 杞崲涓?base_environment StockpileSlot"""
        result = {}
        for name, sim_slot in stockpile.items():
            result[name] = BaseStockpileSlot(
                ingredient_name=sim_slot.ingredient_name,
                cooker_type=sim_slot.cooker_type,
                count=sim_slot.count,
            )
        return result

