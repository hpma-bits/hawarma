"""
统一烹饪 Agent

地位：基于优先级的贪心策略，在 90 秒内最大化订单完成数
      通过 GameEnvironment 与真实游戏交互

决策模型：按优先级顺序选择动作
1. 送餐
2. 移动完成食材
3. 开始烹饪（让灶台尽早异步工作）
4. 添加调料（食材齐全时）
5. 从库存取用
6. 清理过期食材
7. 存入库存

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


# ============================================================================
# 常量配置
# ============================================================================

# 灶台过期时间（秒，完成烹饪后）
COOKER_EXPIRE_SECONDS = 5.0


# ============================================================================
# Agent 核心类
# ============================================================================

class CookingAgent:
    """
    统一烹饪 Agent

    贪心策略（按优先级）：
    1. 送餐
    2. 移动完成食材
    3. 开始烹饪
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
            slug = r.slug if hasattr(r, 'slug') else r.get('slug')
            self._recipe_by_slug[slug] = r

        # 食材 -> (灶台, 时长) 映射
        self._ingredient_info: dict[str, tuple[str, float]] = {}
        self._build_ingredient_info()

        # 配方 slug -> 调料需求 dict（每个名字 -> 所需数量，默认每个1份）
        self._recipe_condiments: dict[str, dict[str, int]] = {}
        for r in recipes:
            slug = r.slug if hasattr(r, 'slug') else r.get('slug')
            raw = r.condiments if hasattr(r, 'condiments') else r.get('condiments', [])
            if isinstance(raw, list):
                self._recipe_condiments[slug] = {c: 1 for c in raw}
            elif isinstance(raw, dict):
                self._recipe_condiments[slug] = dict(raw)
            else:
                self._recipe_condiments[slug] = {}

        # 统计
        self.stats = {
            "orders_served": 0,
            "total_score": 0,
            "orders_timeout": 0,
            "actions_taken": 0,
        }

        logger.info(f"CookingAgent ready | {len(recipes)} recipes | {len(self._ingredient_info)} ingredients")

    # ========================================================================
    # 初始化辅助
    # ========================================================================

    def _build_ingredient_info(self) -> None:
        """构建食材 -> (灶台, 时长) 映射"""
        for recipe in self.recipes:
            raw_ingredients = recipe.raw_ingredients if hasattr(recipe, 'raw_ingredients') else recipe.get('raw_ingredients', [])
            cookers = recipe.cookers if hasattr(recipe, 'cookers') else recipe.get('cookers', [])
            cook_durations = recipe.cook_durations if hasattr(recipe, 'cook_durations') else recipe.get('cook_durations', [])

            for i, ing in enumerate(raw_ingredients):
                if ing not in self._ingredient_info:
                    cooker = cookers[i] if i < len(cookers) else None
                    duration = cook_durations[i] if i < len(cook_durations) else 3.0
                    if cooker:
                        self._ingredient_info[ing] = (cooker, duration)

    # ========================================================================
    # 决策入口
    # ========================================================================

    def step(self) -> Optional[Action]:
        """
        单步决策：按优先级选择最优动作
        
        优先级顺序（文档定义）：
        1. 送餐
        2. 移动完成食材
        3. 开始烹饪
        4. 添加调料
        5. 从库存取用
        6. 清理过期食材
        7. 存入库存
        """
        # 检查动画窗口
        if self.env.is_in_animation_window():
            return None
        
        # 1. 送餐
        if action := self._try_serve():
            return action
        
        # 2. 移动完成食材
        if action := self._try_move_to_assembly():
            return action
        
        # 3. 开始烹饪
        if action := self._try_start_cooking():
            return action
        
        # 4. 添加调料
        if action := self._try_add_condiment():
            return action
        
        # 5. 从库存取用
        if action := self._try_pull_from_stockpile():
            return action
        
        # 6. 清理过期食材
        if action := self._try_clear_expired():
            return action
        
        # 7. 存入库存
        if action := self._try_store_to_stockpile():
            return action
        
        return None
    
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
        needed_ings = self._get_needed_ingredient_names()
        if not needed_ings:
            return None

        for cooker_name, cooker in self.env.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue

            # 烹饪未完成（done_at 是绝对时间戳）
            if time.time() < cooker.done_at:
                continue

            # 食材过期，跳过（由清理步骤处理）
            if time.time() >= cooker.done_at + COOKER_EXPIRE_SECONDS:
                continue

            if cooker.ingredient_name not in needed_ings:
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

    def _try_start_cooking(self) -> Optional[CookAction]:
        """为空闲灶台分配烹饪任务（按需响应，不预烹饪）"""
        free_cookers = self._get_free_cookers()
        if not free_cookers:
            return None

        to_cook = self._get_ingredients_to_cook()

        # 烹饪订单需要的食材
        for ing_name, cooker_type in to_cook:
            if cooker_type not in free_cookers:
                continue

            # 已经在烹饪中
            if self._is_cooking(ing_name):
                continue

            # 库存已有，跳过（优先使用库存）
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

        # 不预烹饪 - 按需响应策略更可靠
        return None

    # ========================================================================
    # 清理过期食材
    # ========================================================================

    def _try_clear_expired(self) -> Optional[ClearCookerAction]:
        """清理过期食材（完成烹饪后超过 5 秒未取走）"""
        for cooker_name, cooker in self.env.cookers.items():
            if cooker.busy and cooker.done_at:
                if time.time() >= cooker.done_at + COOKER_EXPIRE_SECONDS:
                    return ClearCookerAction(cooker=cooker_name)
        return None

    # ========================================================================
    # 存入库存
    # ========================================================================

    def _try_store_to_stockpile(self) -> Optional[MoveToStockpileAction]:
        """将灶台完成的多余食材存入库存"""
        assembly = self.env.assembly

        # 组装站空闲时不需要存储——食材可以直接移到组装站
        if assembly.is_free:
            return None

        # 组装站有目标配方，但灶台食材不是配方需要的 => 存入库存
        for cooker_name, cooker in self.env.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            if time.time() < cooker.done_at:
                continue

            # 如果组装站需要这个食材，不应该存入库存
            needed = self._get_needed_ingredient_names()
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
        """按优先级排序订单：rush 优先，timeout 近的优先"""
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
            return (rush_priority, timeout_remaining)

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

    def _get_needed_ingredients(self) -> list[tuple[str, str]]:
        """获取当前组装站/订单需要的食材列表 [(ingredient, cooker)]"""
        assembly = self.env.assembly
        target_slug = assembly.target_recipe_slug
        present = set(assembly.ingredients)

        if target_slug:
            recipe = self._recipe_by_slug.get(target_slug)
            if recipe:
                raw = recipe.raw_ingredients if hasattr(recipe, 'raw_ingredients') else recipe.get('raw_ingredients', [])
                cookers = recipe.cookers if hasattr(recipe, 'cookers') else recipe.get('cookers', [])
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
                raw = recipe.raw_ingredients if hasattr(recipe, 'raw_ingredients') else recipe.get('raw_ingredients', [])
                cookers = recipe.cookers if hasattr(recipe, 'cookers') else recipe.get('cookers', [])
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

    def _can_add_to_assembly(self, ingredient: str) -> bool:
        """检查食材是否可以添加到组装站"""
        assembly = self.env.assembly
        present = set(assembly.ingredients)
        target_slug = assembly.target_recipe_slug

        if not present and not target_slug:
            return True

        if not target_slug:
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
                raw = recipe.raw_ingredients if hasattr(recipe, 'raw_ingredients') else recipe.get('raw_ingredients', [])
                if ingredient in raw:
                    return order.order_id
        return None

    def _ingredients_match(self, actual: list, recipe) -> bool:
        """检查食材是否匹配配方（忽略顺序）"""
        expected = recipe.raw_ingredients if hasattr(recipe, 'raw_ingredients') else recipe.get('raw_ingredients', [])
        return sorted(actual) == sorted(expected)

    def _condiments_complete(self, applied: dict[str, int], needed: dict[str, int]) -> bool:
        """检查调料是否齐全"""
        for condiment, count in needed.items():
            if applied.get(condiment, 0) < count:
                return False
        return True

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "time": self.env.time,
            "orders_served": self.stats["orders_served"],
            "total_score": self.stats["total_score"],
            "orders_timeout": self.stats["orders_timeout"],
            "actions_taken": self.stats["actions_taken"],
        }
