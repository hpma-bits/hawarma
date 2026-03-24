"""
测试固件模块

地位：提供测试所需的配方数据和订单创建辅助函数

输入：无
输出：测试用配方和订单对象

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新
"""

from tests.fixtures.test_recipes import (
    TEST_RECIPES,
    create_order_from_recipe,
    create_test_order,
)

__all__ = [
    "TEST_RECIPES",
    "create_order_from_recipe",
    "create_test_order",
]
