"""
TUI 测试脚本

测试 Hawarma TUI 的基本功能
"""

import sys

from hawarma.tui import HawarmaApp


def test_tui_creation():
    """测试TUI应用是否能正常创建"""
    app = HawarmaApp()
    print("[OK] TUI应用创建成功")
    print(f"   配置加载: {'成功' if app.config else '失败'}")
    print(f"   配方管理器: {'成功' if app.recipe_manager else '失败'}")
    return True


def test_config_loading():
    """测试配置加载"""
    from hawarma.config import load_config
    config = load_config()
    print("[OK] 配置加载成功")
    print(f"   图片目录: {config.image_directory}")
    print(f"   日志目录: {config.log_directory}")
    print(f"   游戏时长: {config.episode_duration}秒")
    print(f"   策略: {config.strategy}")
    return True


def test_recipe_loading():
    """测试配方加载"""
    from hawarma.services.recipe_manager import RecipeManager
    recipe_manager = RecipeManager(recipes_path="data/recipes.json")
    recipes = recipe_manager.get_all_recipes()
    print(f"[OK] 配方加载成功，共 {len(recipes)} 个配方")
    for i, recipe in enumerate(recipes[:3]):
        print(f"   {i+1}. {recipe.name}")
    if len(recipes) > 3:
        print(f"   ... 还有 {len(recipes) - 3} 个配方")
    return True


def main():
    """运行所有测试"""
    print("开始测试 Hawarma TUI...")
    print()
    
    tests = [
        ("TUI应用创建", test_tui_creation),
        ("配置加载", test_config_loading),
        ("配方加载", test_recipe_loading),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            print(f"测试: {test_name}")
            if test_func():
                passed += 1
            else:
                failed += 1
                print(f"   [FAIL] 测试失败")
        except Exception as e:
            failed += 1
            print(f"   [ERROR] 测试异常: {e}")
        print()
    
    print("=" * 40)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 40)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
