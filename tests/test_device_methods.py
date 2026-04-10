import unittest
from airtest.core.api import init_device, G


class TestDeviceMethods(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Initialize device for testing."""
        cls.device = init_device(
            platform="Android",
            uuid="127.0.0.1:16384",
            cap_method="minicap_apk",
        )

    def test_screenshot_method(self):
        """测试截图方法检测 - 使用 MinicapApk"""
        screen_impl = self.device.screen_proxy.screen_method
        actual_class = type(screen_impl).__name__
        
        self.assertIn(actual_class, ['Minicap', 'MinicapApk', 'Javacap', 'AdbCap'])
        self.assertEqual(actual_class, 'MinicapApk')

    def test_touch_method(self):
        """测试触控方法检测 - 使用 Maxtouch (Android 10+)"""
        touch_proxy = self.device.touch_proxy
        touch_impl = touch_proxy.touch_method
        impl_class = type(touch_impl).__name__
        
        base = touch_impl.base_touch
        base_class = type(base).__name__
        
        self.assertIn(base_class, ['Minitouch', 'Maxtouch'])
        self.assertEqual(base_class, 'Maxtouch')


if __name__ == "__main__":
    unittest.main()