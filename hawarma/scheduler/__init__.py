"""
Scheduler Package

地位：包含游戏的唯一决策中心。所有业务策略都在这里，不在服务层。

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from hawarma.scheduler.scheduler import Scheduler
from hawarma.scheduler.order_policy import OrderPolicy
from hawarma.scheduler.stockpile_policy import StockpilePolicy

__all__ = ["Scheduler", "OrderPolicy", "StockpilePolicy"]
