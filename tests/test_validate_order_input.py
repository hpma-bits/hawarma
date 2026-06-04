"""
测试 prepare order 输入的校验逻辑（不修改数据）

覆盖：空输入、长度不符、非数字字符、索引越界、合法输入。
"""

import unittest

from hawarma.recipe import Recipe, Station
from hawarma.utils.order_parser import validate_order_input


def _make_recipe(slug: str, name: str) -> Recipe:
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


class TestValidateOrderInput(unittest.TestCase):
    def setUp(self):
        self.recipes = [
            _make_recipe("a", "A"),
            _make_recipe("b", "B"),
            _make_recipe("c", "C"),
            _make_recipe("d", "D"),
        ]

    def test_empty_is_valid(self):
        valid, err = validate_order_input(self.recipes, "")
        self.assertTrue(valid)
        self.assertEqual(err, "")

    def test_length_mismatch_too_short(self):
        valid, err = validate_order_input(self.recipes, "01")
        self.assertFalse(valid)
        self.assertIn("长度应为 4", err)

    def test_length_mismatch_too_long(self):
        valid, err = validate_order_input(self.recipes, "01234")
        self.assertFalse(valid)
        self.assertIn("长度应为 4", err)

    def test_non_digit_chars(self):
        valid, err = validate_order_input(self.recipes, "01a3")
        self.assertFalse(valid)
        self.assertIn("非数字字符", err)

    def test_0based_in_range(self):
        valid, err = validate_order_input(self.recipes, "0123")
        self.assertTrue(valid)
        self.assertEqual(err, "")

    def test_0based_out_of_range(self):
        valid, err = validate_order_input(self.recipes, "0124")
        self.assertFalse(valid)
        self.assertIn("索引越界", err)
        self.assertIn("0~3", err)

    def test_1based_in_range(self):
        valid, err = validate_order_input(self.recipes, "1234")
        self.assertTrue(valid)
        self.assertEqual(err, "")

    def test_overflow_treated_as_0based(self):
        """含超出 1-based 范围数字的输入（n=4 时含 5）自动降级为 0-based 校验"""
        valid, err = validate_order_input(self.recipes, "1235")
        self.assertFalse(valid)
        self.assertIn("0~3", err)

    def test_mixed_0and1_based_treated_as_0based(self):
        """含 '0' 的输入视为 0-based，此时 5 越界"""
        valid, err = validate_order_input(self.recipes, "0125")
        self.assertFalse(valid)
        self.assertIn("0~3", err)

    def test_repeated_indices_are_allowed(self):
        """重复索引被显式允许（与 parse_order_input 旧行为一致）"""
        valid, err = validate_order_input(self.recipes, "1010")
        self.assertTrue(valid)
        self.assertEqual(err, "")

    def test_empty_recipes_with_empty_input(self):
        valid, err = validate_order_input([], "")
        self.assertTrue(valid)

    def test_empty_recipes_with_any_input_invalid(self):
        valid, err = validate_order_input([], "0")
        self.assertFalse(valid)
        self.assertIn("长度应为 0", err)


if __name__ == "__main__":
    unittest.main()
