"""
统一烹饪 Agent

地位：Agent Shell + Strategy 注入模式
      - Strategy 负责纯决策（decide(state) -> Action）
      - Agent Shell 负责环境状态封装、停滞检测诊断、统计

输入：GameEnvironment、配方列表、可选 Strategy
输出：Action 对象供执行器执行

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger


def _action_name(action: Action | None) -> str:
    """Get the action class name for logging"""
    if action is None:
        return "None"
    return type(action).__name__

# ============================================================================
# 动作类型定义
# ============================================================================


@dataclass
class Action:
    """动作基类"""


@dataclass
class CookAction(Action):
    """烹饪动作"""

    ingredient: str
    cooker: str
    duration: float
    order_id: int | None = None


@dataclass
class MoveToAssemblyAction(Action):
    """移动到组装站"""

    cooker: str
    order_id: int | None = None


@dataclass
class MoveToStockpileAction(Action):
    """移动到库存"""

    cooker: str
    slot: str


@dataclass
class PullFromStockpileAction(Action):
    """从库存取用"""

    slot: str
    ingredient: str


@dataclass
class AddCondimentAction(Action):
    """添加调料"""

    condiment: str


@dataclass
class ServeOrderAction(Action):
    """送餐"""

    slot_idx: int


@dataclass
class ClearCookerAction(Action):
    """清理灶台"""

    cooker: str


@dataclass
class ClearAssemblyAction(Action):
    """清空组装站（丢弃食材）"""


# ============================================================================
# Agent 核心类
# ============================================================================


class CookingAgent:
    """
    统一烹饪 Agent

    重构后：纯 Agent Shell + Strategy 注入模式。
    - Strategy 负责纯决策（decide(state) -> Action）
    - Agent Shell 负责环境状态封装、停滞检测诊断、统计

    所有决策逻辑已迁移到 playground.strategies.default.DefaultStrategy。
    """

    def __init__(self, env, recipes: list, strategy=None):
        self.env = env
        self.recipes = recipes

        # 配方 slug -> Recipe 映射
        self._recipe_by_slug: dict = {}
        for r in recipes:
            if hasattr(env, "get_recipe_adapter") and hasattr(r, "slug"):
                adapter = env.get_recipe_adapter(r.slug)
                if adapter:
                    self._recipe_by_slug[r.slug] = adapter
                    continue

            slug = r.slug if hasattr(r, "slug") else r.get("slug")
            self._recipe_by_slug[slug] = r

        self._use_adapters = hasattr(env, "get_recipe_adapter")

        # 配方 slug -> 调料需求 dict
        self._recipe_condiments: dict[str, dict[str, int]] = {}
        for r in recipes:
            slug = r.slug if hasattr(r, "slug") else r.get("slug")
            condiments = self._get_recipe_attr(r, "condiments", [])
            if isinstance(condiments, list):
                self._recipe_condiments[slug] = {c: 1 for c in condiments}
            elif isinstance(condiments, dict):
                self._recipe_condiments[slug] = dict(condiments)
            else:
                self._recipe_condiments[slug] = {}

        # 注入 Strategy（默认使用 DefaultStrategy）
        if strategy is None:
            from playground.strategies.default import DefaultStrategy
            strategy = DefaultStrategy()
        strategy.on_game_start(self._recipe_by_slug)
        self._strategy = strategy

        # 统计
        self.stats = {
            "orders_served": 0,
            "total_score": 0,
            "orders_timeout": 0,
            "actions_taken": 0,
        }

        # 停滞检测
        self._consecutive_none = 0
        self._last_action_time = 0.0
        self._stagnation_warned = False

        logger.info(
            f"CookingAgent ready | {len(recipes)} recipes | strategy={type(strategy).__name__}"
        )

    def _get_recipe_attr(self, recipe, attr_name, default=None):
        """
        获取recipe属性，支持多种格式

        Args:
            recipe: recipe对象
            attr_name: 属性名
            default: 默认值

        Returns:
            属性值或默认值
        """
        if hasattr(recipe, "ingredients") and attr_name == "raw_ingredients":
            return [ing.name for ing in recipe.ingredients]
        if hasattr(recipe, "ingredients") and attr_name == "cookers":
            return [ing.cooker_type for ing in recipe.ingredients]
        if hasattr(recipe, "ingredients") and attr_name == "cook_durations":
            return [ing.duration for ing in recipe.ingredients]

        if hasattr(recipe, attr_name):
            return getattr(recipe, attr_name)

        if isinstance(recipe, dict):
            return recipe.get(attr_name, default)

        return default

    # ========================================================================
    # 决策入口
    # ========================================================================

    def step(self) -> Action | None:
        """
        单步决策：Agent Shell + Strategy 模式

        流程：
        1. 构建 UnifiedState 从 env
        2. 调用 Strategy.decide(state) 获取动作
        3. 返回动作

        Agent Shell 不再包含 Safety Layer——所有决策（包括 clear_assembly）
        都由注入的 Strategy 负责。
        """
        state = self._build_unified_state()
        action = self._strategy.decide(state)

        if action:
            logger.debug(f"[t={self.env.time:.1f}s] step: strategy returned {_action_name(action)}")
        else:
            logger.debug(f"[t={self.env.time:.1f}s] step: strategy returned None")

        return action

    def _build_unified_state(self):
        """从 self.env 构建 UnifiedState（供 Strategy 使用）"""
        from playground.env.unified_state import UnifiedState

        assembly = self.env.assembly
        ingredients_cookers = [(ing[0], ing[1]) for ing in assembly.ingredients_cookers]

        orders = []
        for order in self.env.orders:
            if order is None:
                orders.append(None)
            else:
                orders.append(order)

        return UnifiedState(
            time=self.env.time,
            orders=tuple(orders),
            cookers=dict(self.env.cookers),
            assembly=assembly,
            stockpile=dict(self.env.stockpile),
            recipes=dict(self._recipe_by_slug),
            game_duration=getattr(self.env, '_game_duration', 90.0),
            is_in_animation_window=self.env.is_in_animation_window(),
        )

    def step_with_diagnostics(self) -> Action | None:
        """带诊断的单步决策，记录停滞原因"""
        action = self.step()

        if action:
            self._consecutive_none = 0
            self._last_action_time = self.env.time
            self._stagnation_warned = False
            return action

        self._consecutive_none += 1
        stagnant_duration = self._consecutive_none * 0.05

        if stagnant_duration >= 5.0 and not self._stagnation_warned:
            self._stagnation_warned = True
            self._log_stagnation_diagnostic(stagnant_duration)

        return action

    def _log_stagnation_diagnostic(self, stagnant_duration: float) -> None:
        """记录停滞诊断信息"""
        assembly = self.env.assembly
        assembly_ings = [
            ing[0] if isinstance(ing, tuple) else ing
            for ing in assembly.ingredients_cookers
        ]

        active_orders = [
            (i, o) for i, o in enumerate(self.env.orders) if o and not o.done
        ]
        free_cookers = self._get_free_cookers()
        cooking = [c.ingredient_name for c in self.env.cookers.values() if c.busy]
        stockpile = {
            n: s.ingredient_name for n, s in self.env.stockpile.items() if s.count > 0
        }

        reasons = []

        if self.env.is_in_animation_window():
            reasons.append("animation_window")

        if assembly_ings:
            if assembly.target_recipe_slug:
                condiments_needed = self._recipe_condiments.get(
                    assembly.target_recipe_slug, {}
                )
                if condiments_needed and not self._condiments_complete(
                    assembly.condiments, condiments_needed
                ):
                    missing_c = [
                        c
                        for c in condiments_needed
                        if assembly.condiments.get(c, 0) < condiments_needed[c]
                    ]
                    reasons.append(f"condiments_incomplete(missing={missing_c})")
            else:
                inferred = self._infer_recipe_from_assembly()
                if inferred:
                    condiments_needed = self._recipe_condiments.get(inferred, {})
                    if condiments_needed:
                        reasons.append(
                            f"condiments_incomplete(inferred={inferred}, missing={list(condiments_needed.keys())})"
                        )
                else:
                    reasons.append("no_target_recipe")

        if not free_cookers:
            reasons.append("no_free_cookers")

        if cooking:
            reasons.append(f"cooking={cooking}")

        if stockpile:
            reasons.append(f"stockpile={list(stockpile.values())}")

        order_summary = [
            f"{o.recipe_slug}({o.timeout_at - self.env.time:.0f}s)"
            for _, o in active_orders
        ]

        logger.warning(
            f"[t={self.env.time:.1f}s] Agent stagnation: {stagnant_duration:.1f}s without action | "
            f"assembly=[{', '.join(assembly_ings)}] target={assembly.target_recipe_slug} | "
            f"orders=[{', '.join(order_summary)}] | "
            f"reasons=[{', '.join(reasons) if reasons else 'unknown'}]"
        )

    # ========================================================================
    # 订单优先级
    # ========================================================================

    def _prioritized_orders(self) -> list[tuple[int, object]]:
        """按优先级排序订单：rush 优先，timeout 近的优先，创建早的优先"""
        orders_with_idx = []
        for i, order in enumerate(self.env.orders):
            if order is not None and not order.done:
                orders_with_idx.append((i, order))

        def sort_key(item):
            _, order = item
            rush_priority = 0 if order.is_rush else 1
            timeout_remaining = order.timeout_at - self.env.time
            created_at = order.created_at
            return (rush_priority, timeout_remaining, created_at)

        orders_with_idx.sort(key=sort_key)
        return orders_with_idx

    # ========================================================================
    # 辅助方法
    # ========================================================================

    def on_order_timeout(self, order_id: int) -> None:
        """订单超时时由外部调用，更新统计"""
        self.stats["orders_timeout"] += 1

    def on_order_served(self, score: int = 1) -> None:
        """订单送餐成功时由外部调用，更新统计"""
        self.stats["orders_served"] += 1
        self.stats["total_score"] += score

    def _get_free_cookers(self) -> list[str]:
        """获取空闲灶台列表"""
        return [name for name, cooker in self.env.cookers.items() if not cooker.busy]

    def _condiments_complete(
        self, applied: dict[str, int], needed: dict[str, int]
    ) -> bool:
        """检查调料是否齐全"""
        for condiment, count in needed.items():
            if applied.get(condiment, 0) < count:
                return False
        return True

    def _infer_recipe_from_assembly(self) -> str | None:
        """根据组装站食材推断匹配的配方"""
        assembly = self.env.assembly
        if not assembly.ingredients_cookers:
            return None

        assembly_pairs = set()
        for ing in assembly.ingredients_cookers:
            if isinstance(ing, tuple):
                assembly_pairs.add((ing[0], ing[1] if len(ing) > 1 else None))
            else:
                assembly_pairs.add((ing, None))

        for _, order in self._prioritized_orders():
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe:
                raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
                cookers = self._get_recipe_attr(recipe, "cookers", [])
                recipe_pairs = set()
                for i, ing in enumerate(raw):
                    cooker = cookers[i] if i < len(cookers) else None
                    recipe_pairs.add((ing, cooker))
                if assembly_pairs == recipe_pairs:
                    return order.recipe_slug
        return None

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "time": self.env.time,
            "orders_served": self.stats["orders_served"],
            "total_score": self.stats["total_score"],
            "orders_timeout": self.stats["orders_timeout"],
            "actions_taken": self.stats["actions_taken"],
        }
