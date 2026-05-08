"""
测试组装站验证器

地位：验证 Verifier 在 testset/assembly/ 图片上能否正确识别空组装站
      使用 patch 绕过 airtest 设备依赖，保留真实 Template 匹配
      文件名含 "empty" 的图片预期为空（True），否则预期为非空（False）

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2

import hawarma.game.verifier as av_module


class TestVerifier(unittest.TestCase):
    def setUp(self):
        self.assembly_dir = Path(__file__).parent / "testset" / "assembly"
        self.images = sorted(self.assembly_dir.glob("*.jpg"))
        self.assertGreater(len(self.images), 0, "No test images found")
        self._screens = {
            p.name: cv2.imread(str(p)) for p in self.images
        }

    def _create_mock_config(self):
        config = MagicMock()
        config.image_directory = str(Path(__file__).parent.parent / "static" / "img")
        config.debug.save_assembly_verify_screenshots = False
        config.matching.assembly_threshold = 0.9
        return config

    def _mock_device(self, screen):
        mock_g = MagicMock()
        mock_g.DEVICE.snapshot.return_value = screen
        return mock_g

    def _evaluate(self, threshold):
        verifier = av_module.Verifier(self._create_mock_config())
        verifier._empty_template.threshold = threshold

        failures = []
        for img_path in self.images:
            mock_g = self._mock_device(self._screens[img_path.name])
            with patch.object(av_module, "G", mock_g):
                is_empty = verifier.is_assembly_empty()

            expected = "empty" in img_path.stem
            if is_empty != expected:
                failures.append((img_path.name, expected, is_empty))

        correct = len(self.images) - len(failures)
        return correct, len(self.images), failures

    def test_threshold_sweep(self):
        """扫描阈值找到最优值"""
        print("\n  Threshold sweep (0.70..0.99):")
        best = None
        for t in range(70, 100):
            threshold = t / 100.0
            correct, total, failures = self._evaluate(threshold)
            status = "PASS" if not failures else "FAIL"
            line = f"    {threshold:.2f}: {correct}/{total} {status}"
            if failures:
                line += f"  fails: {[f[0] for f in failures]}"
            if not failures and best is None:
                best = threshold
            print(line)

        self.assertIsNotNone(best, "No threshold found that passes all images")
        print(f"\n  Lowest working threshold: {best}")

    def test_assembly_detection(self):
        """用 0.7 确认失败，再用最优阈值确认通过"""
        _, _, fails_07 = self._evaluate(0.7)
        self.assertEqual(len(fails_07), 2, "Expected 2 failures at threshold 0.7 (fish + jiaozi)")
        print(f"\n  threshold=0.7: expected 2 failures, got {len(fails_07)}: {[f[0] for f in fails_07]}")

        best = 0.90
        correct, total, failures = self._evaluate(best)
        print(f"\n  threshold={best}: {correct}/{total}")
        for img_path in self.images:
            expected = "empty" in img_path.stem
            mock_g = self._mock_device(self._screens[img_path.name])
            with patch.object(av_module, "G", mock_g):
                verifier = av_module.Verifier(self._create_mock_config())
                verifier._empty_template.threshold = best
                is_empty = verifier.is_assembly_empty()
            status = "OK" if is_empty == expected else "MISMATCH"
            print(f"    {img_path.name}: expected={expected}, actual={is_empty} [{status}]")
            self.assertEqual(is_empty, expected, f"{img_path.name} mismatch")


if __name__ == "__main__":
    unittest.main()
