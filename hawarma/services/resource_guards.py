"""
Resource Guards

地位：管理物理资源的并发访问锁，不包含任何业务策略。

输入：资源的请求
输出：锁的获取/释放

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

import asyncio


class ResourceGuards:
    """
    Owns only resource serialization, no policy.
    
    Protects:
    - Cooker locks: one ingredient cooking at a time per cooker
    - Stockpile slot locks: one operation at a time per stockpile slot
    - Assembly lock: assembly station serialization
    
    Note: These are orthogonal to the global UI lock in UIOperationManager.
    - Resource guards: prevent multiple orders from using same physical resource
    - UI lock: ensures UI operations are serialized to the game
    """

    def __init__(
        self,
        cookers: list[str],
        stockpile_slot_count: int,
    ):
        self._cooker_locks: dict[str, asyncio.Lock] = {
            name: asyncio.Lock() for name in cookers
        }
        self._stockpile_locks: dict[int, asyncio.Lock] = {
            i: asyncio.Lock() for i in range(stockpile_slot_count)
        }
        self._assembly_lock = asyncio.Lock()

    async def acquire_cooker(self, cooker_name: str) -> bool:
        """
        Try to acquire a cooker lock.
        Returns True if acquired, False if cooker is busy.
        """
        lock = self._cooker_locks[cooker_name]
        if lock.locked():
            return False
        await lock.acquire()
        return True

    def release_cooker(self, cooker_name: str) -> None:
        """Release a cooker lock. Idempotent."""
        lock = self._cooker_locks.get(cooker_name)
        if lock is None:
            return
        if lock.locked():
            lock.release()

    async def acquire_stockpile_slot(self, slot: int) -> bool:
        """Try to acquire a stockpile slot lock. Returns True if acquired."""
        lock = self._stockpile_locks.get(slot)
        if lock is None:
            return False
        if lock.locked():
            return False
        await lock.acquire()
        return True

    def release_stockpile_slot(self, slot: int) -> None:
        """Release a stockpile slot lock. Idempotent."""
        lock = self._stockpile_locks.get(slot)
        if lock is None:
            return
        if lock.locked():
            lock.release()

    async def acquire_assembly(self) -> bool:
        """Try to acquire assembly lock. Returns True if acquired."""
        if self._assembly_lock.locked():
            return False
        await self._assembly_lock.acquire()
        return True

    def release_assembly(self) -> None:
        """Release assembly lock. Idempotent."""
        if self._assembly_lock.locked():
            self._assembly_lock.release()
