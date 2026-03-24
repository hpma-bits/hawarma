"""
Mock 模块

地位：提供测试所需的 Mock 实现，模拟 UI 操作和订单检测

输入：测试配置
输出：Mock 对象

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新
"""

from tests.mocks.mock_detection_service import MockDetectionService, ScheduledOrder
from tests.mocks.mock_ui_manager import MockUIOperationManager, UIOperation

__all__ = [
    "MockDetectionService",
    "MockUIOperationManager",
    "ScheduledOrder",
    "UIOperation",
]
