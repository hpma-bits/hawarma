"""
Playground 策略模块

Strategy（决策脑）定义与实现

可用策略：
- DefaultStrategy: 默认策略（主动预烹饪 + 决策优先级优化）
- CookingFirstV2Strategy: 旧版策略（Cooking First v2）
- StockpileFirstStrategy: 库存优先策略变体（基于CookingFirstV2Strategy）
"""

from playground.strategies.default import DefaultStrategy
from playground.strategies.cooking_first_v2 import CookingFirstV2Strategy
from playground.strategies.stockpile_first import StockpileFirstStrategy

__all__ = ["DefaultStrategy", "CookingFirstV2Strategy", "StockpileFirstStrategy"]