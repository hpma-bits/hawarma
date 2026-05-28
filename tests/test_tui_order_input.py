"""
测试 TUI 配方选择输入解析逻辑

验证用户输入的准备顺序数字串能被正确解析为配方顺序。
"""

import unittest

from hawarma.recipe import Recipe, Station
from hawarma.utils.order_parser import parse_order_input


def _make_recipe(slug: str, name: str) -> Recipe:
    """创建测试用 Recipe（只需 slug 和 name）"""
    return Recipe(
        slug=slug,
        name=name,
        raw_ingredients=[],
        cookers=[],
        cookers_layout=[],
        cook_durations=[],
        condiments={},
        station=Station.GASTRONOME,
    )


class TestTuiOrderInput(unittest.TestCase):
    """测试 TUI 订单输入解析"""

    def setUp(self):
        self.recipes = [
            _make_recipe("recipe_a", "Recipe A"),
            _make_recipe("recipe_b", "Recipe B"),
            _make_recipe("recipe_c", "Recipe C"),
            _make_recipe("recipe_d", "Recipe D"),
        ]

    def test_default_order_when_empty(self):
        result = parse_order_input(self.recipes, "")
        self.assertEqual(result, self.recipes)

    def test_default_order_when_input_length_mismatch(self):
        result = parse_order_input(self.recipes, "01")
        self.assertEqual(result, self.recipes)

    def test_default_order_when_input_has_alpha(self):
        result = parse_order_input(self.recipes, "a2c")
        self.assertEqual(result, self.recipes)

    def test_parse_012_returns_default_order(self):
        result = parse_order_input(self.recipes, "0123")
        self.assertEqual(
            [r.slug for r in result],
            ["recipe_a", "recipe_b", "recipe_c", "recipe_d"],
        )

    def test_parse_2130_reorders_correctly(self):
        result = parse_order_input(self.recipes, "2130")
        slugs = [r.slug for r in result]
        self.assertEqual(slugs, ["recipe_c", "recipe_b", "recipe_d", "recipe_a"])

    def test_parse_3210_reverses_order(self):
        result = parse_order_input(self.recipes, "3210")
        slugs = [r.slug for r in result]
        self.assertEqual(slugs, ["recipe_d", "recipe_c", "recipe_b", "recipe_a"])

    # ── 1-based 索引测试 ──

    def test_1based_1234_equals_0based_0123(self):
        """1-based '1234' 应等价于 0-based '0123'"""
        result = parse_order_input(self.recipes, "1234")
        self.assertEqual(
            [r.slug for r in result],
            ["recipe_a", "recipe_b", "recipe_c", "recipe_d"],
        )

    def test_1based_4321_reverses_order(self):
        """1-based '4321' → 0-based '3210' → [D,C,B,A]"""
        result = parse_order_input(self.recipes, "4321")
        self.assertEqual(
            [r.slug for r in result],
            ["recipe_d", "recipe_c", "recipe_b", "recipe_a"],
        )

    def test_1based_3241_specific_order(self):
        """1-based '3241' → 0-based '2130' → [C,B,D,A]"""
        result = parse_order_input(self.recipes, "3241")
        self.assertEqual(
            [r.slug for r in result],
            ["recipe_c", "recipe_b", "recipe_d", "recipe_a"],
        )

    def test_1based_auto_detect_with_3_recipes(self):
        """3个食谱时，1-based 用 1-3，'231' → 0-based '120' → [B,C,A]"""
        recipes = self.recipes[:3]
        result = parse_order_input(recipes, "231")
        self.assertEqual(
            [r.slug for r in result],
            ["recipe_b", "recipe_c", "recipe_a"],
        )

    def test_1based_single_recipe(self):
        """1个食谱时，'1' 等价于 '0'"""
        recipes = self.recipes[:1]
        result = parse_order_input(recipes, "1")
        self.assertEqual(result, recipes)

    # ── 边界与混合 ──

    def test_0based_and_1based_both_work(self):
        """同一组食谱两种索引都应正确工作"""
        result_0 = parse_order_input(self.recipes, "2130")
        result_1 = parse_order_input(self.recipes, "3241")
        self.assertEqual(
            [r.slug for r in result_0],
            [r.slug for r in result_1],
        )

    def test_0based_has_0_does_not_trigger_1based(self):
        """含 '0' 的输入始终视为 0-based"""
        # '0124' → 0-based → selected[4] IndexError → fallback
        result = parse_order_input(self.recipes, "0124")
        self.assertEqual(
            [r.slug for r in result],
            ["recipe_a", "recipe_b", "recipe_c", "recipe_d"],
        )

    def test_parse_1010_works_with_repeated_indices(self):
        """输入数字可以包含重复值（同一食谱多次出现）"""
        result = parse_order_input(self.recipes, "1010")
        slugs = [r.slug for r in result]
        self.assertEqual(slugs, ["recipe_b", "recipe_a", "recipe_b", "recipe_a"])

    def test_parse_single_recipe(self):
        recipes = self.recipes[:1]
        result = parse_order_input(recipes, "0")
        self.assertEqual(result, recipes)

    def test_parse_three_recipes(self):
        recipes = self.recipes[:3]
        result = parse_order_input(recipes, "201")
        slugs = [r.slug for r in result]
        self.assertEqual(slugs, ["recipe_c", "recipe_a", "recipe_b"])

    def test_selected_recipes_order_matches_display_order(self):
        """
        验证 selected_recipes 的构建方式：
        当用户从列表中选择了 [recipe_d, recipe_b, recipe_a, recipe_c]
        时（点击顺序），selected_recipes 仍应按 _all_recipes（JSON）顺序排列。
        """
        all_recipes = self.recipes  # [A, B, C, D]

        selected_slugs = ["recipe_d", "recipe_b", "recipe_a", "recipe_c"]

        selected_recipes = [
            r for r in all_recipes if r.slug in selected_slugs
        ]

        slugs = [r.slug for r in selected_recipes]
        self.assertEqual(slugs, ["recipe_a", "recipe_b", "recipe_c", "recipe_d"])

    def test_order_after_selection_mismatch(self):
        """
        即使 selected_slugs 是乱序（点击顺序），
        用户输入 "2130" 仍应正确映射到 JSON 顺序的 recipes。
        """
        all_recipes = self.recipes
        selected_slugs = ["recipe_d", "recipe_b", "recipe_a", "recipe_c"]

        selected_recipes = [
            r for r in all_recipes if r.slug in selected_slugs
        ]

        result = parse_order_input(selected_recipes, "2130")
        slugs = [r.slug for r in result]
        self.assertEqual(slugs, ["recipe_c", "recipe_b", "recipe_d", "recipe_a"])


if __name__ == "__main__":
    unittest.main()
