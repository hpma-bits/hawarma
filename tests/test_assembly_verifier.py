"""
测试组装站验证器

地位：验证 AssemblyVerifier 在 testset 图片上能否正确识别空组装站
      使用 mock 绕过 airtest 依赖

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2


class TestAssemblyVerifier(unittest.TestCase):
    """测试组装站验证器"""

    def setUp(self):
        """设置测试环境"""
        self.testset_dir = Path(__file__).parent / "testset"
        self.test_images = list(self.testset_dir.glob("*.jpg"))
        self.assertTrue(len(self.test_images) > 0, "No test images found in testset")

    def _create_mock_config(self):
        """创建模拟配置"""
        config = MagicMock()
        config.image_directory = str(Path(__file__).parent.parent / "static" / "img")
        return config

    def _setup_airtest_mocks(self):
        """设置 airtest mock"""
        mock_g = MagicMock()
        mock_template = MagicMock()
        mock_crop = MagicMock()

        def mock_crop_image(img, roi):
            x1, y1, x2, y2 = roi
            return img[y1:y2, x1:x2]

        mock_crop.side_effect = mock_crop_image

        modules_to_mock = {
            'airtest': MagicMock(),
            'airtest.core': MagicMock(),
            'airtest.core.api': MagicMock(),
            'airtest.aircv': mock_crop,
        }
        modules_to_mock['airtest.core.api'].G = mock_g
        modules_to_mock['airtest.core.api'].Template = mock_template

        patcher = patch.dict(sys.modules, modules_to_mock)
        patcher.start()
        self.addCleanup(patcher.stop)

        return mock_g, mock_template

    def test_empty_assembly_detection_on_testset(self):
        """
        在所有 testset 图片上验证空组装站检测
        所有 testset 图片中的 assembly 都是空的，应该全部返回 True
        """
        mock_g, mock_template = self._setup_airtest_mocks()

        from hawarma.bridge.assembly_verifier import AssemblyVerifier

        config = self._create_mock_config()
        verifier = AssemblyVerifier(config)

        self.assertIsNotNone(verifier._empty_template, "Template should be loaded")

        results = {}
        for img_path in self.test_images:
            screen = cv2.imread(str(img_path))
            self.assertIsNotNone(screen, f"Failed to load {img_path.name}")

            mock_g.DEVICE.snapshot.return_value = screen
            is_empty = verifier.is_assembly_empty()
            results[img_path.name] = is_empty

        all_empty = all(results.values())
        self.assertTrue(
            all_empty,
            f"Some images failed to detect empty assembly: {[k for k, v in results.items() if not v]}"
        )

    def test_empty_assembly_detection_individual(self):
        """逐个测试每张图片，方便定位问题"""
        mock_g, mock_template = self._setup_airtest_mocks()

        from hawarma.bridge.assembly_verifier import AssemblyVerifier

        config = self._create_mock_config()
        verifier = AssemblyVerifier(config)

        for img_path in self.test_images:
            screen = cv2.imread(str(img_path))
            mock_g.DEVICE.snapshot.return_value = screen
            is_empty = verifier.is_assembly_empty()
            self.assertTrue(
                is_empty,
                f"Failed to detect empty assembly in {img_path.name}"
            )


if __name__ == "__main__":
    unittest.main()
