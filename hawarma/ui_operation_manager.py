"""
UI操作管理器

地位：统一管理所有UI操作，确保同一时刻只有1个UI操作发送到游戏

输入：UI操作请求（swipe/click）
输出：UI操作结果

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

import asyncio

from airtest.core.api import swipe
from loguru import logger


class UIOperationManager:
    """
    统一管理所有UI操作，确保同一时刻只有1个UI操作发送到游戏

    职责：
    1. 全局UI锁 - 序列化所有swipe/click操作
    2. 操作日志 - 记录所有UI操作便于调试

    注意：此锁与资源锁（cooker_locks, assembly_lock等）是正交的
    - 资源锁：防止多个订单占用同一游戏资源
    - UI操作锁：确保UI操作串行发送到游戏
    两者可以共存，执行顺序：先获取资源锁，再获取UI锁
    """

    def __init__(self):
        self._global_ui_lock = asyncio.Lock()

    async def swipe(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        duration: float = 0.1,
    ) -> None:
        """
        执行swipe操作

        Args:
            start: 起始位置 (x, y)
            end: 结束位置 (x, y)
            duration: 滑动持续时间（秒）
        """
        async with self._global_ui_lock:
            logger.debug(f"UI swipe: {start} -> {end}, duration={duration}")
            swipe(start, end, duration=duration)
            await asyncio.sleep(0.1)

    async def execute(self, operation: str, *args, **kwargs) -> None:
        """
        执行通用UI操作

        Args:
            operation: 操作类型
            *args, **kwargs: 操作参数
        """
        async with self._global_ui_lock:
            logger.debug(f"UI operation: {operation}")
            if operation == "swipe":
                swipe(args[0], args[1], duration=kwargs.get("duration", 0.1))
            await asyncio.sleep(0.1)
