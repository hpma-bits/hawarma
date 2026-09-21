"""
游戏环境（真实游戏）

GameEnv 追踪真实游戏的状态，通过程序逻辑维护灶台、组装站、库存状态。
不继承 ABC — 真实环境和模拟环境本质不同（同步 vs 异步），通过 UnifiedState + Action 共享数据契约。
get_unified_state() 返回全量深快照（各模型 snapshot() 字段级拷贝），
观测与内部状态无共享可变对象（#16）。

时基（#17）：
- 注入 clock: Callable[[], float]（默认 time.monotonic），env.time / 订单时间戳 /
  动画窗口全部基于该时钟的**局内相对秒数**（clock() - game_start），与模拟器同基，
  不受 NTP 校时/系统睡眠影响
- Order.created_at/timeout_at 用 env.time（相对），真实耗时测量（墙钟）也走同一 clock

订单生命周期（Issue #18）：
- create_order 是订单创建唯一入口：timeout 查 RecipeTimeoutLookup（构造注入或
  懒加载，与 #22 reward_lookup 注入模式一致），查不到时 fallback 类常量
  DEFAULT_NORMAL_TIMEOUT/DEFAULT_RUSH_TIMEOUT（保持原 70/40 行为）
- apply_scan_result 把扫描结果的匹配/ghost 过滤/新建/删除收敛为 env 内的原子
  同步方法（无 await）：增量语义 + 已删除订单记忆窗口（防旧扫描帧复活）+
  连续 SCAN_MISS_DELETE_THRESHOLD 次未扫到才删除
- serve_order_by_id 按 order_id 结算送餐：serve 验证窗口内订单被 timeout 移位/
  删除时绝不结算到错单（找不到则 warning + 不计分）
- serve_order / serve_from_cooker / check_and_remove_timed_out_orders 移除订单时
  记入 _recently_removed 记忆（墙钟窗口 REMOVED_ORDER_MEMORY_WINDOW）

输入：UI操作结果、订单检测结果
输出：游戏状态供Agent决策

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

import time
from collections.abc import Callable

from loguru import logger

from hawarma.core.models import (
    AssemblyState,
    CookerState,
    MixingBowlState,
    Order,
    StockpileSlot,
)
from hawarma.core.reward import RecipeRewardLookup, RecipeTimeoutLookup
from hawarma.core.scoring import ScoringContext
from hawarma.recipe import Recipe, Station


class GameEnv:
    """
    真实游戏环境

    同时实现 GastronomeEnv 和 DessertEnv。
    根据当前 station 模式，只有对应接口的方法会被调用。
    """

    # 订单超时 fallback（RecipeTimeoutLookup 查不到该配方时保持原硬编码行为）
    DEFAULT_NORMAL_TIMEOUT: float = 70.0
    DEFAULT_RUSH_TIMEOUT: float = 40.0

    # 扫描增量同步参数（Issue #18）
    # 连续 N 次扫描未出现的订单才删除（防单次漏检误删）
    SCAN_MISS_DELETE_THRESHOLD: int = 2
    # 已删除订单（serve/timeout）的记忆窗口（墙钟秒）：窗口内同 (slug, rush)
    # 的扫描条目视为旧帧幽灵，不重建订单（防复活竞态）
    REMOVED_ORDER_MEMORY_WINDOW: float = 1.5
    # serve 图像延迟幽灵窗口（墙钟秒）：与 Runner _last_served 记录配套，
    # 互补于动画窗口（后者由 serve 时 set_animation_window 设置）
    SERVE_GHOST_WINDOW: float = 1.5

    def __init__(
        self,
        cooker_names: list[str],
        stockpile_slots: int = 3,
        game_duration: float = 90.0,
        recipes: dict[str, Recipe] | None = None,
        cooker_retention: float = 5.0,
        clock: Callable[[], float] | None = None,
        reward_lookup: RecipeRewardLookup | None = None,
        timeout_lookup: RecipeTimeoutLookup | None = None,
    ):
        self._cooker_retention = cooker_retention
        # 时钟注入（#17）：默认 monotonic，测试可注入假时钟确定性驱动
        # 订单超时/动画窗口；所有时间测量（env.time、订单时间戳、墙钟观测）
        # 统一经此 clock，不再直接调 time.time()
        self._clock = clock if clock is not None else time.monotonic
        self._cookers: dict[str, CookerState] = {
            name: CookerState(cooker_type=name) for name in cooker_names
        }

        self._assembly = AssemblyState()
        self._mixing_bowl = MixingBowlState()

        self._stockpile: dict[str, StockpileSlot] = {
            f"slot{i}": StockpileSlot() for i in range(stockpile_slots)
        }

        self._orders: list[Order | None] = [None] * 4

        self._game_start_time: float | None = None
        self._game_duration = game_duration
        self._animation_until: float = 0.0
        self._next_order_id = 1

        # 配方数据（用于校验组装站操作）
        self._recipes = recipes or {}

        # 度量上下文（统计查询、总分、终局结算唯一持有者；S1 抽离）
        self._scoring = ScoringContext()

        # 得分查表（可注入共享实例；未注入时首次 on_order_served 前懒加载，
        # 避免 GameEnv 在 unit test 中加载 CSV）
        self._reward_lookup: RecipeRewardLookup | None = reward_lookup

        # 订单超时查表（Issue #18）：可注入共享实例；未注入时首次 create_order 前
        # 懒加载（与 reward_lookup 注入模式一致，#22）
        self._timeout_lookup: RecipeTimeoutLookup | None = timeout_lookup

        # 扫描增量同步状态（Issue #18）：
        # - 连续未扫到计数（order_id -> 次数），扫到即清零，达到阈值删除
        self._scan_miss_count: dict[int, int] = {}
        # - 已删除订单记忆（order_id -> (slug, is_rush, 删除墙钟时刻)），
        #   供 apply_scan_result 校验「扫描条目是否为旧帧幽灵」
        self._recently_removed: dict[int, tuple[str, bool, float]] = {}

        logger.info(
            f"GameEnv initialized: {len(cooker_names)} cookers, {stockpile_slots} stockpile slots"
        )

    # ========================================================================
    # Env 接口实现
    # ========================================================================

    @property
    def time(self) -> float:
        """当前游戏时间（秒，局内相对：clock() - game_start 起点时刻）"""
        if self._game_start_time is None:
            return 0.0
        return self._clock() - self._game_start_time

    @property
    def orders(self) -> list[Order | None]:
        """当前订单列表"""
        return self._orders

    @property
    def cookers(self) -> dict[str, CookerState]:
        """灶台状态"""
        return self._cookers

    @property
    def assembly(self) -> AssemblyState:
        """组装站状态"""
        return self._assembly

    @property
    def stockpile(self) -> dict[str, StockpileSlot]:
        """库存状态"""
        return self._stockpile

    @property
    def mixing_bowl(self) -> MixingBowlState:
        """搅拌盆状态（甜点专用）"""
        return self._mixing_bowl

    def is_in_animation_window(self) -> bool:
        """是否在动画窗口期间"""
        return self._clock() < self._animation_until

    def animation_window_remaining(self) -> float:
        """动画窗口剩余时长（秒）。

        只观测不改行为：供扫描循环/日志判断「新单发现滞后里动画占几成」。
        不在动画窗口内返回 0.0。
        """
        return max(0.0, self._animation_until - self._clock())

    def start_cooking(self, ingredient: str, cooker: str, duration: float) -> bool:
        """开始烹饪"""
        if cooker not in self._cookers:
            logger.error(f"Unknown cooker: {cooker}")
            return False

        cooker_state = self._cookers[cooker]
        if cooker_state.busy:
            logger.warning(f"Cooker {cooker} is busy")
            return False

        cooker_state.busy = True
        cooker_state.item_name = ingredient
        cooker_state.started_at = self.time
        cooker_state.done_at = self.time + duration
        cooker_state.expired_at = self.time + duration + self._cooker_retention
        return True

    def move_to_assembly(self, cooker: str) -> bool:
        """将灶台完成的食材移动到组装站"""
        if cooker not in self._cookers:
            return False

        cooker_state = self._cookers[cooker]
        if not cooker_state.busy or cooker_state.done_at is None:
            return False

        ingredient = cooker_state.item_name
        cooker_type = cooker_state.cooker_type

        # 食材已过期，拒绝移动
        if cooker_state.is_expired(self.time):
            logger.warning(
                f"[t={self.time:.1f}s] Ingredient {ingredient} on {cooker} expired, cannot move to assembly"
            )
            return False

        # 如果组装站为空，根据(ingredient, cooker)推断目标配方
        if self._assembly.is_free:
            inferred_slug = self.get_recipe_for_ingredient_cooker(ingredient, cooker_type)
            if inferred_slug:
                self._assembly.target_recipe_slug = inferred_slug

        self._assembly.ingredients.append((ingredient, cooker_type, 0.0))
        cooker_state.reset()
        return True

    def move_to_stockpile(self, cooker: str, slot: str) -> bool:
        """将灶台食材移动到库存"""
        if cooker not in self._cookers:
            return False

        cooker_state = self._cookers[cooker]
        if not cooker_state.busy:
            return False

        if slot not in self._stockpile:
            return False

        stockpile_slot = self._stockpile[slot]
        if not stockpile_slot.add(
            cooker_state.item_name, cooker_state.cooker_type
        ):
            return False

        self._cookers[cooker].reset()
        return True

    def pull_from_stockpile(self, slot: str) -> bool:
        """从库存取用食材到组装站"""
        if slot not in self._stockpile:
            return False

        stockpile_slot = self._stockpile[slot]
        if stockpile_slot.count <= 0:
            return False

        ingredient = stockpile_slot.item_name
        cooker_type = stockpile_slot.cooker_type

        # 如果组装站为空，根据(ingredient, cooker)推断目标配方
        if self._assembly.is_free:
            inferred_slug = self.get_recipe_for_ingredient_cooker(ingredient, cooker_type)
            if inferred_slug:
                self._assembly.target_recipe_slug = inferred_slug

        self._assembly.ingredients.append((ingredient, cooker_type, 0.0))
        stockpile_slot.remove()
        return True

    def add_condiment(self, condiment: str) -> bool:
        """添加调料到组装站（校验目标配方）"""
        if self._assembly.target_recipe_slug:
            recipe = self._recipes.get(self._assembly.target_recipe_slug)
            if recipe is not None:
                condiments = recipe.condiments
                max_count = condiments.get(condiment, 0)
                valid = max_count > 0

                if not valid:
                    logger.warning(
                        f"[t={self.time:.1f}s] Condiment {condiment} not in recipe {self._assembly.target_recipe_slug}"
                    )
                    return False
                current = self._assembly.condiments.get(condiment, 0)
                if current >= max_count:
                    logger.warning(
                        f"[t={self.time:.1f}s] Condiment {condiment} already at max ({max_count}) for recipe {self._assembly.target_recipe_slug}"
                    )
                    return False

        current = self._assembly.condiments.get(condiment, 0)
        self._assembly.condiments[condiment] = current + 1
        return True

    def serve_order(self, slot_idx: int) -> bool:
        """送餐"""
        if slot_idx < 0 or slot_idx >= len(self._orders):
            return False

        order = self._orders[slot_idx]
        if order is None:
            return False

        self._settle_serve(order, slot_idx)
        return True

    def serve_order_by_id(self, order_id: int) -> Order | None:
        """按 order_id 结算送餐（Issue #18：serve 验证窗口后的安全结算入口）。

        送餐验证耗时 ≥0.25s（swipe + 渲染等待 + 截图验证），期间 timeout 循环
        可能已删除目标订单并使槽位左移——按 slot 结算会打错单。本方法按
        serve 前锁定的 order_id 查找结算：

        - 订单仍活跃：等价于 serve_order(其所在槽位)，返回被结算的订单
          （调用方随后按返回值计分）
        - 订单已不在（验证窗口内被 timeout 删除）：warning + 不计分、不改状态，
          返回 None——绝不结算到错单
        """
        for slot_idx, order in enumerate(self._orders):
            if order is not None and order.order_id == order_id:
                self._settle_serve(order, slot_idx)
                return order

        logger.warning(
            f"[t={self.time:.1f}s] serve_order_by_id({order_id}): order no longer "
            f"active (timed out during serve verification?), no settlement"
        )
        return None

    def _settle_serve(self, order: Order, slot_idx: int) -> None:
        """结算一次成功送餐：标记完成、清组装站、动画窗口、移位、记防复活内存"""
        order.done = True
        self._remember_removed_order(order)
        self._assembly.reset()
        self.set_animation_window(1.5)

        # 送餐后移除该订单
        self._orders[slot_idx] = None
        # 左移槽位
        self._shift_orders_left()

        logger.info(
            f"[t={self.time:.1f}s] Served order {order.order_id} ({order.recipe_slug}) slot {slot_idx} {'RUSH' if order.is_rush else 'normal'}"
        )

    def clear_cooker(self, cooker: str) -> bool:
        """清理灶台"""
        if cooker not in self._cookers:
            return False
        self._cookers[cooker].reset()
        return True

    def clear_assembly(self) -> bool:
        """清空组装站"""
        if not self._assembly.ingredients:
            return False
        self._assembly.reset()
        return True

    # ========================================================================
    # Dessert 方法
    # ========================================================================

    def add_to_mixing_bowl(self, ingredient: str, recipe_slug: str | None = None) -> bool:
        """食材 → 搅拌盆"""
        if len(self._mixing_bowl.ingredients) >= 2:
            logger.warning(f"[t={self.time:.1f}s] Mixing bowl full, cannot add {ingredient}")
            return False

        if self._mixing_bowl.is_empty:
            if recipe_slug:
                self._mixing_bowl.target_recipe_slug = recipe_slug
            else:
                inferred = self._infer_dessert_recipe(ingredient)
                if inferred:
                    self._mixing_bowl.target_recipe_slug = inferred

        if self._mixing_bowl.target_recipe_slug:
            recipe = self._recipes.get(self._mixing_bowl.target_recipe_slug)
            if recipe:
                raw_ings = recipe.raw_ingredients
                if ingredient not in raw_ings:
                    logger.warning(
                        f"[t={self.time:.1f}s] Ingredient {ingredient} not in dessert recipe {self._mixing_bowl.target_recipe_slug}"
                    )
                    return False

        if ingredient in self._mixing_bowl.ingredients:
            logger.warning(f"[t={self.time:.1f}s] Ingredient {ingredient} already in mixing bowl")
            return False

        self._mixing_bowl.ingredients.append(ingredient)
        logger.info(f"[t={self.time:.1f}s] Added {ingredient} to mixing bowl")
        return True

    def add_condiment_to_mixing_bowl(self, condiment: str) -> bool:
        """调料 → 搅拌盆"""
        if self._mixing_bowl.is_empty:
            logger.warning(f"[t={self.time:.1f}s] Mixing bowl is empty, cannot add condiment")
            return False

        if self._mixing_bowl.target_recipe_slug:
            recipe = self._recipes.get(self._mixing_bowl.target_recipe_slug)
            if recipe is not None:
                condiments = recipe.condiments
                max_count = condiments.get(condiment, 0)
                valid = max_count > 0

                if not valid:
                    logger.warning(
                        f"[t={self.time:.1f}s] Condiment {condiment} not in recipe {self._mixing_bowl.target_recipe_slug}"
                    )
                    return False
                current = self._mixing_bowl.condiments.get(condiment, 0)
                if current >= max_count:
                    logger.warning(
                        f"[t={self.time:.1f}s] Condiment {condiment} already at max ({max_count})"
                    )
                    return False

        self._mixing_bowl.condiments[condiment] = self._mixing_bowl.condiments.get(condiment, 0) + 1
        logger.info(f"[t={self.time:.1f}s] Added condiment {condiment} to mixing bowl")
        return True

    def stir_mixing_bowl(self) -> bool:
        """搅拌操作"""
        if self._mixing_bowl.is_empty:
            logger.warning(f"[t={self.time:.1f}s] Mixing bowl is empty, cannot stir")
            return False
        if self._mixing_bowl.is_stirred:
            logger.warning(f"[t={self.time:.1f}s] Mixing bowl already stirred")
            return False
        self._mixing_bowl.is_stirred = True
        logger.info(f"[t={self.time:.1f}s] Stirred mixing bowl")
        return True

    def move_mixing_bowl_to_cooker(self, cooker: str) -> bool:
        """搅拌盆 → 灶台"""
        if not self._mixing_bowl.is_stirred:
            logger.warning(f"[t={self.time:.1f}s] Mixing bowl not stirred")
            return False
        if cooker not in self._cookers:
            logger.error(f"Unknown cooker: {cooker}")
            return False
        cooker_state = self._cookers[cooker]
        if cooker_state.busy:
            logger.warning(f"Cooker {cooker} is busy")
            return False

        recipe = self._recipes.get(self._mixing_bowl.target_recipe_slug)
        if not recipe:
            logger.error(f"Recipe not found: {self._mixing_bowl.target_recipe_slug}")
            return False

        cookers_list = recipe.cookers
        durations = recipe.cook_durations
        if not cookers_list or not durations:
            logger.error(f"Recipe {self._mixing_bowl.target_recipe_slug} has no cookers/durations")
            return False
        if cookers_list[0] != cooker:
            logger.warning(f"Recipe requires {cookers_list[0]}, not {cooker}")
            return False

        duration = durations[0]
        cooker_state.busy = True
        cooker_state.item_name = self._mixing_bowl.target_recipe_slug
        cooker_state.cooker_type = cooker
        cooker_state.started_at = self.time
        cooker_state.done_at = self.time + duration
        cooker_state.expired_at = self.time + duration + self._cooker_retention

        self._mixing_bowl.reset()
        logger.info(f"[t={self.time:.1f}s] Moved mixing bowl to {cooker} ({duration}s)")
        return True

    def serve_from_cooker(self, cooker: str, slot_idx: int) -> bool:
        """灶台 → 取餐台"""
        if cooker not in self._cookers:
            return False
        cooker_state = self._cookers[cooker]
        if not cooker_state.busy or cooker_state.done_at is None:
            return False
        if self.time < cooker_state.done_at:
            logger.warning(f"[t={self.time:.1f}s] Cooker {cooker} not done yet")
            return False
        if cooker_state.is_expired(self.time):
            logger.warning(f"[t={self.time:.1f}s] Cooker {cooker} expired")
            return False
        if slot_idx < 0 or slot_idx >= len(self._orders):
            return False
        order = self._orders[slot_idx]
        if order is None:
            return False
        recipe_slug = cooker_state.item_name
        if order.recipe_slug != recipe_slug:
            logger.warning(
                f"[t={self.time:.1f}s] Order {order.order_id} expects {order.recipe_slug}, not {recipe_slug}"
            )
            return False

        order.done = True
        cooker_state.reset()
        self._remember_removed_order(order)
        self.set_animation_window(1.5)
        self._orders[slot_idx] = None
        self._shift_orders_left()
        logger.info(f"[t={self.time:.1f}s] Served dessert {recipe_slug} from {cooker} slot {slot_idx}")
        return True

    def clear_mixing_bowl(self) -> bool:
        """清空搅拌盆"""
        if self._mixing_bowl.is_empty:
            return False
        discarded = self._mixing_bowl.ingredients.copy()
        self._mixing_bowl.reset()
        logger.info(f"[t={self.time:.1f}s] Cleared mixing bowl (discarded: {discarded})")
        return True

    def _infer_dessert_recipe(self, ingredient: str) -> str | None:
        """根据单个食材推断甜点配方"""
        from hawarma.recipe import Station
        for order in self._orders:
            if order and not order.done:
                recipe = self._recipes.get(order.recipe_slug)
                if recipe:
                    station = recipe.station
                    if station == Station.DESSERT:
                        raw_ings = recipe.raw_ingredients
                        if ingredient in raw_ings:
                            return order.recipe_slug
        return None

    # ========================================================================
    # 统一状态接口
    # ========================================================================

    def get_unified_state(self) -> "UnifiedState":
        """构建 UnifiedState 快照（字段级深拷贝，#16）。

        所有可变子状态（orders/cookers/assembly/stockpile/mixing_bowl）
        经各自 snapshot() 拷贝，与 env 内部状态完全隔离，
        Strategy 篡改返回值不会污染环境。
        recipes 为静态配置数据，仅拷贝容器（Recipe 对象只读共享）。
        """
        from hawarma.core.state import UnifiedState

        orders = tuple(
            order.snapshot() if order is not None else None for order in self._orders
        )

        return UnifiedState(
            time=self.time,
            orders=orders,
            cookers={name: c.snapshot() for name, c in self._cookers.items()},
            assembly=self._assembly.snapshot(),
            stockpile={name: s.snapshot() for name, s in self._stockpile.items()},
            recipes=dict(self._recipes),
            game_duration=self._game_duration,
            is_in_animation_window=self.is_in_animation_window(),
            mixing_bowl=self._mixing_bowl.snapshot(),
        )

    def get_stats(self) -> dict:
        stats = self._scoring.get_stats()
        return {
            "time": self.time,
            **stats,
        }

    def finalize(self) -> float:
        """终局结算（幂等）：总分 = 订单得分和 + 总 visibility."""
        return self._scoring.finalize()

    def on_order_served(self, order: Order, has_condiments: bool) -> None:
        """
        记录订单完成事件，按游戏规则计算实际得分。

        与模拟器对齐（env_simulator.py:1170-1206）：
            1. 按 serve 瞬间的 recipe + has_condiments + 订单生成时锁定的
               spawned_at_visibility 计算该订单得分
            2. 把该订单的 visibility 加到局内总 visibility
               （影响后续订单的 spawned_at_visibility 与最终总分）

        调用方（runner）需在调用本方法前：
            - 从 env.orders[slot_idx] 拿到 order 引用
            - 在 env.serve_order / serve_from_cooker 清空 assembly 之前
              用 env.assembly.condiments 判断 has_condiments
        """
        if self._reward_lookup is None:
            self._reward_lookup = RecipeRewardLookup()

        score = self._reward_lookup.get_score(
            order.recipe_slug,
            has_condiments=has_condiments,
            is_rush=order.is_rush,
            total_visibility=order.spawned_at_visibility,
        )
        visibility = self._reward_lookup.get_visibility(
            order.recipe_slug, has_condiments
        )

        self._scoring.record_serve(score, visibility)

        logger.info(
            f"[t={self.time:.1f}s] Scored order {order.order_id} ({order.recipe_slug}, "
            f"{'RUSH' if order.is_rush else 'normal'}, cond={has_condiments}): "
            f"+{score:.0f} score, +{visibility} visibility "
            f"(spawned_at={order.spawned_at_visibility:.0f}, "
            f"total_vis={self._scoring.total_visibility:.0f})"
        )

    def on_order_timeout(self, order_id: int) -> None:
        self._scoring.record_timeout()

    def on_action_taken(self) -> None:
        """每次执行动作时调用，更新统计"""
        self._scoring.record_action()

    # ========================================================================
    # 扩展方法（GameEnv 特有）
    # ========================================================================

    def start_game(self) -> None:
        """开始游戏计时（记录 clock 起点，env.time 从 0 起算）"""
        self._game_start_time = self._clock()

    def is_game_over(self) -> bool:
        """游戏是否结束"""
        if self._game_start_time is None:
            return False
        return self.time >= self._game_duration

    def set_animation_window(self, duration: float = 1.5) -> None:
        """设置动画窗口"""
        self._animation_until = self._clock() + duration

    def add_to_assembly(
        self,
        ingredient: str,
        cooker: str,
        order_id: int | None = None,
        recipe_slug: str | None = None,
    ) -> bool:
        """添加食材到组装站（带配方关联，校验食材合法性）"""
        if self._assembly.is_free:
            self._assembly.owner_order_id = order_id
            if recipe_slug:
                self._assembly.target_recipe_slug = recipe_slug
            elif order_id:
                order = self.get_order_by_id(order_id)
                if order:
                    self._assembly.target_recipe_slug = order.recipe_slug
                else:
                    self._assembly.target_recipe_slug = (
                        self.get_recipe_for_ingredient_cooker(ingredient, cooker)
                    )
            else:
                self._assembly.target_recipe_slug = (
                    self.get_recipe_for_ingredient_cooker(ingredient, cooker)
                )

        # 如果组装站有食材但没有目标配方，尝试推断
        if not self._assembly.target_recipe_slug and self._assembly.ingredients:
            all_ings = [t[0] for t in self._assembly.ingredients] + [ingredient]
            inferred = self._infer_recipe_slug_from_ingredients(all_ings)
            if inferred:
                self._assembly.target_recipe_slug = inferred

        # 校验食材是否属于目标配方
        raw_ings = []
        if self._assembly.target_recipe_slug:
            recipe = self._recipes.get(self._assembly.target_recipe_slug)
            if recipe is not None:
                raw_ings = recipe.raw_ingredients
                if ingredient not in raw_ings:
                    logger.warning(
                        f"[t={self.time:.1f}s] Ingredient {ingredient} not in recipe {self._assembly.target_recipe_slug}"
                    )
                    return False

        # 检查是否重复添加（按 ingredient-cooker 组合统计）
        already_added = sum(
            1 for t in self._assembly.ingredients if t[0] == ingredient
        )
        needed = raw_ings.count(ingredient) if raw_ings else 1
        if already_added >= needed:
            logger.warning(
                f"[t={self.time:.1f}s] Ingredient {ingredient} already at max ({needed}) for recipe {self._assembly.target_recipe_slug}"
            )
            return False

        self._assembly.ingredients.append((ingredient, cooker, 0.0))
        return True

    def get_condiment_count(self, condiment: str) -> int:
        """获取已添加的调料数量"""
        return self._assembly.condiments.get(condiment, 0)

    def _shift_orders_left(self) -> None:
        """压缩订单槽位，将 None 移到末尾"""
        non_null = [o for o in self._orders if o is not None]
        self._orders = non_null + [None] * (4 - len(non_null))
        self._log_orders_state("_shift")

    def _log_orders_state(self, reason: str = "") -> None:
        """输出完整的订单状态列表"""
        slots = []
        for i, order in enumerate(self._orders):
            if order is None:
                slots.append(f"slot{i}=None")
            else:
                rush_mark = "R" if order.is_rush else ""
                slots.append(f"slot{i}={order.recipe_slug}({rush_mark})")
        logger.info(
            f"[t={self.time:.1f}s] Orders state [{reason}]: [{', '.join(slots)}]"
        )

    # ========================================================================
    # 订单操作（Issue #18：创建/同步/结算收敛为 env 的原子公共 API）
    # ========================================================================

    def create_order(self, recipe_slug: str, is_rush: bool) -> Order:
        """创建新订单（唯一入口）。

        - timeout 优先查 RecipeTimeoutLookup（构造注入或懒加载）；查不到该配方
          时 fallback 到 DEFAULT_NORMAL_TIMEOUT / DEFAULT_RUSH_TIMEOUT（保持原
          硬编码 70/40 行为）
        - 生成瞬间锁定 _scoring.total_visibility 到 spawned_at_visibility
          （倍率依赖该值，订单一旦生成不再变化）
        - _next_order_id 自增
        - 只构造订单对象，不落槽位：槽位由调用方（apply_scan_result /
          add_order 别名）决定

        Returns:
            新建的 Order
        """
        order_id = self._next_order_id
        self._next_order_id += 1

        # 局内相对秒数（#17）：与 env.time 同基，Order 时间戳不再是 epoch 墙钟
        now = self.time
        timeout = self._get_order_timeout(recipe_slug, is_rush)

        order = Order(
            order_id=order_id,
            recipe_slug=recipe_slug,
            is_rush=is_rush,
            created_at=now,
            timeout_at=now + timeout,
            spawned_at_visibility=self._scoring.total_visibility,
        )

        logger.info(
            f"[t={self.time:.1f}s] New order {order_id}: {recipe_slug} "
            f"({'RUSH' if is_rush else 'normal'}), timeout={timeout:.0f}s"
        )
        return order

    def _get_order_timeout(self, recipe_slug: str, is_rush: bool) -> float:
        """订单超时秒数：RecipeTimeoutLookup 查表 + fallback 类常量。"""
        if self._timeout_lookup is None:
            self._timeout_lookup = RecipeTimeoutLookup()
        timeout = self._timeout_lookup.get_timeout(recipe_slug, is_rush)
        if timeout is not None:
            return timeout
        return self.DEFAULT_RUSH_TIMEOUT if is_rush else self.DEFAULT_NORMAL_TIMEOUT

    def add_order(self, recipe_slug: str, is_rush: bool) -> int | None:
        """添加新订单到最左边的空槽位（create_order 的薄别名，保留旧调用兼容）。

        新代码请走 create_order / apply_scan_result；本方法仅为既有调用方
        （测试/脚本）保留「创建即落最左空槽」的旧语义。
        """
        # 找到最左边的空槽位
        target_slot = None
        for i, order in enumerate(self._orders):
            if order is None:
                target_slot = i
                break

        if target_slot is None:
            return None

        order = self.create_order(recipe_slug, is_rush)
        self._orders[target_slot] = order
        self._log_orders_state("add")
        return order.order_id

    def apply_scan_result(
        self,
        scanned: list[tuple[str, bool]],
        recently_served: dict[tuple[str, bool], float] | None = None,
        now_wall: float | None = None,
    ) -> dict[str, int]:
        """原子应用一次扫描结果（Issue #18）。

        同步方法（无 await）：单线程事件循环下与 serve/timeout 变更天然互斥，
        消除「await 扫描点之后用旧帧全量覆盖订单」的竞态。增量语义：

        1. 匹配：扫描条目按 (recipe_slug, is_rush) 匹配现有**活跃**订单
           （同位优先，再其他位——订单位移），匹配到的保留
           order_id/created_at/timeout_at 并放置到扫描位置
        2. serve 幽灵过滤：recently_served 内 SERVE_GHOST_WINDOW 秒刚 serve 过
           该类型且 env 中无活跃同名单 → 跳过（扫描图像延迟，与防复活互补）
        3. 防复活：无匹配但命中已删除订单记忆（REMOVED_ORDER_MEMORY_WINDOW 窗口
           内 serve/timeout 删除的同名单）→ 视为旧扫描帧幽灵，不重建订单
        4. 新建：其余未匹配条目经 create_order 创建
        5. 删除：现有订单连续 SCAN_MISS_DELETE_THRESHOLD 次扫描未出现才删除；
           未达阈值的存活单追加到尾部空位（保留给下一轮匹配）

        Args:
            scanned: 扫描到的订单类型，按 slot 从左到右排序（忽略扫描器 slot gap）
            recently_served: {(slug, is_rush): serve 墙钟时刻}，Runner 的
                _last_served 记录（None = 无 serve 幽灵过滤）
            now_wall: 墙钟读数（None = self._clock()），ghost/记忆窗口判定基准

        Returns:
            同步统计 dict：detected/reused/created/ghost_skipped/
            resurrection_blocked/kept_pending_removal/removed
        """
        now_wall = self._clock() if now_wall is None else now_wall
        self._prune_removed_order_memory(now_wall)

        new_orders: list[Order | None] = [None] * 4
        reused_ids: set[int] = set()
        stats = {
            "detected": len(scanned),
            "reused": 0,
            "created": 0,
            "ghost_skipped": 0,
            "resurrection_blocked": 0,
            "kept_pending_removal": 0,
            "removed": 0,
        }

        for i, (recipe_slug, is_rush) in enumerate(scanned):
            if i >= 4:
                break

            # serve 幽灵订单保护：刚 serve 过该类型且 env 中已无活跃同名单
            if recently_served is not None:
                last_served_at = recently_served.get((recipe_slug, is_rush), 0.0)
                if now_wall - last_served_at < self.SERVE_GHOST_WINDOW:
                    has_active = any(
                        o is not None
                        and not o.done
                        and o.recipe_slug == recipe_slug
                        and o.is_rush == is_rush
                        for o in self._orders
                    )
                    if not has_active:
                        stats["ghost_skipped"] += 1
                        continue

            # 匹配现有活跃订单（校验仍活跃：done 单不复用）
            matched = self._find_active_match(recipe_slug, is_rush, i, reused_ids)
            if matched is not None:
                new_orders[i] = matched
                reused_ids.add(matched.order_id)
                stats["reused"] += 1
                continue

            # 防复活：记忆窗口内同 (slug, rush) 的已删除订单 → 旧扫描帧幽灵
            if self._was_recently_removed(recipe_slug, is_rush, now_wall):
                stats["resurrection_blocked"] += 1
                logger.debug(
                    f"[t={self.time:.1f}s] Scan sync: suppressed resurrection of "
                    f"removed order ({recipe_slug}, {'RUSH' if is_rush else 'normal'})"
                )
                continue

            new_orders[i] = self.create_order(recipe_slug, is_rush)
            stats["created"] += 1

        # 未匹配的现有订单：连续 N 次未扫到才删除；未达阈值的追加到尾部保位
        survivors: list[Order] = []
        for order in self._orders:
            if order is None or order.order_id in reused_ids:
                continue
            misses = self._scan_miss_count.get(order.order_id, 0) + 1
            if misses >= self.SCAN_MISS_DELETE_THRESHOLD:
                del self._scan_miss_count[order.order_id]
                stats["removed"] += 1
                logger.info(
                    f"[t={self.time:.1f}s] Order {order.order_id} "
                    f"({order.recipe_slug}) removed after {misses} consecutive "
                    f"scan misses"
                )
            else:
                self._scan_miss_count[order.order_id] = misses
                survivors.append(order)

        # 本轮扫到的订单 miss 计数清零
        for order_id in reused_ids:
            self._scan_miss_count.pop(order_id, None)

        # 存活单追加到尾部空位（左对齐，与 _shift_orders_left 布局一致）；
        # 槽位放不下的存活单按删除处理（4 槽全被扫描条目占满的极端场景）
        for order in survivors:
            placed = False
            for i in range(4):
                if new_orders[i] is None:
                    new_orders[i] = order
                    placed = True
                    stats["kept_pending_removal"] += 1
                    break
            if not placed:
                self._scan_miss_count.pop(order.order_id, None)
                stats["removed"] += 1
                logger.warning(
                    f"[t={self.time:.1f}s] Order {order.order_id} "
                    f"({order.recipe_slug}) dropped: no free slot after scan sync"
                )

        self._orders = new_orders
        self._log_orders_state("scan_sync")
        return stats

    def _find_active_match(
        self,
        recipe_slug: str,
        is_rush: bool,
        scan_idx: int,
        reused_ids: set[int],
    ) -> Order | None:
        """为扫描条目找可复用的活跃订单：同位优先，再其他位置（位移匹配）。"""
        # 1) 优先同位置
        existing = self._orders[scan_idx] if scan_idx < len(self._orders) else None
        if (
            existing is not None
            and not existing.done
            and existing.recipe_slug == recipe_slug
            and existing.is_rush == is_rush
            and existing.order_id not in reused_ids
        ):
            return existing
        # 2) 匹配其他位置的活跃订单（订单位移）
        for other in self._orders:
            if (
                other is not None
                and not other.done
                and other.recipe_slug == recipe_slug
                and other.is_rush == is_rush
                and other.order_id not in reused_ids
            ):
                return other
        return None

    def _remember_removed_order(self, order: Order) -> None:
        """订单被移除（serve/timeout）时记入防复活内存（墙钟时刻）。"""
        self._recently_removed[order.order_id] = (
            order.recipe_slug,
            order.is_rush,
            self._clock(),
        )

    def _prune_removed_order_memory(self, now_wall: float) -> None:
        """清理超出记忆窗口的已删除订单记录。"""
        expired = [
            order_id
            for order_id, (_slug, _rush, removed_at) in self._recently_removed.items()
            if now_wall - removed_at > self.REMOVED_ORDER_MEMORY_WINDOW
        ]
        for order_id in expired:
            del self._recently_removed[order_id]

    def _was_recently_removed(
        self, recipe_slug: str, is_rush: bool, now_wall: float
    ) -> bool:
        """同 (slug, rush) 订单是否在记忆窗口内被删除（旧扫描帧判定）。"""
        return any(
            slug == recipe_slug
            and rush == is_rush
            and now_wall - removed_at <= self.REMOVED_ORDER_MEMORY_WINDOW
            for slug, rush, removed_at in self._recently_removed.values()
        )

    def check_and_remove_timed_out_orders(self) -> list[int]:
        """检查并移除超时订单，返回超时订单ID列表"""
        timed_out = []
        now = self.time
        for i, order in enumerate(self._orders):
            if order is not None and not order.done and now >= order.timeout_at:
                timed_out.append(order.order_id)
                logger.warning(
                    f"[t={self.time:.1f}s] Order {order.order_id} ({order.recipe_slug}) timed out in slot {i}"
                )
                self._remember_removed_order(order)
                self._orders[i] = None

        if timed_out:
            self._shift_orders_left()
        else:
            self._log_orders_state("timeout_check")

        return timed_out

    def get_order_by_id(self, order_id: int) -> Order | None:
        """根据ID获取订单"""
        for order in self._orders:
            if order and order.order_id == order_id:
                return order
        return None

    def get_order_slot(self, order_id: int) -> int | None:
        """获取订单所在的槽位索引"""
        for i, order in enumerate(self._orders):
            if order and order.order_id == order_id:
                return i
        return None

    # ========================================================================
    # 状态查询
    # ========================================================================

    def get_free_cookers(self) -> list[str]:
        """获取空闲灶台列表"""
        return [name for name, cooker in self._cookers.items() if not cooker.busy]

    def get_done_cookers(self) -> list[str]:
        """获取烹饪完成的灶台列表"""
        return [
            name
            for name, cooker in self._cookers.items()
            if cooker.busy and cooker.done_at and self.time >= cooker.done_at
        ]

    def get_stockpile_count(self, ingredient: str) -> int:
        """获取指定食材的库存数量"""
        for slot in self._stockpile.values():
            if slot.item_name == ingredient:
                return slot.count
        return 0

    def find_stockpile_slot(self, ingredient: str) -> str | None:
        """找到存储指定食材的库存槽位"""
        for slot_name, slot in self._stockpile.items():
            if slot.item_name == ingredient and slot.count > 0:
                return slot_name
        return None

    def find_empty_stockpile_slot(self) -> str | None:
        """找到空的库存槽位"""
        for slot_name, slot in self._stockpile.items():
            if slot.item_name is None or slot.count == 0:
                return slot_name
        return None

    def _infer_recipe_slug_from_ingredient(self, ingredient: str) -> str | None:
        """根据单个食材和活跃订单推断目标配方"""
        for order in self._orders:
            if order and not order.done:
                recipe = self._recipes.get(order.recipe_slug)
                if recipe:
                    raw_ings = recipe.raw_ingredients
                    if ingredient in raw_ings:
                        return order.recipe_slug
        return None

    def get_recipe_for_ingredient_cooker(
        self, ingredient: str, cooker_type: str
    ) -> str | None:
        """
        根据 (ingredient, cooker) 组合确定目标recipe。
        
        逻辑：
        1. 遍历活跃订单
        2. 检查 ingredient+cooker 是否匹配 recipe 的 (raw_ingredients[0], cookers[0])
        3. 返回匹配的recipe_slug，不匹配则返回None
        
        场景分析：
        - gildedShoreRisotto: raw=[clearwater_fish, creamfield_rice], cooks=[oven, pot]
        - braisedNewYearFish: raw=[clearwater_fish], cooks=[skillet]
        - clearwater_fish(oven) → 只能匹配 gildedShoreRisotto
        - clearwater_fish(skillet) → 只能匹配 braisedNewYearFish
        """
        for order in self._orders:
            if order and not order.done:
                recipe = self._recipes.get(order.recipe_slug)
                if recipe:
                    raw_ings = recipe.raw_ingredients
                    cookers = recipe.cookers
                    if raw_ings and cookers:
                        if raw_ings[0] == ingredient and cookers[0] == cooker_type:
                            return order.recipe_slug
        return None

    def _infer_recipe_slug_from_ingredients(self, ingredients: list[str]) -> str | None:
        """根据多个食材和活跃订单推断目标配方"""
        for order in self._orders:
            if order and not order.done:
                recipe = self._recipes.get(order.recipe_slug)
                if recipe:
                    raw_ings = set(recipe.raw_ingredients)
                    if all(ing in raw_ings for ing in ingredients):
                        return order.recipe_slug
        return None
