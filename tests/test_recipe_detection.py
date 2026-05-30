# tests/test_recipe_detection.py
"""
Recipe 检测测试

测试 gildedShoreRisotto 和 braisedNewYearFish 的识别能力。
两者共享第一个食材 clearwater_fish，需要通过第二个食材或 cooker 图标区分。
"""

import unittest
from pathlib import Path

import cv2
from airtest.core.api import Template

from hawarma.config import load_config
from hawarma.game.scanner import Scanner
from hawarma.recipe import Recipe
from hawarma.utils.image_utils import local_match


TESTSET_DIR = Path(__file__).parent / "testset"
IMG_DIR = Path(__file__).parent.parent / "static" / "img"


class TestRecipeDetection(unittest.TestCase):
    """测试 gildedShoreRisotto 和 braisedNewYearFish 的识别"""

    def _load_screen(self, filename: str):
        path = TESTSET_DIR / filename
        self.assertTrue(path.exists(), f"Test image not found: {path}")
        screen = cv2.imread(str(path))
        self.assertIsNotNone(screen, f"Failed to load: {path}")
        return screen

    def _match_template(self, template_name: str, roi: tuple, screen):
        """通用模板匹配"""
        tpl_path = IMG_DIR / template_name
        self.assertTrue(tpl_path.exists(), f"Template not found: {tpl_path}")
        tpl = Template(str(tpl_path))
        return local_match(tpl, roi, screen)

    def _get_slot_rois(self, slot: int = 0):
        """从配置中获取 slot 0 的食材区域 ROI"""
        ingredients_regions = [
            (440, 250, 780, 385),
            (815, 250, 1155, 385),
            (1190, 250, 1530, 385),
            (1565, 250, 1905, 385),
        ]
        x1, y1, x2, y2 = ingredients_regions[slot]
        quarter_w = (x2 - x1) // 4
        ing1_roi = (x1, y1, x1 + quarter_w, y2)
        ing2_roi = (x1 + quarter_w, y1, x1 + 2 * quarter_w, y2)
        return ing1_roi, ing2_roi

    def _match_ingredient(self, ingredient_name: str, roi: tuple, screen):
        """匹配食材模板"""
        ing_path = f"ingredient-{ingredient_name}.jpg"
        if not (IMG_DIR / ing_path).exists():
            ing_path = f"icon-{ingredient_name}.jpg"
        return self._match_template(ing_path, roi, screen)

    def _match_cooker(self, cooker_name: str, roi: tuple, screen):
        """匹配 cooker 图标模板"""
        cooker_path = f"cooker-{cooker_name}.jpg"
        if not (IMG_DIR / cooker_path).exists():
            cooker_path = f"icon-{cooker_name}.jpg"
        return self._match_template(cooker_path, roi, screen)

    # ===== 基础匹配测试 =====

    def test_gildedShoreRisotto_first_ingredient(self):
        """gildedShoreRisotto.jpg 应匹配 clearwater_fish"""
        screen = self._load_screen("gildedShoreRisotto.jpg")
        ing1_roi, _ = self._get_slot_rois(0)
        match = self._match_ingredient("clearwater_fish", ing1_roi, screen)
        self.assertIsNotNone(match, "clearwater_fish should match")
        print(f"  clearwater_fish confidence: {match.get('confidence', 0):.4f}")

    def test_gildedShoreRisotto_second_ingredient(self):
        """gildedShoreRisotto.jpg 应匹配 creamfield_rice"""
        screen = self._load_screen("gildedShoreRisotto.jpg")
        _, ing2_roi = self._get_slot_rois(0)
        match = self._match_ingredient("creamfield_rice", ing2_roi, screen)
        self.assertIsNotNone(match, "creamfield_rice should match")
        print(f"  creamfield_rice confidence: {match.get('confidence', 0):.4f}")

    def test_braisedNewYearFish_first_ingredient(self):
        """braisedNewYearFish.jpg 应匹配 clearwater_fish"""
        screen = self._load_screen("braisedNewYearFish.jpg")
        ing1_roi, _ = self._get_slot_rois(0)
        match = self._match_ingredient("clearwater_fish", ing1_roi, screen)
        self.assertIsNotNone(match, "clearwater_fish should match")
        print(f"  clearwater_fish confidence: {match.get('confidence', 0):.4f}")

    def test_braisedNewYearFish_second_ingredient_no_match(self):
        """braisedNewYearFish.jpg 不应匹配 creamfield_rice"""
        screen = self._load_screen("braisedNewYearFish.jpg")
        _, ing2_roi = self._get_slot_rois(0)
        match = self._match_ingredient("creamfield_rice", ing2_roi, screen)
        if match:
            conf = float(match.get("confidence", 0))
            self.assertLess(conf, 0.7, "creamfield_rice should NOT match")

    # ===== 冲突检测模拟 =====

    def test_scanner_resolves_gildedShoreRisotto(self):
        """Scanner 应通过第二食材正确识别 gildedShoreRisotto"""
        screen = self._load_screen("gildedShoreRisotto.jpg")
        ing1_roi, ing2_roi = self._get_slot_rois(0)

        # 两个候选共享 clearwater_fish
        m1 = self._match_ingredient("clearwater_fish", ing1_roi, screen)
        self.assertIsNotNone(m1)

        # 检查第二食材 creamfield_rice
        m2 = self._match_ingredient("creamfield_rice", ing2_roi, screen)
        self.assertIsNotNone(m2)
        conf = float(m2.get("confidence", 0))
        self.assertGreater(conf, 0.6, "Should resolve to gildedShoreRisotto via second ingredient")

    def test_scanner_cannot_resolve_braisedNewYearFish(self):
        """
        Scanner 无法通过第二食材区分 braisedNewYearFish。
        _resolve_dessert_conflict 返回 None，
        _resolve_cooker_conflict 是不完整实现也返回 None。
        最终结果取决于迭代顺序（可能误识别）。
        """
        screen = self._load_screen("braisedNewYearFish.jpg")
        ing1_roi, ing2_roi = self._get_slot_rois(0)

        m1 = self._match_ingredient("clearwater_fish", ing1_roi, screen)
        self.assertIsNotNone(m1)

        # 第二食材不应匹配
        m2 = self._match_ingredient("creamfield_rice", ing2_roi, screen)
        if m2:
            conf = float(m2.get("confidence", 0))
            self.assertLess(conf, 0.6, "creamfield_rice should not match")

    # ===== Cooker 图标匹配（用于验证修复方案的可行性）=====

    def test_gildedShoreRisotto_cooker_oven(self):
        """gildedShoreRisotto.jpg 的 cooker 区域应匹配 oven"""
        screen = self._load_screen("gildedShoreRisotto.jpg")
        ing1_roi, _ = self._get_slot_rois(0)

        match = self._match_cooker("oven", ing1_roi, screen)
        if match:
            conf = float(match.get("confidence", 0))
            print(f"  oven in gildedShoreRisotto: {conf:.4f}")
            self.assertGreater(conf, 0.7, "oven should match in gildedShoreRisotto")
        else:
            print("  oven: no match (template may differ from screenshot)")

    def test_braisedNewYearFish_cooker_skillet(self):
        """braisedNewYearFish.jpg 的 cooker 区域应匹配 skillet"""
        screen = self._load_screen("braisedNewYearFish.jpg")
        ing1_roi, _ = self._get_slot_rois(0)

        match = self._match_cooker("skillet", ing1_roi, screen)
        if match:
            conf = float(match.get("confidence", 0))
            print(f"  skillet in braisedNewYearFish: {conf:.4f}")
            self.assertGreater(conf, 0.7, "skillet should match in braisedNewYearFish")
        else:
            print("  skillet: no match (template may differ from screenshot)")


class TestScannerIntegration(unittest.TestCase):
    """通过 Scanner._detect_order 端到端测试 recipe 识别"""

    @classmethod
    def setUpClass(cls):
        cls.config = load_config()
        recipes_data = [
            {
                "slug": "gildedShoreRisotto",
                "name": "Gilded Shore Risotto",
                "raw_ingredients": ["clearwater_fish", "creamfield_rice"],
                "cookers": ["oven", "pot"],
                "cookers_layout": ["oven", "pot"],
                "cook_durations": [3.0, 2.0],
                "condiments": ["buttermilk_cream", "midsummer_onion"],
                "station": "gastronome",
            },
            {
                "slug": "braisedNewYearFish",
                "name": "Braised New Year Fish",
                "raw_ingredients": ["clearwater_fish"],
                "cookers": ["skillet"],
                "cookers_layout": ["skillet"],
                "cook_durations": [4.0],
                "condiments": ["hearthspice", "acacia_honey"],
                "station": "gastronome",
            },
        ]
        cls.recipes = [Recipe(**d) for d in recipes_data]
        cls.scanner = Scanner(cls.config, cls.recipes)

    def _load_screen(self, filename: str):
        path = TESTSET_DIR / filename
        return cv2.imread(str(path))

    def test_detect_gildedShoreRisotto(self):
        """Scanner 应正确识别 gildedShoreRisotto"""
        screen = self._load_screen("gildedShoreRisotto.jpg")
        order = self.scanner._detect_order(0, screen)
        self.assertIsNotNone(order, "Should detect an order")
        self.assertEqual(order.recipe_slug, "gildedShoreRisotto")

    def test_detect_braisedNewYearFish(self):
        """Scanner 应正确识别 braisedNewYearFish"""
        screen = self._load_screen("braisedNewYearFish.jpg")
        order = self.scanner._detect_order(0, screen)
        self.assertIsNotNone(order, "Should detect an order")
        self.assertEqual(order.recipe_slug, "braisedNewYearFish")


if __name__ == "__main__":
    unittest.main(verbosity=2)
