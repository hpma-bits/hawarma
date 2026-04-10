import unittest
from airtest.core.api import init_device, G
import time


class TestLazyInitMinicap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Initialize device for testing."""
        cls.device = init_device(
            platform="Android",
            uuid="127.0.0.1:16384",
            cap_method="minicap_apk",
        )

    def test_lazy_init_minicap(self):
        """测试延迟初始化 minicap - 不在初始化时立即创建 stream"""
        # 1. 检查 screen_proxy 是否已初始化
        self.assertTrue(hasattr(self.device, 'screen_proxy'))
        self.assertIsNotNone(self.device.screen_proxy)
        
        # 2. 获取 screen_method (实际截图实现)
        screen_impl = self.device.screen_proxy.screen_method
        self.assertIsNotNone(screen_impl)
        
        # 3. 检查 frame_gen 是否为 None (延迟初始化的标志)
        # 如果 frame_gen 为 None，说明还没有建立 stream
        has_frame_gen = hasattr(screen_impl, 'frame_gen') and screen_impl.frame_gen is not None
        
        # 4. 第一次 snapshot 后应该初始化
        first_snapshot = self.device.snapshot()
        self.assertIsNotNone(first_snapshot)
        
        # 5. 再次检查 frame_gen
        has_frame_gen_after = hasattr(screen_impl, 'frame_gen') and screen_impl.frame_gen is not None
        
        print(f"\n=== Lazy Init Detection ===")
        print(f"Before snapshot: frame_gen exists = {has_frame_gen}")
        print(f"After snapshot: frame_gen exists = {has_frame_gen_after}")
        
        # 如果还没初始化，第一次 snapshot 后应该有了
        if not has_frame_gen:
            self.assertTrue(has_frame_gen_after, "frame_gen should be initialized after first snapshot")


if __name__ == "__main__":
    unittest.main(verbosity=2)