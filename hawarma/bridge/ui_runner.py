"""
UI 操作执行器

地位：封装所有 swipe 操作，提供坐标映射和异步执行
      从 config.yaml 读取坐标配置
      根据菜谱选择顺序动态确定元素坐标

输入：符号化操作（食材名、灶台名等）
输出：swipe 操作执行结果

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

import asyncio
from typing import Optional

from airtest.core.api import swipe
from loguru import logger

from hawarma.config import AppConfig
from hawarma.models import Recipe


class UIRunner:
    """
    UI 操作执行器
    
    将符号化操作转换为屏幕坐标，并执行 swipe 操作。
    """
    
    def __init__(self, config: AppConfig, recipes: list[Recipe]):
        """
        初始化 UIRunner
        
        Args:
            config: 应用配置
            recipes: 选中的配方列表（用于确定食材位置）
        """
        self.config = config
        self.recipes = recipes
        
        # 坐标映射
        self._ingredient_positions: dict[str, tuple[int, int]] = {}
        self._cooker_positions: dict[str, tuple[int, int]] = {}
        self._condiment_positions: dict[str, tuple[int, int]] = {}
        self._stockpile_positions: dict[str, tuple[int, int]] = {}
        self._assembly_position: tuple[int, int] = tuple(config.screen.assembly_station_position)
        self._pickup_positions: list[tuple[int, int]] = [
            tuple(pos) for pos in config.screen.pickup_stations_positions
        ]
        
        # 异步锁
        self._lock = asyncio.Lock()
        
        # 构建坐标映射
        self._build_mappings()
        
        logger.info(f"UIRunner initialized with {len(self._ingredient_positions)} ingredients")
    
    def _build_mappings(self) -> None:
        """
        构建坐标映射
        
        根据菜谱选择顺序动态确定各元素位置：
        1. Cookers: 按cookers_layout去重，根据种类数量选择槽位
        2. Ingredients: 按raw_ingredients去重，反转顺序后分配索引
        3. Condiments: 按condiments去重，顺序分配索引
        """
        # 收集所有食材（按选中配方的顺序）
        all_ingredients = []
        for recipe in self.recipes:
            for ing in recipe.raw_ingredients:
                if ing not in all_ingredients:
                    all_ingredients.append(ing)
        
        # 食材位置：反转顺序后分配索引（从下到上、从左到右）
        positions = self.config.screen.raw_ingredients_positions
        reversed_ingredients = list(reversed(all_ingredients))
        for i, ing in enumerate(reversed_ingredients):
            if i < len(positions):
                self._ingredient_positions[ing] = tuple(positions[i])
        
        # 收集所有cooker（按选中配方的cookers_layout顺序）
        all_cookers = []
        for recipe in self.recipes:
            for cooker in recipe.cookers_layout:
                if cooker not in all_cookers:
                    all_cookers.append(cooker)
        
        # 灶台位置：根据种类数量选择槽位
        # 1种→[1]，2种→[1,2]，3种→[0,1,2]，4种→[0,1,2,3]
        cooker_positions = self.config.screen.cookers_positions
        num_cookers = len(all_cookers)
        
        if num_cookers == 1:
            slot_indices = [1]
        elif num_cookers == 2:
            slot_indices = [1, 2]
        elif num_cookers == 3:
            slot_indices = [0, 1, 2]
        else:  # 4 or more
            slot_indices = [0, 1, 2, 3]
        
        for i, cooker in enumerate(all_cookers):
            if i < len(slot_indices):
                slot_idx = slot_indices[i]
                if slot_idx < len(cooker_positions):
                    self._cooker_positions[cooker] = tuple(cooker_positions[slot_idx])
        
        # 收集所有condiment（按选中配方的顺序）
        all_condiments = []
        for recipe in self.recipes:
            for cond in recipe.condiments:
                if cond not in all_condiments:
                    all_condiments.append(cond)
        
        # 调料位置：顺序分配索引（从下到上、从左到右）
        condiment_positions = self.config.screen.condiments_positions
        for i, cond in enumerate(all_condiments):
            if i < len(condiment_positions):
                self._condiment_positions[cond] = tuple(condiment_positions[i])
        
        # 库存位置
        stockpile_positions = self.config.screen.stockpile_positions
        for i, pos in enumerate(stockpile_positions):
            self._stockpile_positions[f"slot{i}"] = tuple(pos)
    
    # ========================================================================
    # 核心操作
    # ========================================================================
    
    async def swipe(self, start: tuple[int, int], end: tuple[int, int], duration: float = 0.1) -> None:
        """
        执行 swipe 操作
        
        Args:
            start: 起始坐标
            end: 结束坐标
            duration: 持续时间（默认0.1秒）
        """
        async with self._lock:
            logger.debug(f"Swipe: {start} -> {end}")
            # 直接调用 swipe，不使用 to_thread 以避免线程切换开销
            swipe(start, end, duration)
            # 短暂等待，确保操作完全完成
            await asyncio.sleep(0.05)
    
    async def cook(self, ingredient: str, cooker: str) -> None:
        """
        烹饪食材
        
        Args:
            ingredient: 食材名称
            cooker: 灶台名称
        """
        ing_pos = self._get_ingredient_position(ingredient)
        cooker_pos = self._get_cooker_position(cooker)
        
        await self.swipe(ing_pos, cooker_pos)
        logger.debug(f"Cooking {ingredient} on {cooker}")
    
    async def move_to_assembly(self, cooker: str) -> None:
        """
        将灶台食材移动到组装站
        
        Args:
            cooker: 灶台名称
        """
        cooker_pos = self._get_cooker_position(cooker)
        await self.swipe(cooker_pos, self._assembly_position)
        logger.debug(f"Moved from {cooker} to assembly")
    
    async def move_to_stockpile(self, cooker: str, slot: str) -> None:
        """
        将灶台食材移动到库存
        
        Args:
            cooker: 灶台名称
            slot: 库存槽位名称
        """
        cooker_pos = self._get_cooker_position(cooker)
        stockpile_pos = self._get_stockpile_position(slot)
        await self.swipe(cooker_pos, stockpile_pos)
        logger.debug(f"Moved from {cooker} to {slot}")
    
    async def pull_from_stockpile(self, slot: str) -> None:
        """
        从库存取用食材到组装站
        
        Args:
            slot: 库存槽位名称
        """
        stockpile_pos = self._get_stockpile_position(slot)
        await self.swipe(stockpile_pos, self._assembly_position)
        logger.debug(f"Pulled from {slot} to assembly")
    
    async def add_condiment(self, condiment: str) -> None:
        """
        添加调料到组装站
        
        Args:
            condiment: 调料名称
        """
        condiment_pos = self._get_condiment_position(condiment)
        await self.swipe(condiment_pos, self._assembly_position)
        logger.debug(f"Added condiment {condiment}")
    
    async def serve_order(self, slot_idx: int) -> None:
        """
        送餐
        
        Args:
            slot_idx: 订单槽位索引
        """
        pickup_pos = self._pickup_positions[slot_idx]
        await self.swipe(self._assembly_position, pickup_pos)
        logger.debug(f"Served order to slot {slot_idx}")
    
    async def clear_cooker(self, cooker: str) -> None:
        """
        清理灶台（丢弃过期食材）
        
        Args:
            cooker: 灶台名称
        """
        cooker_pos = self._get_cooker_position(cooker)
        # 丢弃到屏幕外（假设右下角是垃圾桶）
        trash_pos = (1800, 1000)
        await self.swipe(cooker_pos, trash_pos)
        logger.debug(f"Cleared cooker {cooker}")
    
    # ========================================================================
    # 坐标查询
    # ========================================================================
    
    def _get_ingredient_position(self, ingredient: str) -> tuple[int, int]:
        """获取食材位置"""
        if ingredient in self._ingredient_positions:
            return self._ingredient_positions[ingredient]
        raise ValueError(f"Unknown ingredient: {ingredient}")
    
    def _get_cooker_position(self, cooker: str) -> tuple[int, int]:
        """获取灶台位置"""
        if cooker in self._cooker_positions:
            return self._cooker_positions[cooker]
        raise ValueError(f"Unknown cooker: {cooker}")
    
    def _get_condiment_position(self, condiment: str) -> tuple[int, int]:
        """获取调料位置"""
        if condiment in self._condiment_positions:
            return self._condiment_positions[condiment]
        # 默认使用配置中的位置
        positions = self.config.screen.condiments_positions
        # 根据调料名称计算索引（简单hash）
        idx = hash(condiment) % len(positions)
        return tuple(positions[idx])
    
    def _get_stockpile_position(self, slot: str) -> tuple[int, int]:
        """获取库存位置"""
        if slot in self._stockpile_positions:
            return self._stockpile_positions[slot]
        raise ValueError(f"Unknown stockpile slot: {slot}")
    
    # ========================================================================
    # 调试
    # ========================================================================
    
    def get_mappings(self) -> dict:
        """获取坐标映射（用于调试）"""
        return {
            "ingredients": self._ingredient_positions,
            "cookers": self._cooker_positions,
            "condiments": self._condiment_positions,
            "stockpile": self._stockpile_positions,
            "assembly": self._assembly_position,
            "pickups": self._pickup_positions,
        }
