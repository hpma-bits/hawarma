import unittest
import asyncio
import time
from airtest.core.api import init_device, touch
from airtest.core.settings import Settings as ST
from loguru import logger

from hawarma.config import load_config
from hawarma.services.recipe_manager import RecipeManager
from hawarma.bridge.scanner import OrderScanner


class TestTimerDetectionLatency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """初始化设备 - 与 main.py 相同"""
        ST.CVSTRATEGY = ["tpl"]
        ST.OPDELAY = 0.05
        ST.THRESHOLD = 0.7
        
        logger.info("Initializing device...")
        cls.device = init_device(
            platform="Android",
            uuid="127.0.0.1:16384",
            cap_method="minicap_apk",
        )
        touch((0, 0))
        
        # 打印截图方法
        if hasattr(cls.device, 'screen_proxy') and cls.device.screen_proxy:
            screen_class = type(cls.device.screen_proxy.screen_method).__name__
            logger.info(f"Screenshot method: {screen_class}")
        
        # 加载配置和配方
        cls.config = load_config()
        recipe_manager = RecipeManager(recipes_path="data/recipes.json")
        all_recipes = recipe_manager.get_all_recipes()
        selected_recipes = all_recipes[:6]
        
        # 初始化 scanner（不预热 - 延迟初始化）
        logger.info("Initializing OrderScanner (lazy init)...")
        cls.scanner = OrderScanner(cls.config, selected_recipes)
        
        # 预热 stream（在通知用户显示图片之前）
        logger.info("Prewarming stream before test...")
        prewarm_start = time.time()
        cls.scanner.prewarm()
        prewarm_duration = time.time() - prewarm_start
        logger.info(f"Prewarm completed in {prewarm_duration:.3f}s")
        
    def test_timer_detection_latency(self):
        """测试 timer 检测延迟"""
        print("\n" + "=" * 60)
        print("=== Timer Detection Latency Test ===")
        print("=" * 60)
        print("请在显示 timer 图标后按回车键开始检测...")
        input("按回车键继续...")
        print("=" * 60)
        
        start_time = time.time()
        attempt = 0
        max_attempts = 20  # 约 10 秒超时 (0.5s 间隔)
        detected = False
        
        while attempt < max_attempts:
            attempt += 1
            loop_start = time.time()
            
            # 检测 timer
            detected = asyncio.run(self.scanner.detect_timer())
            
            loop_duration = time.time() - loop_start
            total_duration = time.time() - start_time
            
            status = "DETECTED" if detected else "..."
            print(f"Attempt {attempt:2d}: {loop_duration:.3f}s (total: {total_duration:.3f}s) [{status}]")
            
            if detected:
                print("=" * 60)
                print(f"Timer detected after {attempt} attempts ({total_duration:.3f}s)")
                print("=" * 60)
                break
            
            time.sleep(0.01)  # 短暂休息，避免占用太多 CPU
        
        # 验证结果
        self.assertTrue(detected, f"在 {max_attempts} 次尝试内未检测到 timer")
        
        # 验证是否在 1 秒内检测到
        if total_duration > 1.0:
            print(f"WARNING: 检测延迟 {total_duration:.3f}s 超过 1 秒!")
        else:
            print(f"OK: 检测延迟 {total_duration:.3f}s 在 1 秒以内")


if __name__ == "__main__":
    unittest.main(verbosity=2)