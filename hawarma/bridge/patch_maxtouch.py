"""
Maxtouch Monkey Patch

在 UpEvent 前添加停留时间，确保滑动到位。

一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from airtest.core.android.touch_methods.base_touch import BaseTouch, DownEvent, MoveEvent, SleepEvent, UpEvent


def patched_swipe(self, tuple_from_xy, tuple_to_xy, duration=0.8, steps=5):
    """
    Patch BaseTouch.swipe，在 UpEvent 前添加停留时间

    Args:
        tuple_from_xy: 起始坐标
        tuple_to_xy: 结束坐标
        duration: 滑动持续时间
        steps: 滑动步数
    """
    swipe_events = [DownEvent(tuple_from_xy), SleepEvent(0.1)]
    swipe_events += self._BaseTouch__swipe_move(tuple_from_xy, tuple_to_xy, duration, steps)
    swipe_events.append(SleepEvent(0.1))
    swipe_events.append(UpEvent())
    self.perform(swipe_events)


def apply_patch():
    """应用 patch"""
    BaseTouch.swipe = patched_swipe