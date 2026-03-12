# hawarma/services/stockpile_manager.py
"""
Stockpile管理器

地位：独立管理stockpile逻辑，采用事件驱动模式，消除轮询

输入：订单状态变化事件、组装台可用性变化事件
输出：stockpile决策、食材送达指令

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

import asyncio
from collections import Counter
from typing import Dict, List, Set, Tuple, Optional
from loguru import logger

from hawarma.models import Order, Recipe
from hawarma.services.cooking_service import CookingService


class StockpileManager:
    """
    独立管理stockpile逻辑，采用事件驱动模式。
    
    核心特性：
    1. 事件驱动：响应订单状态变化、组装台可用性变化等事件
    2. 消除轮询：不再需要周期性检查，而是响应事件触发
    3. 职责分离：stockpile逻辑与订单处理逻辑完全分离
    4. 资源协调：通过事件机制与订单处理流程协调资源使用
    """

    def __init__(
        self,
        cooking_service: CookingService,
        stockpile_area_assignments: Dict[str, str],
        ordered_recipes: List[Recipe],
        ingredient_stock_counts: Counter,
        ingredient_stock_lock: asyncio.Lock,
        order_slots_lock: asyncio.Lock,
        get_order_slots_func: Optional[callable] = None,
    ):
        """
        初始化StockpileManager。

        Args:
            cooking_service: 烹饪服务实例
            stockpile_area_assignments: 暂存区分配映射
            ordered_recipes: 当前会话的食谱列表
            ingredient_stock_counts: 共享的食材库存计数器（与app.py共享）
            ingredient_stock_lock: 库存访问专用锁
            order_slots_lock: 订单槽位访问专用锁
            get_order_slots_func: 获取当前order slots的函数（用于访问订单状态）
        """
        self.cooking_service = cooking_service
        self.stockpile_area_assignments = stockpile_area_assignments
        self.ordered_recipes = ordered_recipes
        self.ingredient_stock_counts = ingredient_stock_counts  # 共享计数器
        self._ingredient_stock_lock = ingredient_stock_lock
        self._order_slots_lock = order_slots_lock
        self._get_order_slots_func = get_order_slots_func

        # 事件队列
        self._event_queue: asyncio.Queue = asyncio.Queue()
        
        # 运行状态
        self._is_running: bool = False
        self._event_loop_task: Optional[asyncio.Task] = None

        # 组装台状态跟踪（用于资源协调）
        self._assembly_station_occupied: bool = False
        self._assembly_station_lock = asyncio.Lock()

    async def start(self):
        """启动StockpileManager的事件循环。"""
        if self._is_running:
            return
        
        self._is_running = True
        self._event_loop_task = asyncio.create_task(self._event_loop())
        logger.info("StockpileManager started")

    async def stop(self):
        """停止StockpileManager的事件循环。"""
        if not self._is_running:
            return
        
        self._is_running = False
        
        # 发送停止事件
        await self._event_queue.put(None)
        
        if self._event_loop_task:
            try:
                await asyncio.wait_for(self._event_loop_task, timeout=2.0)
            except asyncio.TimeoutError:
                self._event_loop_task.cancel()
                try:
                    await self._event_loop_task
                except asyncio.CancelledError:
                    pass
        
        logger.info("StockpileManager stopped")

    async def _event_loop(self):
        """事件循环，处理所有stockpile相关事件。"""
        while self._is_running:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=0.5
                )
                
                if event is None:  # 停止信号
                    break
                
                await self._handle_event(event)
                
            except asyncio.TimeoutError:
                # 定期检查是否需要处理idle状态
                await self._check_idle_state()
            except Exception as e:
                logger.error(f"Error in StockpileManager event loop: {e}")

    async def _handle_event(self, event: dict):
        """处理单个事件。"""
        event_type = event.get("type")
        
        if event_type == "cooker_available":
            await self._on_cooker_available(event)
        elif event_type == "order_status_changed":
            await self._on_order_status_changed(event)
        elif event_type == "assembly_station_available":
            await self._on_assembly_station_available(event)
        elif event_type == "assembly_station_occupied":
            await self._on_assembly_station_occupied(event)
        else:
            logger.warning(f"Unknown event type: {event_type}")

    async def _on_cooker_available(self, event: dict):
        """当cooker可用时触发，尝试stockpile。"""
        available_cookers = event.get("cookers", [])
        if not available_cookers:
            return
        
        # 按优先级排序决策：先尝试耗时长的食材，优先后续订单需要的
        prioritized = await self._prioritize_ingredients_for_stockpile(available_cookers)
        
        for ingredient_name, cooker_name, recipe in prioritized:
            # 检查库存上限（需要锁保护）
            async with self._ingredient_stock_lock:
                stock_full = self.ingredient_stock_counts[ingredient_name] >= 5
            
            if stock_full:
                continue
            
            # 检查cooker是否仍然可用
            available = await self.cooking_service.get_available_cookers()
            if cooker_name not in available:
                continue
            
            # 执行stockpile
            stockpile_area_idx = list(self.stockpile_area_assignments.values()).index(ingredient_name)
            await self._cook_and_update_stock(
                recipe,
                ingredient_name,
                self.cooking_service.stockpile_area_positions[stockpile_area_idx]
            )
            return  # 一次只处理一个
    
    async def _prioritize_ingredients_for_stockpile(self, available_cookers: list[str]) -> list[tuple[str, str, Recipe]]:
        """
        按优先级排序食材：
        1. 按烹饪时间降序（耗时长的优先）
        2. 优先后续订单需要的食材（不在当前slot 0的订单）
        
        Returns: [(ingredient_name, cooker_name, recipe), ...]
        """
        candidates = []
        
        for cooker_name in available_cookers:
            for ingredient_name, recipe in self._find_all_recipes_for_cooker(cooker_name):
                if ingredient_name in self.stockpile_area_assignments.values():
                    # 计算优先级分数：
                    # 1. 烹饪时间（越大越好，归一化到 0-10）
                    idx = recipe.raw_ingredients.index(ingredient_name)
                    cook_time = recipe.cook_durations[idx]
                    time_score = min(cook_time / 3.0, 10)  # 假设最大烹饪时间约30秒
                    
                    # 2. 是否后续订单需要（+5分）
                    subsequent_bonus = 0
                    order_slots = await self._get_order_slots()
                    if len(order_slots) > 1:
                        # 检查slot 1, 2... 是否需要这个食材
                        for slot_idx in range(1, len(order_slots)):
                            order = await self._get_order_slot(slot_idx)
                            if order and ingredient_name in order.recipe.raw_ingredients:
                                subsequent_bonus = 5
                                break
                    
                    total_score = time_score + subsequent_bonus
                    candidates.append((total_score, ingredient_name, cooker_name, recipe, cook_time))
        
        # 按分数降序排序
        candidates.sort(key=lambda x: x[0], reverse=True)
        
        # 返回排序后的结果
        return [(c[1], c[2], c[3]) for c in candidates]
    
    def _find_all_recipes_for_cooker(self, cooker_name: str) -> list[tuple[str, Recipe]]:
        """找到所有需要该cooker的食材和recipe组合。"""
        results = []
        for recipe in self.ordered_recipes:
            for i, ing in enumerate(recipe.raw_ingredients):
                if recipe.cookers[i] == cooker_name:
                    results.append((ing, recipe))
        return results
    
    async def _get_order_slots(self) -> list:
        """获取order slots（由主程序注入），带锁保护。"""
        async with self._order_slots_lock:
            return self._get_order_slots_func() if self._get_order_slots_func else []
    
    async def _get_order_slot(self, idx: int):
        """获取指定slot的订单，带锁保护。"""
        async with self._order_slots_lock:
            slots = self._get_order_slots_func() if self._get_order_slots_func else []
            return slots[idx] if idx < len(slots) else None

    async def _on_order_status_changed(self, event: dict):
        """当订单状态变化时触发。"""
        order = event.get("order")
        new_status = event.get("status")
        
        if new_status == "HEATING":
            # 订单开始加热，检查是否需要协调资源
            logger.debug(f"Order {order.order_id} started heating")
        elif new_status == "READY_TO_SEASON":
            # 订单准备调味，组装台即将被使用
            logger.debug(f"Order {order.order_id} ready to season")
        elif new_status == "COMPLETED":
            # 订单完成，组装台释放
            logger.debug(f"Order {order.order_id} completed, assembly station released")

    async def _on_assembly_station_available(self, event: dict):
        """当组装台可用时触发。"""
        async with self._assembly_station_lock:
            self._assembly_station_occupied = False
        logger.debug("Assembly station now available")

    async def _on_assembly_station_occupied(self, event: dict):
        """当组装台被占用时触发。"""
        async with self._assembly_station_lock:
            self._assembly_station_occupied = True
        logger.debug("Assembly station now occupied")

    async def _try_stockpile_on_cooker(self, cooker_name: str):
        """尝试在指定cooker上进行stockpile。"""
        # 找到适合该cooker的食材
        for stockpile_area_idx_str, ingredient_name in self.stockpile_area_assignments.items():
            # 检查库存是否已满（需要锁保护）
            async with self._ingredient_stock_lock:
                stock_full = self.ingredient_stock_counts[ingredient_name] >= 5
            
            if stock_full:
                continue
            
            # 找到需要该cooker的recipe
            recipe = self._find_recipe_for_ingredient(ingredient_name, cooker_name)
            if not recipe:
                continue
            
            # 检查cooker是否仍然可用
            available = await self.cooking_service.get_available_cookers()
            if cooker_name not in available:
                return
            
            # 启动stockpile任务
            stockpile_area_idx = int(stockpile_area_idx_str.split("_")[-1])
            await self._cook_and_update_stock(
                recipe,
                ingredient_name,
                self.cooking_service.stockpile_area_positions[stockpile_area_idx]
            )
            return

    def _find_recipe_for_ingredient(self, ingredient: str, cooker: str) -> Optional[Recipe]:
        """找到需要指定食材和cooker的recipe。"""
        for recipe in self.ordered_recipes:
            if ingredient in recipe.raw_ingredients:
                idx = recipe.raw_ingredients.index(ingredient)
                if recipe.cookers[idx] == cooker:
                    return recipe
        return None

    async def _cook_and_update_stock(self, recipe: Recipe, ingredient_name: str, destination: Tuple[int, int]):
        """烹饪单个食材并更新库存。"""
        try:
            await self.cooking_service.prepare_ingredients(
                recipe, destination, ingredient_name_to_cook=ingredient_name, is_order_cooking=False
            )
            async with self._ingredient_stock_lock:
                self.ingredient_stock_counts[ingredient_name] += 1
            logger.info(f"Successfully stockpiled {ingredient_name}")
        except Exception as e:
            logger.error(f"Failed to stockpile {ingredient_name}: {e}")
            raise

    async def _check_idle_state(self):
        """检查idle状态，可以在此处理一些定期任务。"""
        # 可以在此添加一些定期检查逻辑
        pass

    # 公共API：用于发送事件
    async def notify_cooker_available(self, cookers: List[str]):
        """通知有cooker可用。"""
        await self._event_queue.put({
            "type": "cooker_available",
            "cookers": cookers
        })

    async def notify_order_status_changed(self, order: Order, status: str):
        """通知订单状态变化。"""
        await self._event_queue.put({
            "type": "order_status_changed",
            "order": order,
            "status": status
        })

    async def notify_assembly_station_available(self):
        """通知组装台可用。"""
        await self._event_queue.put({
            "type": "assembly_station_available"
        })

    async def notify_assembly_station_occupied(self):
        """通知组装台被占用。"""
        await self._event_queue.put({
            "type": "assembly_station_occupied"
        })
