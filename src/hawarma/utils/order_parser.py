"""配方顺序解析工具

支持 0-based（如 '0123'）和 1-based（如 '1234'）两种索引格式。
自动检测：不含 '0' 且所有数字在 [1, N] 范围内视为 1-based。
"""

from hawarma.recipe import Recipe


def parse_order_input(
    selected_recipes: list[Recipe],
    order_input: str,
) -> list[Recipe]:
    """解析用户输入的订单顺序

    Args:
        selected_recipes: 已选择的配方列表
        order_input: 用户输入的数字串（如 '0123' 或 '1234'）

    Returns:
        按用户输入排序后的配方列表，输入无效时返回原列表
    """
    n = len(selected_recipes)
    if not (order_input and all(c.isdigit() for c in order_input) and len(order_input) == n):
        return selected_recipes

    if all('1' <= c <= str(n) for c in order_input):
        indices = [int(c) - 1 for c in order_input]
    else:
        indices = [int(c) for c in order_input]

    try:
        return [selected_recipes[idx] for idx in indices]
    except IndexError:
        return selected_recipes
