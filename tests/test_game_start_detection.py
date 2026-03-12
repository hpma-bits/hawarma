"""
游戏开始检测测试模块

地位：测试通过左上角计时器图标识别来判断游戏是否开始

输入：测试集图片、icon-timer.jpg模板
输出：测试结果，报告匹配成功/失败及位置

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

import unittest
from pathlib import Path

import cv2
import numpy as np


class TestGameStartDetection(unittest.TestCase):
    """测试游戏开始检测功能，通过左上角计时器图标识别。"""

    @classmethod
    def setUpClass(cls):
        """加载测试所需的图片和模板。"""
        # 项目根目录
        cls.project_root = Path(__file__).parent.parent
        
        # 静态图片目录
        cls.static_img_dir = cls.project_root / "static" / "img"
        
        # 测试集目录
        cls.testset_dir = cls.project_root / "tests" / "testset"
        
        # 计时器图标模板路径
        cls.timer_icon_path = cls.static_img_dir / "icon-timer.jpg"
        
        # 验证模板文件存在
        if not cls.timer_icon_path.exists():
            raise FileNotFoundError(f"计时器图标模板未找到: {cls.timer_icon_path}")
        
        # 使用OpenCV加载模板图片
        cls.timer_template = cv2.imread(str(cls.timer_icon_path))
        if cls.timer_template is None:
            raise ValueError(f"无法加载计时器图标模板: {cls.timer_icon_path}")
        
        print(f"\n成功加载计时器图标模板: {cls.timer_icon_path}")
        print(f"模板尺寸: {cls.timer_template.shape}")

    def _load_test_image(self, image_name: str) -> np.ndarray:
        """加载测试集图片。"""
        image_path = self.testset_dir / image_name
        if not image_path.exists():
            raise FileNotFoundError(f"测试图片未找到: {image_path}")
        
        # 使用cv2加载图片
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError(f"无法加载图片: {image_path}")
        
        return image

    def _detect_game_start(
        self, 
        screen: np.ndarray, 
        search_region: tuple = (0, 0, 200, 150),
        threshold: float = 0.7
    ) -> dict:
        """
        检测游戏是否开始，通过在指定区域搜索计时器图标。
        
        使用OpenCV的模板匹配功能，在指定的搜索区域内查找计时器图标。
        
        Args:
            screen: 屏幕截图 (BGR格式的numpy数组)
            search_region: 搜索区域 (x1, y1, x2, y2)，默认左上角200x150区域
            threshold: 匹配阈值，超过此值认为匹配成功 (0-1)
        
        Returns:
            dict: {
                'detected': bool,      # 是否检测到
                'position': tuple | None,  # 匹配位置 (x, y)
                'confidence': float,    # 置信度 (0-1)
                'search_region': tuple  # 搜索区域
            }
        """
        result = {
            'detected': False,
            'position': None,
            'confidence': 0.0,
            'search_region': search_region
        }
        
        try:
            # 提取搜索区域
            x1, y1, x2, y2 = search_region
            search_area = screen[y1:y2, x1:x2]
            
            # 确保搜索区域和模板都有有效尺寸
            if search_area.size == 0 or self.timer_template.size == 0:
                print("警告: 搜索区域或模板尺寸无效")
                return result
            
            # 使用OpenCV进行模板匹配
            # cv2.TM_CCOEFF_NORMED 返回归一化的相关系数 (0-1)
            match_result = cv2.matchTemplate(
                search_area, 
                self.timer_template, 
                cv2.TM_CCOEFF_NORMED
            )
            
            # 获取最大匹配值及其位置
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(match_result)
            
            # 更新结果
            result['confidence'] = float(max_val)
            
            # 如果匹配值超过阈值，认为匹配成功
            if max_val >= threshold:
                result['detected'] = True
                # 计算在原图中的绝对位置
                result['position'] = (
                    x1 + max_loc[0] + self.timer_template.shape[1] // 2,
                    y1 + max_loc[1] + self.timer_template.shape[0] // 2
                )
                
        except Exception as e:
            print(f"检测过程中出现错误: {e}")
            import traceback
            traceback.print_exc()
        
        return result

    def test_game_start_detection_with_testset(self):
        """
        使用testset中的图片测试游戏开始检测功能。
        
        测试流程：
        1. 加载testset目录下的测试图片
        2. 在每张图片的左上角区域搜索计时器图标
        3. 使用OpenCV模板匹配算法进行检测
        4. 记录匹配结果和置信度
        5. 统计成功/失败率
        
        期望结果：
        - 至少有一张图片成功检测到计时器图标
        - 匹配置信度应超过设定的阈值(默认0.7)
        """
        # 获取测试集中的所有jpg图片
        test_images = sorted([f.name for f in self.testset_dir.glob("*.jpg")])
        
        if not test_images:
            self.fail("测试集中没有找到任何jpg图片")
        
        print(f"\n{'='*60}")
        print(f"开始测试游戏开始检测功能")
        print(f"{'='*60}")
        print(f"找到 {len(test_images)} 张测试图片")
        print(f"计时器图标模板: {self.timer_icon_path}")
        print(f"模板尺寸: {self.timer_template.shape}")
        print(f"搜索区域: 左上角 (0,0) 到 (200,150)")
        print(f"匹配阈值: 0.7")
        print(f"{'='*60}\n")
        
        # 统计结果
        success_count = 0
        fail_count = 0
        results_details = []
        
        # 测试前5张图片（避免测试时间太长）
        test_samples = test_images[:5]
        
        for idx, image_name in enumerate(test_samples, 1):
            print(f"\n[{idx}/{len(test_samples)}] 测试图片: {image_name}")
            print("-" * 60)
            
            try:
                # 加载测试图片
                screen = self._load_test_image(image_name)
                print(f"  图片尺寸: {screen.shape}")
                
                # 检测游戏开始（搜索左上角区域）
                result = self._detect_game_start(
                    screen=screen,
                    search_region=(0, 0, 200, 150),  # 左上角200x150区域
                    threshold=0.7
                )
                
                # 记录详细结果
                result_detail = {
                    'image': image_name,
                    'detected': result['detected'],
                    'confidence': result['confidence'],
                    'position': result['position']
                }
                results_details.append(result_detail)
                
                # 输出结果
                if result['detected']:
                    success_count += 1
                    print(f"  ✓ 检测到计时器图标!")
                    print(f"    位置: {result['position']}")
                    print(f"    置信度: {result['confidence']:.3f}")
                else:
                    fail_count += 1
                    print(f"  ✗ 未检测到计时器图标")
                    print(f"    最高置信度: {result['confidence']:.3f}")
                
            except Exception as e:
                fail_count += 1
                print(f"  ✗ 测试失败: {str(e)}")
                import traceback
                traceback.print_exc()
        
        # 打印详细统计结果
        print("\n" + "="*60)
        print("测试完成 - 详细报告")
        print("="*60)
        print(f"测试图片总数: {len(test_samples)}")
        print(f"成功检测到计时器: {success_count} 张")
        print(f"未检测到计时器: {fail_count} 张")
        print(f"成功率: {success_count/len(test_samples)*100:.1f}%")
        print("\n详细结果:")
        for detail in results_details:
            status = "✓" if detail['detected'] else "✗"
            print(f"  {status} {detail['image']}: 置信度={detail['confidence']:.3f}")
        print("="*60)
        
        # 断言：确保至少有一张图片成功检测到计时器图标
        self.assertGreater(
            success_count, 
            0, 
            f"在 {len(test_samples)} 张测试图片中，没有一张成功检测到计时器图标。"
            f"请检查：\n"
            f"1. 模板图片 (static/img/icon-timer.jpg) 是否正确\n"
            f"2. 搜索区域设置 (0,0)-(200,150) 是否合适\n"
            f"3. 匹配阈值 (0.7) 是否过高"
        )

    def test_timer_template_loading(self):
        """测试计时器图标模板是否正确加载。"""
        print("\n" + "="*60)
        print("测试计时器图标模板加载")
        print("="*60)
        
        # 验证模板文件存在
        self.assertTrue(
            self.timer_icon_path.exists(),
            f"计时器图标模板文件不存在: {self.timer_icon_path}"
        )
        print(f"✓ 模板文件存在: {self.timer_icon_path}")
        
        # 验证模板成功加载为numpy数组
        self.assertIsNotNone(self.timer_template)
        print(f"✓ 模板成功加载为numpy数组")
        
        # 验证模板尺寸合理
        self.assertEqual(len(self.timer_template.shape), 3)
        height, width, channels = self.timer_template.shape
        print(f"✓ 模板尺寸: {width}x{height} 像素, {channels} 通道")
        
        # 验证模板不是空图
        non_zero_pixels = np.count_nonzero(self.timer_template)
        self.assertGreater(non_zero_pixels, 0, "模板图片是全黑的")
        print(f"✓ 模板包含 {non_zero_pixels} 个非零像素")
        
        print("="*60)
        print("计时器图标模板加载测试通过!")
        print("="*60)


if __name__ == "__main__":
    # 运行测试
    unittest.main(verbosity=2)
