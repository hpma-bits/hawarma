"""
测试配方数据

地位：提供测试用的配方和订单创建辅助函数

输入：无
输出：预定义配方、订单创建函数

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新
"""

from hawarma.models import Order, OrderStage, Recipe

# ============================================================================
# 测试用配方定义
# ============================================================================

TEST_RECIPES: dict[str, Recipe] = {
    # 单食材配方（简单）
    "braised_fish": Recipe(
        slug="braised_fish",
        name="Braised Fish",
        raw_ingredients=["clearwater_fish"],
        cookers=["skillet"],
        cookers_layout=["skillet"],
        cook_durations=[4.0],
        condiments=["hearthspice", "acacia_honey"],
    ),
    "hearty_pie": Recipe(
        slug="hearty_pie",
        name="Hearty Pie",
        raw_ingredients=["hearty_egg"],
        cookers=["oven"],
        cookers_layout=["oven"],
        cook_durations=[3.0],
        condiments=["buttermilk_cream", "acacia_honey"],
    ),
    "saltbaked_shrimp": Recipe(
        slug="saltbaked_shrimp",
        name="Saltbaked Shrimp",
        raw_ingredients=["shoreline_shrimp"],
        cookers=["grill"],
        cookers_layout=["grill"],
        cook_durations=[4.0],
        condiments=["sunkissed_lemon", "fleur_de_sel"],
    ),
    # 双食材配方（复杂）
    "risotto": Recipe(
        slug="risotto",
        name="Gilded Shore Risotto",
        raw_ingredients=["clearwater_fish", "creamfield_rice"],
        cookers=["oven", "pot"],
        cookers_layout=["oven", "pot"],
        cook_durations=[3.0, 2.0],
        condiments=["buttermilk_cream", "midsummer_onion"],
    ),
    "jiaozi": Recipe(
        slug="jiaozi",
        name="New Year Jiaozi",
        raw_ingredients=["dough_wrappers", "tender_lamb"],
        cookers=["pot", "grill"],
        cookers_layout=["grill", "pot"],
        cook_durations=[3.0, 4.0],
        condiments=["hearthspice", "fleur_de_sel"],
    ),
    "venison_stew": Recipe(
        slug="venison_stew",
        name="Braised Venison Stew",
        raw_ingredients=["forest_venison", "blanquette_fig"],
        cookers=["pot", "skillet"],
        cookers_layout=["skillet", "pot"],
        cook_durations=[4.0, 3.0],
        condiments=["elderberry_liqueur", "paleleaf_laurel"],
    ),
    # 高价值配方（长烹饪时间）
    "tomahawk": Recipe(
        slug="tomahawk",
        name="Wild Herb Tomahawk",
        raw_ingredients=["prime_cut_beef", "vining_marjoram"],
        cookers=["skillet", "grill"],
        cookers_layout=["grill", "skillet"],
        cook_durations=[5.0, 4.0],
        condiments=["hearthspice", "fleur_de_sel"],
    ),
    "ink_pasta": Recipe(
        slug="ink_pasta",
        name="Deepwater Ink Pasta",
        raw_ingredients=["deepwater_tentacle", "pliant_pasta"],
        cookers=["oven", "pot"],
        cookers_layout=["oven", "pot"],
        cook_durations=[5.0, 3.0],
        condiments=["elderberry_liqueur", "paleleaf_laurel"],
    ),
}


# ============================================================================
# 订单创建辅助函数
# ============================================================================

# 全局订单 ID 计数器
_order_id_counter = 0


def _next_order_id() -> int:
    """生成下一个订单 ID"""
    global _order_id_counter
    _order_id_counter += 1
    return _order_id_counter


def reset_order_counter() -> None:
    """重置订单 ID 计数器（用于测试隔离）"""
    global _order_id_counter
    _order_id_counter = 0


def create_test_order(
    recipe_name: str,
    is_rush: bool = False,
    condiment_preference: dict[str, int] | None = None,
) -> Order:
    """
    创建测试订单。

    Args:
        recipe_name: 配方名称（TEST_RECIPES 中的 key）
        is_rush: 是否为加急订单
        condiment_preference: 调料偏好，默认使用配方中的所有调料各 1 份

    Returns:
        Order 对象
    """
    if recipe_name not in TEST_RECIPES:
        raise ValueError(f"Unknown recipe: {recipe_name}")

    recipe = TEST_RECIPES[recipe_name]

    if condiment_preference is None:
        condiment_preference = {c: 1 for c in recipe.condiments}

    return Order(
        recipe=recipe,
        is_rush=is_rush,
        condiment_preference=condiment_preference,
        order_id=_next_order_id(),
        current_stage=OrderStage.PENDING,
    )


def create_order_from_recipe(
    recipe: Recipe,
    is_rush: bool = False,
    condiment_preference: dict[str, int] | None = None,
) -> Order:
    """
    从 Recipe 对象创建订单。

    Args:
        recipe: Recipe 对象
        is_rush: 是否为加急订单
        condiment_preference: 调料偏好

    Returns:
        Order 对象
    """
    if condiment_preference is None:
        condiment_preference = {c: 1 for c in recipe.condiments}

    return Order(
        recipe=recipe,
        is_rush=is_rush,
        condiment_preference=condiment_preference,
        order_id=_next_order_id(),
        current_stage=OrderStage.PENDING,
    )
