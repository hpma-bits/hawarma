"""
统一烹饪 Agent

地位：基于多订单并行策略，在 90 秒内最大化订单完成数
      通过 GameEnvironment 与真实游戏交互

策略核心思想：
1. 收集所有订单需要的食材
2. 为空闲灶台分配烹饪任务（即使不是当前订单需要的）
3. 完成后存入stockpile，供后续订单使用

优先级顺序：
1. 送餐
2. 开始烹饪（动画窗口期间允许，尽早启动灶台）
3. 移动完成食材（当前订单需要的）
4. 添加调料
5. 存入stockpile（非当前订单需要的食材）
6. 从库存取用
7. 清理过期食材

输入：GameEnvironment、配方列表
输出：动作对象供执行器执行

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from loguru import logger


# ============================================================================
# 动作类型定义
# ============================================================================

@dataclass
class Action:
    """动作基类"""
    pass


@dataclass
class CookAction(Action):
    """烹饪动作"""
    ingredient: str
    cooker: str
    duration: float
    order_id: Optional[int] = None


@dataclass
class MoveToAssemblyAction(Action):
    """移动到组装站"""
    cooker: str
    order_id: Optional[int] = None


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
    pass


# ============================================================================
# Agent 核心类
# ============================================================================

class CookingAgent:
    """
    统一烹饪 Agent

    贪心策略（按优先级）：
    1. 送餐（动画窗口期间跳过）
    2. 开始烹饪（动画窗口期间允许，尽早启动灶台）
    3. 移动完成食材
    4. 添加调料
    5. 从库存取用
    6. 清理过期食材
    7. 存入库存
    """

    def __init__(self, env, recipes: list):
        self.env = env
        self.recipes = recipes
        
        # 配方 slug -> Recipe 映射
        self._recipe_by_slug: dict = {}
        for r in recipes:
            # 如果环境有get_recipe_adapter方法，使用适配器
            if hasattr(env, 'get_recipe_adapter') and hasattr(r, 'slug'):
                adapter = env.get_recipe_adapter(r.slug)
                if adapter:
                    self._recipe_by_slug[r.slug] = adapter
                    continue
            
            # 否则直接使用recipe
            slug = r.slug if hasattr(r, 'slug') else r.get('slug')
            self._recipe_by_slug[slug] = r
        
        # 检查是否有适配器
        self._use_adapters = hasattr(env, 'get_recipe_adapter')
        
        # 食材 -> (灶台, 时长) 映射
        self._ingredient_info_dict: dict[str, tuple[str, float]] = {}
        self._build_ingredient_info()
        
        # 配方 slug -> 调料需求 dict
        self._recipe_condiments: dict[str, dict[str, int]] = {}
        for r in recipes:
            slug = r.slug if hasattr(r, 'slug') else r.get('slug')
            condiments = self._get_recipe_attr(r, 'condiments', [])
            if isinstance(condiments, list):
                self._recipe_condiments[slug] = {c: 1 for c in condiments}
            elif isinstance(condiments, dict):
                self._recipe_condiments[slug] = dict(condiments)
            else:
                self._recipe_condiments[slug] = {}
        
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
        
        # 组装站停滞计时
        self._assembly_stale_since: float | None = None
        
        logger.info(f"CookingAgent ready | {len(recipes)} recipes | {len(self._ingredient_info_dict)} ingredients")
    
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
        # Handle Recipe objects from simulator - convert ingredients to raw_ingredients/cookers/cook_durations
        if hasattr(recipe, 'ingredients') and attr_name == 'raw_ingredients':
            return [ing.name for ing in recipe.ingredients]
        if hasattr(recipe, 'ingredients') and attr_name == 'cookers':
            return [ing.cooker_type for ing in recipe.ingredients]
        if hasattr(recipe, 'ingredients') and attr_name == 'cook_durations':
            return [ing.duration for ing in recipe.ingredients]
        
        # If it's a Recipe object, also check for the attribute directly
        if hasattr(recipe, attr_name):
            return getattr(recipe, attr_name)
        
        # 如果是字典，使用get
        if isinstance(recipe, dict):
            return recipe.get(attr_name, default)
        
        return default
    
    @property
    def _ingredient_info(self) -> dict:
        """食材信息映射"""
        return self._ingredient_info_dict
    
    def _build_ingredient_info(self) -> None:
        """构建食材 -> (灶台, 时长) 映射"""
        for recipe in self.recipes:
            raw_ingredients = self._get_recipe_attr(recipe, 'raw_ingredients', [])
            cookers = self._get_recipe_attr(recipe, 'cookers', [])
            cook_durations = self._get_recipe_attr(recipe, 'cook_durations', [])

            for i, ing in enumerate(raw_ingredients):
                if ing not in self._ingredient_info_dict:
                    cooker = cookers[i] if i < len(cookers) else None
                    duration = cook_durations[i] if i < len(cook_durations) else 3.0
                    if cooker:
                        self._ingredient_info_dict[ing] = (cooker, duration)
  
    # ========================================================================
    # 决策入口
    # ========================================================================

    def step(self) -> Optional[Action]:
        """
        单步决策：多订单并行策略
        
        策略核心思想：
        1. 收集所有订单需要的食材
        2. 为空闲灶台分配烹饪任务（即使不是当前订单需要的）
        3. 完成后存入stockpile，供后续订单使用
        
        优先级顺序：
        1. 送餐（动画窗口期间跳过）
        2. 清理过期食材（防止灶台被占用）
        3. 移动完成食材（当前订单需要的）
        4. 开始烹饪（动画窗口期间允许，尽早启动灶台）
        5. 添加调料
        6. 存入stockpile（非当前订单需要的食材）
        7. 从库存取用
        """
        # 0. 检查assembly是否属于已超时订单，如果是则清空
        if action := self._check_and_clear_expired_assembly():
            return action
        
        # 0.5. 检查组装站是否长时间停滞
        if action := self._check_stale_assembly():
            return action
        
        assembly = self.env.assembly
        # Handle both list[str] (real game) and list[tuple] (simulator)
        assembly_ings = [ing[0] if isinstance(ing, tuple) else ing for ing in assembly.ingredients]
        
        # 1. 送餐（内部有动画窗口检查）
        if action := self._try_serve():
            return action
        
        # 2. 清理过期食材（优先于移动，防止移动过期食材）
        if action := self._try_clear_expired():
            return action
        
        # 3. 移动完成食材到组装站（当前订单需要的）- 内部有过期检查
        if action := self._try_move_to_assembly():
            return action
        
        # 4. 开始烹饪（动画窗口期间允许，尽早启动灶台）
        if action := self._try_parallel_cooking():
            return action
        
        # 5. 添加调料
        if action := self._try_add_condiment():
            return action
        
        # 6. 存入stockpile（非当前订单需要的食材）
        if action := self._try_store_to_stockpile():
            return action
        
        # 7. 从库存取用
        if action := self._try_pull_from_stockpile():
            return action
        
        return None

    def step_with_diagnostics(self) -> Optional[Action]:
        """带诊断的单步决策，记录各优先级检查失败原因"""
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
        assembly_ings = [ing[0] if isinstance(ing, tuple) else ing for ing in assembly.ingredients]
        
        active_orders = [(i, o) for i, o in enumerate(self.env.orders) if o and not o.done]
        free_cookers = self._get_free_cookers()
        cooking = [c.ingredient_name for c in self.env.cookers.values() if c.busy]
        stockpile = {n: s.ingredient_name for n, s in self.env.stockpile.items() if s.count > 0}
        
        reasons = []
        
        if self.env.is_in_animation_window():
            reasons.append("animation_window")
        
        if assembly_ings:
            if assembly.target_recipe_slug:
                condiments_needed = self._recipe_condiments.get(assembly.target_recipe_slug, {})
                if condiments_needed and not self._condiments_complete(assembly.condiments, condiments_needed):
                    missing_c = [c for c in condiments_needed if assembly.condiments.get(c, 0) < condiments_needed[c]]
                    reasons.append(f"condiments_incomplete(missing={missing_c})")
            else:
                inferred = self._infer_recipe_from_assembly()
                if inferred:
                    condiments_needed = self._recipe_condiments.get(inferred, {})
                    if condiments_needed:
                        reasons.append(f"condiments_incomplete(inferred={inferred}, missing={list(condiments_needed.keys())})")
                else:
                    reasons.append("no_target_recipe")
        
        if not free_cookers:
            reasons.append("no_free_cookers")
        
        if cooking:
            reasons.append(f"cooking={cooking}")
        
        if stockpile:
            reasons.append(f"stockpile={list(stockpile.values())}")
        
        order_summary = [f"{o.recipe_slug}({o.timeout_at - self.env.time:.0f}s)" for _, o in active_orders]
        
        logger.warning(
            f"[t={self.env.time:.1f}s] Agent stagnation: {stagnant_duration:.1f}s without action | "
            f"assembly=[{', '.join(assembly_ings)}] target={assembly.target_recipe_slug} | "
            f"orders=[{', '.join(order_summary)}] | "
            f"reasons=[{', '.join(reasons) if reasons else 'unknown'}]"
        )
    
    def _get_assembly_stage(self) -> str:
        """
        判断组装站当前阶段
        
        Returns:
            "NOT_READY": 食材未齐全
            "NEEDS_SEASONING": 食材齐全但调料未齐
            "READY": 食材和调料都齐全
        """
        assembly = self.env.assembly
        
        if not assembly.ingredients:
            return "NOT_READY"
        
        target_slug = assembly.target_recipe_slug
        if not target_slug:
            return "NOT_READY"
        
        recipe = self._recipe_by_slug.get(target_slug)
        if not recipe:
            return "NOT_READY"
        
        # 检查食材是否齐全
        if not self._ingredients_match(assembly.ingredients, recipe):
            return "NOT_READY"
        
        # 食材齐全，检查调料
        condiments_needed = self._recipe_condiments.get(target_slug, {})
        if self._condiments_complete(assembly.condiments, condiments_needed):
            return "READY"
        
        return "NEEDS_SEASONING"

    # ========================================================================
    # 送餐
    # ========================================================================

    def _try_serve(self) -> Optional[ServeOrderAction]:
        """送餐：组装站菜品匹配某个订单时立即送"""
        if self.env.is_in_animation_window():
            return None

        assembly = self.env.assembly
        if not assembly.ingredients:
            return None

        target_slug = assembly.target_recipe_slug

        # 按优先级遍历订单：rush 优先，timeout 近的优先
        for slot_idx, order in self._prioritized_orders():
            if order is None or order.done:
                continue

            # 如果组装站有目标配方，必须匹配
            if target_slug and target_slug != order.recipe_slug:
                continue

            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe and self._ingredients_match(assembly.ingredients, recipe):
                # 检查调料是否齐全
                condiments_needed = self._recipe_condiments.get(order.recipe_slug, {})
                if self._condiments_complete(assembly.condiments, condiments_needed):
                    return ServeOrderAction(slot_idx=slot_idx)

        return None

    # ========================================================================
    # 添加调料
    # ========================================================================

    def _try_add_condiment(self) -> Optional[AddCondimentAction]:
        """添加调料：只有当食材齐全时才添加调料"""
        assembly = self.env.assembly
        target_slug = assembly.target_recipe_slug

        # 如果没有目标配方，尝试从食材推断
        if not target_slug:
            target_slug = self._infer_recipe_from_assembly()
            if not target_slug:
                return None

        recipe = self._recipe_by_slug.get(target_slug)
        if not recipe:
            return None

        # 检查食材是否齐全
        if not self._ingredients_match(assembly.ingredients, recipe):
            return None

        condiments_needed = self._recipe_condiments.get(target_slug, {})
        if not condiments_needed:
            return None

        for condiment, required in condiments_needed.items():
            current = self.env.get_condiment_count(condiment)
            if current < required:
                return AddCondimentAction(condiment=condiment)

        return None

    # ========================================================================
    # 移动完成食材
    # ========================================================================

    def _try_move_to_assembly(self) -> Optional[MoveToAssemblyAction]:
        """将完成的食材从灶台移到组装站"""
        # 获取当前订单需要的食材
        needed_ings = self._get_needed_ingredient_names()
        
        # 获取所有活跃订单需要的食材
        all_needed = set()
        for order in self.env.orders:
            if order and not order.done:
                recipe = self._recipe_by_slug.get(order.recipe_slug)
                if recipe:
                    raw = self._get_recipe_attr(recipe, 'raw_ingredients', [])
                    all_needed.update(raw)

        # 使用并集：移动任何活跃订单需要的食材
        effective_needed = needed_ings | all_needed
        if not effective_needed:
            return None

        for cooker_name, cooker in self.env.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue

            # 烹饪未完成
            if self.env.time < cooker.done_at:
                continue

            # 食材过期，跳过
            if cooker.is_expired(self.env.time):
                continue

            if cooker.ingredient_name not in effective_needed:
                continue

            if self._can_add_to_assembly(cooker.ingredient_name):
                order_id = self._get_order_id_for_ingredient(cooker.ingredient_name)
                return MoveToAssemblyAction(cooker=cooker_name, order_id=order_id)

        return None

    # ========================================================================
    # 从库存取用
    # ========================================================================

    def _try_pull_from_stockpile(self) -> Optional[PullFromStockpileAction]:
        """从库存取用食材到组装站"""
        assembly = self.env.assembly

        # 组装站已经有食材但不匹配当前订单时，不要拉取
        if assembly.ingredients and not assembly.target_recipe_slug:
            return None

        # 如果组装站有目标配方，检查是否有活跃订单匹配
        if assembly.target_recipe_slug:
            has_active = any(
                o and not o.done and o.recipe_slug == assembly.target_recipe_slug
                for o in self.env.orders
            )
            if not has_active:
                return None  # 目标订单已不存在，不要拉取

        needed_ings = self._get_needed_ingredient_names()
        if not needed_ings:
            return None

        for slot_name, slot in self.env.stockpile.items():
            if slot.ingredient_name in needed_ings and slot.count > 0:
                if self._can_add_to_assembly(slot.ingredient_name):
                    return PullFromStockpileAction(
                        slot=slot_name,
                        ingredient=slot.ingredient_name,
                    )

        return None

    # ========================================================================
    # 开始烹饪
    # ========================================================================

    def _try_parallel_cooking(self) -> Optional[CookAction]:
        """
        多订单并行烹饪 - 利用所有订单需要的食材保证cooker忙碌
        
        核心思想：
        1. 收集当前订单需要的食材
        2. 收集所有订单需要的食材
        3. 优先烹饪当前订单需要的食材
        4. 其次烹饪其他订单需要的食材（如果stockpile中没有）
        """
        free_cookers = self._get_free_cookers()
        if not free_cookers:
            return None
        
        assembly = self.env.assembly
        # Handle both list[str] (real game) and list[tuple] (simulator)
        assembly_ings = [ing[0] if isinstance(ing, tuple) else ing for ing in assembly.ingredients]
        
        # 如果组装站有目标配方，优先烹饪其缺失的食材
        assembly_missing = []
        if assembly.target_recipe_slug:
            recipe = self._recipe_by_slug.get(assembly.target_recipe_slug)
            if recipe:
                raw = self._get_recipe_attr(recipe, 'raw_ingredients', [])
                cookers = self._get_recipe_attr(recipe, 'cookers', [])
                for i, ing_name in enumerate(raw):
                    cooker = cookers[i] if i < len(cookers) else None
                    if cooker and ing_name not in assembly_ings:
                        assembly_missing.append((ing_name, cooker))
        
        # 收集当前订单需要的食材 - 使用优先级排序（rush优先）
        needed_current = []
        for _, order in self._prioritized_orders():
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe:
                raw = self._get_recipe_attr(recipe, 'raw_ingredients', [])
                cookers = self._get_recipe_attr(recipe, 'cookers', [])
                for i, ing_name in enumerate(raw):
                    cooker = cookers[i] if i < len(cookers) else None
                    if cooker and ing_name not in [n for n, _ in needed_current]:
                        needed_current.append((ing_name, cooker))
                break  # 只取第一个优先级最高的订单
        
        # 组装站缺失的食材排最前
        needed_current = assembly_missing + [item for item in needed_current if item not in assembly_missing]
        
        # 收集所有订单需要的食材
        needed_all = []
        seen = set()
        for order in self.env.orders:
            if order and not order.done:
                recipe = self._recipe_by_slug.get(order.recipe_slug)
                if recipe:
                    raw = self._get_recipe_attr(recipe, 'raw_ingredients', [])
                    cookers = self._get_recipe_attr(recipe, 'cookers', [])
                    for i, ing_name in enumerate(raw):
                        cooker = cookers[i] if i < len(cookers) else None
                        if cooker and ing_name not in seen:
                            seen.add(ing_name)
                            needed_all.append((ing_name, cooker))
        
        # 检查哪些食材已在stockpile中
        stockpile_counts = {}
        for slot in self.env.stockpile.values():
            if slot.count > 0 and slot.ingredient_name:
                stockpile_counts[slot.ingredient_name] = stockpile_counts.get(slot.ingredient_name, 0) + slot.count
        
        # 优先烹饪当前订单需要的食材
        for ing_name, cooker_type in needed_current:
            if cooker_type not in free_cookers:
                continue
            if self._is_cooking(ing_name):
                continue
            if ing_name in assembly_ings:
                continue
            if stockpile_counts.get(ing_name, 0) > 0:
                continue
            
            _, duration = self._ingredient_info.get(ing_name, (None, 3.0))
            order_id = self._get_order_id_for_ingredient(ing_name)
            return CookAction(
                ingredient=ing_name,
                cooker=cooker_type,
                duration=duration,
                order_id=order_id,
            )
        
        # 然后烹饪其他订单需要的食材（如果stockpile中没有）
        for ing_name, cooker_type in needed_all:
            if cooker_type not in free_cookers:
                continue
            if self._is_cooking(ing_name):
                continue
            if ing_name in assembly_ings:
                continue
            if stockpile_counts.get(ing_name, 0) > 0:
                continue
            
            _, duration = self._ingredient_info.get(ing_name, (None, 3.0))
            order_id = self._get_order_id_for_ingredient(ing_name)
            return CookAction(
                ingredient=ing_name,
                cooker=cooker_type,
                duration=duration,
                order_id=order_id,
            )
        
        return None
    
    def _try_start_cooking(self) -> Optional[CookAction]:
        """为空闲灶台分配烹饪任务（前瞻性策略 + 按需响应）"""
        free_cookers = self._get_free_cookers()
        if not free_cookers:
            return None

        # 前瞻性烹饪：优先处理紧迫订单的食材
        urgent = self._get_urgent_ingredients()
        for ing_name, cooker_type, remaining in urgent:
            if cooker_type not in free_cookers:
                continue
            
            if self._is_cooking(ing_name):
                continue
            if self._has_in_stockpile(ing_name):
                continue
            
            _, duration = self._ingredient_info.get(ing_name, (None, 3.0))
            order_id = self._get_order_id_for_ingredient(ing_name)
            return CookAction(
                ingredient=ing_name,
                cooker=cooker_type,
                duration=duration,
                order_id=order_id,
            )

        # 按需响应：如果没有紧迫食材，按原有逻辑处理
        to_cook = self._get_ingredients_to_cook()
        for ing_name, cooker_type in to_cook:
            if cooker_type not in free_cookers:
                continue
            if self._is_cooking(ing_name):
                continue
            if self._has_in_stockpile(ing_name):
                continue

            _, duration = self._ingredient_info.get(ing_name, (None, 3.0))
            order_id = self._get_order_id_for_ingredient(ing_name)
            return CookAction(
                ingredient=ing_name,
                cooker=cooker_type,
                duration=duration,
                order_id=order_id,
            )

        return None

    # ========================================================================
    # 清理过期食材
    # ========================================================================

    def _try_clear_expired(self) -> Optional[ClearCookerAction]:
        """清理过期食材（完成烹饪后超过 5 秒未取走）"""
        for cooker_name, cooker in self.env.cookers.items():
            if cooker.busy and cooker.is_expired(self.env.time):
                return ClearCookerAction(cooker=cooker_name)
        return None

    # ========================================================================
    # 存入库存
    # ========================================================================

    def _try_store_to_stockpile(self) -> Optional[MoveToStockpileAction]:
        """将灶台完成的多余食材存入库存"""
        assembly = self.env.assembly
        needed = self._get_needed_ingredient_names()

        # 组装站空闲时：如果食材不是任何活跃订单需要的，存入库存
        if assembly.is_free:
            for cooker_name, cooker in self.env.cookers.items():
                if not cooker.busy or cooker.done_at is None:
                    continue
                if self.env.time < cooker.done_at:
                    continue
                # 食材不是任何订单需要的，存入库存
                if cooker.ingredient_name not in needed:
                    slot = self._find_available_slot(cooker.ingredient_name, cooker.cooker_type)
                    if slot:
                        return MoveToStockpileAction(cooker=cooker_name, slot=slot)
            return None

        # 组装站有目标配方，但灶台食材不是配方需要的 => 存入库存
        for cooker_name, cooker in self.env.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            if self.env.time < cooker.done_at:
                continue

            # 如果组装站需要这个食材，不应该存入库存
            if cooker.ingredient_name in needed:
                continue

            slot = self._find_available_slot(cooker.ingredient_name, cooker.cooker_type)
            if slot:
                return MoveToStockpileAction(cooker=cooker_name, slot=slot)

        return None

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
            # rush 优先（False < True，所以 negation）
            rush_priority = 0 if order.is_rush else 1
            # timeout 越近越优先
            timeout_remaining = order.timeout_at - self.env.time
            # 创建越早越优先
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
    
    def _check_and_clear_expired_assembly(self) -> Optional[ClearAssemblyAction]:
        """检查assembly的食材是否属于已超时的订单，如果是则返回清空动作"""
        assembly = self.env.assembly
        if assembly.is_free:
            return None
        
        assembly_ing_names = [ing[0] if isinstance(ing, tuple) else ing for ing in assembly.ingredients]
        if not assembly_ing_names:
            return None
        
        target_slug = assembly.target_recipe_slug
        
        # 如果有目标配方，检查对应订单是否还有效
        if target_slug:
            for order in self.env.orders:
                if order and not order.done and order.recipe_slug == target_slug:
                    return None  # 订单还有效，不需要清理
            # 目标订单已超时/完成，清空
            return ClearAssemblyAction()
        
        # 没有目标配方（target_slug为None），检查食材是否匹配任何活跃订单
        active_slugs = set()
        for order in self.env.orders:
            if order and not order.done:
                active_slugs.add(order.recipe_slug)
        
        if not active_slugs:
            return ClearAssemblyAction()  # 没有活跃订单
        
        # 检查assembly的食材是否属于任何活跃订单
        for order in self.env.orders:
            if order and not order.done:
                recipe = self._recipe_by_slug.get(order.recipe_slug)
                if recipe:
                    recipe_ings = set(self._get_recipe_attr(recipe, 'raw_ingredients', []))
                    # 如果assembly的所有食材都属于这个订单的配方，保留
                    if all(ing in recipe_ings for ing in assembly_ing_names):
                        return None  # 食材可用于这个订单
        
        # 食材不匹配任何活跃订单，清空
        return ClearAssemblyAction()

    def _check_stale_assembly(self) -> Optional[ClearAssemblyAction]:
        """
        检查组装站是否长时间停滞（食材齐全但无法完成）。
        
        当组装站食材齐全但调料无法添加（如调料灶台被长期占用），
        超过 STALE_THRESHOLD 秒后清空组装站，释放资源重新开始。
        """
        STALE_THRESHOLD = 15.0
        
        assembly = self.env.assembly
        if assembly.is_free or not assembly.ingredients:
            self._assembly_stale_since = None
            return None
        
        target_slug = assembly.target_recipe_slug
        if not target_slug:
            target_slug = self._infer_recipe_from_assembly()
        
        if not target_slug:
            self._assembly_stale_since = None
            return None
        
        recipe = self._recipe_by_slug.get(target_slug)
        if not recipe:
            self._assembly_stale_since = None
            return None
        
        ingredients_complete = self._ingredients_match(assembly.ingredients, recipe)
        condiments_needed = self._recipe_condiments.get(target_slug, {})
        condiments_complete = self._condiments_complete(assembly.condiments, condiments_needed)
        
        if ingredients_complete and not condiments_complete:
            if self._assembly_stale_since is None:
                self._assembly_stale_since = self.env.time
            elif self.env.time - self._assembly_stale_since >= STALE_THRESHOLD:
                logger.warning(
                    f"[t={self.env.time:.1f}s] Assembly stale for {STALE_THRESHOLD}s: "
                    f"{target_slug} ingredients complete but condiments missing "
                    f"({list(condiments_needed.keys())}), clearing"
                )
                self._assembly_stale_since = None
                return ClearAssemblyAction()
        else:
            self._assembly_stale_since = None
        
        return None

    def on_order_served(self, score: int = 1) -> None:
        """订单送餐成功时由外部调用，更新统计"""
        self.stats["orders_served"] += 1
        self.stats["total_score"] += score

    def _get_needed_ingredients(self) -> list[tuple[str, str]]:
        """获取当前组装站/订单需要的食材列表 [(ingredient, cooker)]"""
        assembly = self.env.assembly
        target_slug = assembly.target_recipe_slug
        present = set(assembly.ingredients)

        if target_slug:
            recipe = self._recipe_by_slug.get(target_slug)
            if recipe:
                # Handle Recipe objects (from simulator)
                if hasattr(recipe, 'ingredients') and hasattr(recipe.ingredients, '__iter__'):
                    result = []
                    for ing in recipe.ingredients:
                        if ing.name not in present:
                            result.append((ing.name, ing.cooker_type))
                    return result
                # Handle dict format
                raw = self._get_recipe_attr(recipe, 'raw_ingredients', [])
                cookers = self._get_recipe_attr(recipe, 'cookers', [])
                result = []
                for i, ing in enumerate(raw):
                    if ing not in present:
                        cooker = cookers[i] if i < len(cookers) else None
                        if cooker:
                            result.append((ing, cooker))
                return result

        # 组装站为空，按优先级取第一个订单
        for _, order in self._prioritized_orders():
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe:
                # Handle Recipe objects (from simulator)
                if hasattr(recipe, 'ingredients') and hasattr(recipe.ingredients, '__iter__'):
                    result = []
                    for ing in recipe.ingredients:
                        result.append((ing.name, ing.cooker_type))
                    return result
                # Handle dict format
                raw = self._get_recipe_attr(recipe, 'raw_ingredients', [])
                cookers = self._get_recipe_attr(recipe, 'cookers', [])
                result = []
                for i, ing in enumerate(raw):
                    cooker = cookers[i] if i < len(cookers) else None
                    if cooker:
                        result.append((ing, cooker))
                return result

        return []

    def _get_needed_ingredient_names(self) -> set[str]:
        """获取需要的食材名集合"""
        return {ing for ing, _ in self._get_needed_ingredients()}

    def _get_ingredients_to_cook(self) -> list[tuple[str, str]]:
        """获取需要烹饪的食材列表"""
        needed = self._get_needed_ingredients()
        result = []
        for ing_name, cooker_type in needed:
            if self._is_cooking(ing_name):
                continue
            if self._has_in_stockpile(ing_name):
                continue
            result.append((ing_name, cooker_type))
        return result

    def _get_urgent_ingredients(self) -> list[tuple[str, str, float]]:
        """
        获取需要紧急烹饪的食材列表
        返回: [(ingredient, cooker, remaining_time)]
        按紧迫度排序（rush优先，timeout近的优先）
        """
        result = []
        
        for _, order in self._prioritized_orders():
            remaining = order.timeout_at - self.env.time
            if remaining <= 0:
                continue
            
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if not recipe:
                continue
            
            raw = self._get_recipe_attr(recipe, 'raw_ingredients', [])
            cookers = self._get_recipe_attr(recipe, 'cookers', [])
            
            for i, ing in enumerate(raw):
                cooker = cookers[i] if i < len(cookers) else None
                if not cooker:
                    continue
                if self._is_cooking(ing):
                    continue
                if self._has_in_stockpile(ing):
                    continue
                if self._has_cooked_ingredient(ing):
                    continue
                
                result.append((ing, cooker, remaining))
        
        return result
    
    def _get_time_until_needed(self, ingredient: str) -> float:
        """获取该食材最紧迫的订单剩余时间"""
        min_remaining = float('inf')
        for _, order in self._prioritized_orders():
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if not recipe:
                continue
            raw = self._get_recipe_attr(recipe, 'raw_ingredients', [])
            if ingredient in raw:
                remaining = order.timeout_at - self.env.time
                min_remaining = min(min_remaining, remaining)
        return min_remaining if min_remaining != float('inf') else 0
    
    def _has_cooked_ingredient(self, ingredient: str) -> bool:
        """检查灶台上是否有已完成的该食材"""
        for cooker in self.env.cookers.values():
            if cooker.done_at and cooker.ingredient_name == ingredient:
                return True
        return False

    def _can_add_to_assembly(self, ingredient: str) -> bool:
        """检查食材是否可以添加到组装站"""
        assembly = self.env.assembly
        present = set(assembly.ingredients)
        target_slug = assembly.target_recipe_slug

        if not present and not target_slug:
            return True

        if not target_slug:
            # assembly有食材但没有target，检查ingredient是否匹配任何活跃订单
            for order in self.env.orders:
                if order and not order.done:
                    recipe = self._recipe_by_slug.get(order.recipe_slug)
                    if recipe:
                        raw = self._get_recipe_attr(recipe, 'raw_ingredients', [])
                        if ingredient in raw:
                            return True
            return False

        recipe = self._recipe_by_slug.get(target_slug)
        if not recipe:
            return False

        raw = recipe.raw_ingredients if hasattr(recipe, 'raw_ingredients') else recipe.get('raw_ingredients', [])
        if ingredient not in raw:
            return False

        return ingredient not in present

    def _is_cooking(self, ingredient: str) -> bool:
        """检查食材是否正在烹饪"""
        for cooker in self.env.cookers.values():
            if cooker.busy and cooker.ingredient_name == ingredient:
                return True
        return False

    def _has_in_stockpile(self, ingredient: str) -> bool:
        """检查库存是否有该食材"""
        for slot in self.env.stockpile.values():
            if slot.ingredient_name == ingredient and slot.count > 0:
                return True
        return False

    def _get_free_cookers(self) -> list[str]:
        """获取空闲灶台列表"""
        return [name for name, cooker in self.env.cookers.items() if not cooker.busy]

    def _find_available_slot(self, ingredient: str, cooker_type: str) -> Optional[str]:
        """找到可用的库存槽位"""
        for slot_name, slot in self.env.stockpile.items():
            if slot.ingredient_name is None or (slot.ingredient_name == ingredient and slot.cooker_type == cooker_type):
                if slot.count < 5:
                    return slot_name
        return None

    def _get_order_id_for_ingredient(self, ingredient: str) -> Optional[int]:
        """获取需要该食材的订单ID（优先级排序）"""
        for _, order in self._prioritized_orders():
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe:
                raw = self._get_recipe_attr(recipe, 'raw_ingredients', [])
                if ingredient in raw:
                    return order.order_id
        return None

    def _ingredients_match(self, actual: list, recipe) -> bool:
        """检查食材是否匹配配方（忽略顺序）"""
        expected = recipe.raw_ingredients if hasattr(recipe, 'raw_ingredients') else recipe.get('raw_ingredients', [])
        # Handle tuple format (name, cooker, time) from simulator
        actual_names = [ing[0] if isinstance(ing, tuple) else ing for ing in actual]
        return sorted(actual_names) == sorted(expected)

    def _condiments_complete(self, applied: dict[str, int], needed: dict[str, int]) -> bool:
        """检查调料是否齐全"""
        for condiment, count in needed.items():
            if applied.get(condiment, 0) < count:
                return False
        return True

    def _infer_recipe_from_assembly(self) -> Optional[str]:
        """根据组装站食材推断匹配的配方"""
        assembly = self.env.assembly
        if not assembly.ingredients:
            return None
        
        assembly_names = [ing[0] if isinstance(ing, tuple) else ing for ing in assembly.ingredients]
        
        for _, order in self._prioritized_orders():
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe:
                raw = self._get_recipe_attr(recipe, 'raw_ingredients', [])
                if all(ing in raw for ing in assembly_names):
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
