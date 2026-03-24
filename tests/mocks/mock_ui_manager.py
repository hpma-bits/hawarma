"""
Mock UI Operation Manager

地位：模拟 UI 操作，记录所有操作日志，用于测试 Scheduler-Executor 流程

输入：模拟的坐标和操作参数
输出：操作记录、模拟的执行延迟

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UIOperation:
    """记录单次 UI 操作"""

    type: str  # "swipe", "click", "wait"
    start: tuple[int, int] | None = None
    end: tuple[int, int] | None = None
    duration: float = 0.0
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        if self.type == "swipe":
            return f"Swipe({self.start} -> {self.end}, {self.duration:.2f}s)"
        elif self.type == "click":
            return f"Click({self.start})"
        else:
            return f"Wait({self.duration:.2f}s)"


class MockUIOperationManager:
    """
    模拟 UI 操作管理器。

    设计原则：
    1. 记录所有 UI 操作到日志列表
    2. 可选模拟操作延迟（模拟真实 UI 响应）
    3. 不执行真实 UI 操作
    4. 支持操作统计和回放验证
    """

    def __init__(
        self,
        simulate_delay: bool = True,
        swipe_delay: float = 0.05,
        click_delay: float = 0.02,
    ):
        """
        Args:
            simulate_delay: 是否模拟操作延迟
            swipe_delay: swipe 操作的模拟耗时（秒）
            click_delay: click 操作的模拟耗时（秒）
        """
        self.simulate_delay = simulate_delay
        self.swipe_delay = swipe_delay
        self.click_delay = click_delay

        self.operations: list[UIOperation] = []
        self._start_time: float | None = None

    def reset(self) -> None:
        """重置操作记录"""
        self.operations.clear()
        self._start_time = None

    def _get_relative_time(self) -> float:
        """获取相对于开始时间的当前时间"""
        now = asyncio.get_event_loop().time()
        if self._start_time is None:
            self._start_time = now
            return 0.0
        return now - self._start_time

    async def swipe(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        duration: float = 0.1,
    ) -> None:
        """
        模拟滑动操作。

        Args:
            start: 起始坐标
            end: 结束坐标
            duration: 滑动持续时间
        """
        op = UIOperation(
            type="swipe",
            start=start,
            end=end,
            duration=duration,
            timestamp=self._get_relative_time(),
        )
        self.operations.append(op)

        if self.simulate_delay:
            await asyncio.sleep(self.swipe_delay)

    async def click(self, pos: tuple[int, int]) -> None:
        """
        模拟点击操作。

        Args:
            pos: 点击坐标
        """
        op = UIOperation(
            type="click",
            start=pos,
            timestamp=self._get_relative_time(),
        )
        self.operations.append(op)

        if self.simulate_delay:
            await asyncio.sleep(self.click_delay)

    async def wait(self, seconds: float) -> None:
        """
        模拟等待操作。

        Args:
            seconds: 等待秒数
        """
        op = UIOperation(
            type="wait",
            duration=seconds,
            timestamp=self._get_relative_time(),
        )
        self.operations.append(op)

        if self.simulate_delay:
            await asyncio.sleep(seconds)

    def get_operations_by_type(self, op_type: str) -> list[UIOperation]:
        """获取指定类型的所有操作"""
        return [op for op in self.operations if op.type == op_type]

    def get_swipe_count(self) -> int:
        """获取 swipe 操作总数"""
        return len(self.get_operations_by_type("swipe"))

    def get_total_duration(self) -> float:
        """获取所有操作的总模拟耗时"""
        if not self.operations:
            return 0.0
        return self.operations[-1].timestamp - self.operations[0].timestamp

    def get_operation_timeline(self) -> str:
        """获取操作时间线的可读字符串"""
        lines = []
        for op in self.operations:
            lines.append(f"[{op.timestamp:6.2f}s] {op}")
        return "\n".join(lines)

    async def execute(self, operation: str, *args, **kwargs) -> None:
        """
        执行通用UI操作（兼容 UIOperationManager 接口）

        Args:
            operation: 操作类型
            *args, **kwargs: 操作参数
        """
        if operation == "swipe":
            await self.swipe(args[0], args[1], duration=kwargs.get("duration", 0.1))
        elif operation == "click":
            await self.click(args[0])

    def __repr__(self) -> str:
        return f"MockUI(operations={len(self.operations)}, simulate_delay={self.simulate_delay})"
