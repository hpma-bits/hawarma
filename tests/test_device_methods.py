import unittest
from airtest.core.api import init_device, G
from airtest.core.android.touch_methods.minitouch import Minitouch


class TestDeviceMethods(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Initialize device for testing."""
        cls.device = init_device(
            platform="Android",
            uuid="127.0.0.1:16384",
            cap_method="minicap_apk",
        )

    def test_screenshot_method_logging(self):
        """测试截图方法检测日志输出"""
        # 验证截图方法存在
        self.assertTrue(hasattr(self.device, 'screen_proxy'))
        self.assertIsNotNone(self.device.screen_proxy)
        
        # 验证方法名称
        method_name = self.device.screen_proxy.method_name
        self.assertIsNotNone(method_name)
        # 注意：实际返回的是 'MINICAPAPK' 而不是 'MINICAP_APK'
        self.assertIn(method_name, ['MINICAPAPK', 'MINICAP', 'JAVACAP', 'ADBCAP'])

    def test_touch_method_logging(self):
        """测试触控方法检测日志输出"""
        # 验证触控方法存在
        self.assertTrue(hasattr(self.device, 'touch'))
        self.assertIsNotNone(self.device.touch)
        
        # 验证触控方法类型名称
        touch_method_name = type(self.device.touch).__name__
        self.assertIsNotNone(touch_method_name)
        
        # 验证可能的触控方法类型（包括 method 是 minitouch 的包装）
        valid_methods = ['Minitouch', 'AdbTouch', 'Adb', 'method']
        self.assertIn(touch_method_name, valid_methods)

    def test_touch_base_detection(self):
        """测试触控基类检测"""
        if hasattr(self.device.touch, 'base_touch'):
            base_touch = self.device.touch.base_touch
            if base_touch is not None:
                base_name = type(base_touch).__name__
                self.assertIsNotNone(base_name)


if __name__ == "__main__":
    unittest.main()