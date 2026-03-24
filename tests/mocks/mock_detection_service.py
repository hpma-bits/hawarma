"""
Mock Detection Service

地位：模拟订单检测，预定义订单队列，模拟订单出现时机

输入：订单调度计划
输出：检测到的订单

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新
"""

from dataclasses import dataclass

from hawarma.models import Order


@dataclass
class ScheduledOrder:
    """
    订单出现计划。

    Attributes:
        slot_idx: 订单槽位索引 (0-3)
        order: 订单对象
        appear_at: 相对于游戏开始的出现时间（秒）
    """

    slot_idx: int
    order: Order
    appear_at: float


@dataclass
class DetectionEvent:
    """记录一次检测事件"""

    slot_idx: int
    order: Order | None
    timestamp: float
    detected: bool


class MockDetectionService:
    """
    模拟订单检测服务。

    设计原则：
    1. 按预定义时间表返回订单
    2. 模拟检测延迟
    3. 支持动态添加订单（模拟游戏中的新订单）
    4. 记录所有检测事件
    """

    def __init__(
        self,
        schedule: list[ScheduledOrder] | None = None,
        detection_delay: float = 0.05,
    ):
        """
        Args:
            schedule: 订单出现时间表
            detection_delay: 模拟检测耗时（秒）
        """
        self.schedule: list[ScheduledOrder] = list(schedule or [])
        self.detection_delay = detection_delay

        self.detection_history: list[DetectionEvent] = []
        self._detected_slots: set[int] = set()  # 已检测到的槽位
        self._current_time: float = 0.0

    def reset(self) -> None:
        """重置检测状态"""
        self.detection_history.clear()
        self._detected_slots.clear()
        self._current_time = 0.0

    def set_time(self, time: float) -> None:
        """设置当前时间"""
        self._current_time = time

    def add_scheduled_order(self, scheduled: ScheduledOrder) -> None:
        """动态添加订单到调度表"""
        self.schedule.append(scheduled)

    def detect_order(self, slot_idx: int) -> Order | None:
        """
        检测指定槽位的订单。

        Args:
            slot_idx: 槽位索引

        Returns:
            检测到的订单，如果没有则返回 None
        """
        # 查找在当前时间应该出现的订单
        for scheduled in self.schedule:
            if (
                scheduled.slot_idx == slot_idx
                and scheduled.appear_at <= self._current_time
                and slot_idx not in self._detected_slots
            ):
                self._detected_slots.add(slot_idx)
                event = DetectionEvent(
                    slot_idx=slot_idx,
                    order=scheduled.order,
                    timestamp=self._current_time,
                    detected=True,
                )
                self.detection_history.append(event)
                return scheduled.order

        # 记录未检测到的事件
        event = DetectionEvent(
            slot_idx=slot_idx,
            order=None,
            timestamp=self._current_time,
            detected=False,
        )
        self.detection_history.append(event)
        return None

    def get_pending_orders(self) -> list[ScheduledOrder]:
        """获取尚未检测到的待出现订单"""
        return [
            s
            for s in self.schedule
            if s.slot_idx not in self._detected_slots
            and s.appear_at > self._current_time
        ]

    def get_all_scheduled_orders(self) -> list[ScheduledOrder]:
        """获取所有调度的订单"""
        return list(self.schedule)

    def get_detection_count(self) -> int:
        """获取成功检测的次数"""
        return len([e for e in self.detection_history if e.detected])

    def get_detection_timeline(self) -> str:
        """获取检测时间线的可读字符串"""
        lines = []
        for event in self.detection_history:
            if event.detected:
                rush_tag = " [RUSH]" if event.order.is_rush else ""
                lines.append(
                    f"[{event.timestamp:6.2f}s] Detected order #{event.order.order_id} "
                    f"in slot {event.slot_idx}{rush_tag}"
                )
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"MockDetection(schedule={len(self.schedule)}, "
            f"detected={len(self._detected_slots)})"
        )
