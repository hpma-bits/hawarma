"""
测试 timer icon 模板匹配

地位：验证 icon-timer.jpg 模板在 testset 截图中能否成功匹配
      使用纯 OpenCV 模板匹配，不依赖 airtest

输入：tests/testset/*.jpg 截图、static/img/icon-timer.jpg 模板
输出：每张截图的匹配结果及置信度
"""

import unittest
from pathlib import Path

import cv2
import numpy as np

# timer 检测区域 (x1, y1, x2, y2)，与 config.yaml 一致
TIMER_ROI = (0, 0, 400, 140)


def opencv_template_match(screen: np.ndarray, template: np.ndarray,
                          threshold: float = 0.7) -> dict | None:
    """
    OpenCV 模板匹配，返回最佳匹配结果或 None。

    用 TM_CCOEFF_NORMED，匹配值越高越好。
    """
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

    if max_val >= threshold:
        return {
            "confidence": max_val,
            "x": max_loc[0],
            "y": max_loc[1],
        }
    return None


class TestTimerDetection(unittest.TestCase):
    """timer icon 模板匹配测试"""

    @classmethod
    def setUpClass(cls):
        cls.testset_dir = Path(__file__).parent / "testset"
        cls.template_path = Path("static/img/icon-timer.jpg")
        cls.template = cv2.imread(str(cls.template_path))
        assert cls.template is not None, f"Failed to load {cls.template_path}"

    def _match_timer(self, screen_path: str) -> dict | None:
        """在指定截图的 timer_region 区域内查找 icon-timer 模板"""
        screen = cv2.imread(str(screen_path))
        self.assertIsNotNone(screen, f"Failed to load {screen_path}")

        x1, y1, x2, y2 = TIMER_ROI
        cropped = screen[y1:y2, x1:x2]

        return opencv_template_match(cropped, self.template)

    def test_template_loadable(self):
        """确认模板可以正确加载"""
        self.assertIsNotNone(self.template, "Failed to load icon-timer.jpg")
        h, w = self.template.shape[:2]
        print(f"\nTemplate size: {w}x{h}")

    def test_roi_covers_timer(self):
        """确认 ROI 裁剪区域大小合理"""
        x1, y1, x2, y2 = TIMER_ROI
        self.assertGreater(x2 - x1, 0, "ROI width is 0")
        self.assertGreater(y2 - y1, 0, "ROI height is 0")
        print(f"\nROI: {TIMER_ROI}, size: {x2-x1}x{y2-y1}")

    def test_timer_found_in_order0_0(self):
        """测试 order0-0-01-normal.jpg 中能检测到 timer"""
        result = self._match_timer(self.testset_dir / "order0-0-01-normal.jpg")
        conf = result["confidence"] if result else 0
        print(f"\norder0-0-01-normal: conf={conf:.4f}")
        self.assertIsNotNone(result, "Timer not detected in order0-0-01-normal.jpg")

    def test_timer_found_in_order0_2(self):
        """测试 order0-2-12-rush.jpg 中能检测到 timer"""
        result = self._match_timer(self.testset_dir / "order0-2-12-rush.jpg")
        conf = result["confidence"] if result else 0
        print(f"\norder0-2-12-rush: conf={conf:.4f}")
        self.assertIsNotNone(result, "Timer not detected in order0-2-12-rush.jpg")

    def test_timer_found_in_order1_3(self):
        """测试 order1-3-21-normal.jpg 中能检测到 timer"""
        result = self._match_timer(self.testset_dir / "order1-3-21-normal.jpg")
        conf = result["confidence"] if result else 0
        print(f"\norder1-3-21-normal: conf={conf:.4f}")
        self.assertIsNotNone(result, "Timer not detected in order1-3-21-normal.jpg")

    def test_all_testset_images(self):
        """扫描所有 testset 截图，报告 timer 匹配结果"""
        test_images = sorted(self.testset_dir.glob("*.jpg"))
        self.assertGreater(len(test_images), 0, "No test images found")

        detected = 0
        not_detected = 0
        results = []

        for img_path in test_images:
            result = self._match_timer(str(img_path))
            found = result is not None
            confidence = result["confidence"] if result else 0

            if found:
                detected += 1
            else:
                not_detected += 1

            results.append((img_path.name, found, confidence))

        print(f"\n{'='*60}")
        print(f"Timer Detection Results (ROI={TIMER_ROI}, threshold=0.7)")
        print(f"{'='*60}")
        for name, found, conf in results:
            status = f"FOUND (conf={conf:.4f})" if found else "NOT FOUND"
            print(f"  {name:40s} {status}")
        print(f"{'='*60}")
        print(f"Detected: {detected}/{detected + not_detected}")
        print(f"Not detected: {not_detected}/{detected + not_detected}")

        self.assertGreater(detected, 0, "Timer not detected in ANY testset image!")

    def test_sweep_thresholds(self):
        """扫描不同 threshold 下的检测率，找到最优值"""
        test_images = sorted(self.testset_dir.glob("*.jpg"))

        thresholds = [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9]

        print(f"\n{'='*60}")
        print(f"Threshold sweep on {len(test_images)} images")
        print(f"{'='*60}")

        for thresh in thresholds:
            count = 0
            min_conf = 1.0
            max_conf = 0.0
            for img_path in test_images:
                screen = cv2.imread(str(img_path))
                x1, y1, x2, y2 = TIMER_ROI
                cropped = screen[y1:y2, x1:x2]
                result = opencv_template_match(cropped, self.template, threshold=thresh)
                if result:
                    count += 1
                    min_conf = min(min_conf, result["confidence"])
                    max_conf = max(max_conf, result["confidence"])

            if count > 0:
                print(f"  threshold={thresh:.2f}: {count}/{len(test_images)} detected, "
                      f"conf range=[{min_conf:.4f}, {max_conf:.4f}]")
            else:
                print(f"  threshold={thresh:.2f}: 0/{len(test_images)} detected")


if __name__ == "__main__":
    unittest.main()
