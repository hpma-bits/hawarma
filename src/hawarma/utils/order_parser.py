"""配方顺序解析工具

支持 0-based（如 '0123'）和 1-based（如 '1234'）两种索引格式。
自动检测：不含 '0' 且所有数字在 [1, N] 范围内视为 1-based。
"""

from hawarma.recipe import Recipe


def validate_order_input(
    selected_recipes: list[Recipe],
    order_input: str,
) -> tuple[bool, str]:
    """校验顺序输入是否合法（不修改任何数据）

    空输入视为合法（使用默认顺序）。其他情况依次检查：
    1. 全部为数字
    2. 长度等于已选菜谱数
    3. 0 基索引在合法范围内（1 基范围 [1, N] 由自动检测保证）

    注意：重复索引被显式允许（与 parse_order_input 行为一致）。

    Args:
        selected_recipes: 已选择的配方列表
        order_input: 用户输入的数字串

    Returns:
        (is_valid, error_message) - 合法时 error_message 为空字符串
    """
    n = len(selected_recipes)
    if not order_input:
        return True, ""
    if not all(c.isdigit() for c in order_input):
        return False, f"输入包含非数字字符：'{order_input}'"
    if len(order_input) != n:
        return False, (
            f"输入长度应为 {n}（当前 {len(order_input)}），"
            f"请为每个已选菜谱各输入一个数字"
        )

    is_one_based = all('1' <= c <= str(n) for c in order_input)
    indices = [int(c) - 1 for c in order_input] if is_one_based else [int(c) for c in order_input]

    if not is_one_based and any(i < 0 or i >= n for i in indices):
        return False, f"0 基索引越界：有效范围 0~{n - 1}"

    return True, ""


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
    if not order_input:
        return selected_recipes
    valid, _ = validate_order_input(selected_recipes, order_input)
    if not valid:
        return selected_recipes

    n = len(selected_recipes)
    is_one_based = all('1' <= c <= str(n) for c in order_input)
    indices = [int(c) - 1 for c in order_input] if is_one_based else [int(c) for c in order_input]
    return [selected_recipes[idx] for idx in indices]
