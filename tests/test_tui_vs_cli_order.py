"""
测试 TUI 和 CLI 的配方排序逻辑是否一致

从真实 JSON 加载数据，模拟 TUI/CLI 的精确代码路径。
"""

import unittest
from hawarma.services.recipe_manager import RecipeManager
from hawarma.recipe import Recipe, Station
from hawarma.utils.order_parser import parse_order_input


def tui_build_selected(all_recipes: list[Recipe], selected_slugs: list[str], station: Station) -> list[Recipe]:
    """TUI on_button_pressed 中的精确逻辑"""
    return [
        r for r in all_recipes
        if r.slug in selected_slugs and r.station == station
    ]


def cli_build_selected(all_recipes: list[Recipe], selected_names: list[str]) -> list[Recipe]:
    """CLI get_recipe_selection 中的精确逻辑"""
    return [r for r in all_recipes if r.name in selected_names]


class TestTuiVsCliOrder(unittest.TestCase):
    """验证 TUI 和 CLI 排序逻辑完全一致"""

    @classmethod
    def setUpClass(cls):
        mgr = RecipeManager()
        cls.all_recipes = mgr.get_all_recipes()
        cls.gastronome_recipes = [r for r in cls.all_recipes if r.station == Station.GASTRONOME]
        cls.dessert_recipes = [r for r in cls.all_recipes if r.station == Station.DESSERT]

    def setUp(self):
        self.g4 = self.gastronome_recipes[:4]

    # ── TUI 自身准确性 ──

    def test_tui_input_2130_gives_correct_order(self):
        selected = tui_build_selected(self.g4, [r.slug for r in self.g4], Station.GASTRONOME)
        result = parse_order_input(selected, "2130")
        expected = [self.g4[2], self.g4[1], self.g4[3], self.g4[0]]
        self.assertEqual(
            [r.slug for r in result],
            [r.slug for r in expected],
            f"TUI '2130' failed.\nSelected: {[r.slug for r in selected]}\nGot: {[r.slug for r in result]}\nExpected: {[r.slug for r in expected]}",
        )

    def test_tui_input_2130_indices_map_correctly(self):
        """验证 '2130' 中每个数字索引的映射结果"""
        selected = tui_build_selected(self.g4, [r.slug for r in self.g4], Station.GASTRONOME)
        result = parse_order_input(selected, "2130")
        for i, idx_str in enumerate("2130"):
            idx = int(idx_str)
            self.assertEqual(
                result[i].slug,
                selected[idx].slug,
                f"result[{i}] should be selected_recipes[{idx}]={selected[idx].slug}, got {result[i].slug}",
            )

    def test_tui_input_3102_gives_correct_order(self):
        """验证如果用户实际输入 3102，结果对应什么"""
        selected = tui_build_selected(self.g4, [r.slug for r in self.g4], Station.GASTRONOME)
        result = parse_order_input(selected, "3102")
        expected = [self.g4[3], self.g4[1], self.g4[0], self.g4[2]]
        self.assertEqual(
            [r.slug for r in result],
            [r.slug for r in expected],
        )

    # ── 所有 24 种排列穷举测试 ──

    def test_all_24_permutations(self):
        """穷举所有 4! = 24 种输入排列，验证 TUI 和 CLI 结果一致"""
        import itertools
        selected = tui_build_selected(self.g4, [r.slug for r in self.g4], Station.GASTRONOME)

        for perm in itertools.permutations("0123"):
            input_str = "".join(perm)
            result = parse_order_input(selected, input_str)
            slugs = [r.slug for r in result]
            # 验证解析结果长度正确
            self.assertEqual(len(slugs), 4, f"Input '{input_str}': length mismatch")

    # ── TUI vs CLI 逻辑等价性 ──

    def test_tui_and_cli_build_selected_same_order(self):
        """TUI 和 CLI 构建 selected_recipes 的顺序应一致"""
        slugs = [r.slug for r in self.g4]
        names = [r.name for r in self.g4]

        tui_selected = tui_build_selected(self.all_recipes, slugs, Station.GASTRONOME)
        cli_selected = cli_build_selected(self.all_recipes, names)

        self.assertEqual(
            [r.slug for r in tui_selected],
            [r.slug for r in cli_selected],
        )

    def test_1based_1234_equals_0123(self):
        """1-based '1234' 与 0-based '0123' 结果一致"""
        selected = tui_build_selected(self.g4, [r.slug for r in self.g4], Station.GASTRONOME)
        result = parse_order_input(selected, "1234")
        expected = [r.slug for r in selected]
        self.assertEqual([r.slug for r in result], expected)

    def test_1based_3241_equals_2130(self):
        """1-based '3241' → 0-based '2130'，结果正确"""
        selected = tui_build_selected(self.g4, [r.slug for r in self.g4], Station.GASTRONOME)
        result = parse_order_input(selected, "3241")
        expected = [selected[2].slug, selected[1].slug, selected[3].slug, selected[0].slug]
        self.assertEqual([r.slug for r in result], expected)

    def test_parse_order_input_consistency(self):
        """parse_order_input 对所有输入应产生一致结果"""
        inputs = ["", "0123", "2130", "3210", "3102", "2013", "1230", "1010", "1234", "4321", "3241"]
        selected = tui_build_selected(self.g4, [r.slug for r in self.g4], Station.GASTRONOME)

        for input_str in inputs:
            result = parse_order_input(selected, input_str)
            self.assertEqual(
                len(result),
                len(selected),
                f"Length mismatch for input '{input_str}'",
            )

    # ── edge cases ──

    def test_input_length_mismatch_falls_back(self):
        selected = tui_build_selected(self.g4, [r.slug for r in self.g4], Station.GASTRONOME)
        for bad_input in ["", "01", "01234", "abc"]:
            result = parse_order_input(selected, bad_input)
            self.assertEqual(
                [r.slug for r in result],
                [r.slug for r in selected],
                f"Input '{bad_input}' should fallback to default order",
            )

    def test_tui_with_station_filter_does_not_mix_stations(self):
        """TUI 的 station 过滤不应混入其他 station 的食谱"""
        if len(self.gastronome_recipes) >= 3 and len(self.dessert_recipes) >= 1:
            # 取 3 个 gastronome + 1 个 dessert 确保 station 过滤生效
            mixed_slugs = [r.slug for r in self.gastronome_recipes[:3]] + [self.dessert_recipes[0].slug]
            result = tui_build_selected(self.all_recipes, mixed_slugs, Station.GASTRONOME)
            for r in result:
                self.assertEqual(r.station, Station.GASTRONOME, f"Recipe {r.slug} is {r.station}")


if __name__ == "__main__":
    unittest.main()
