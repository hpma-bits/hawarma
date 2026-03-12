"""
并发测试：Assembly Station 并发访问安全性

地位：测试 AssemblyStationManager 在多订单并发场景下的行为
      验证在"前一个订单食材仍在assembly station时，新订单尝试添加食材"的场景

输入：模拟的订单数据、并发请求
输出：测试结果 - 验证并发安全性

NOTE: Once file content is updated, must update the header comment accordingly
"""

import asyncio
import unittest
from dataclasses import dataclass, field
from typing import Any

from hawarma.models import Order, OrderStage, Recipe
from hawarma.services.assembly_station_manager import AssemblyStationManager


class MockCookingService:
    """模拟 CookingService，替代真实的 UI 操作"""

    def __init__(self):
        self.call_log: list[str] = []
        self.use_stocked_ingredient_calls: list[dict] = []

    async def use_stocked_ingredient(
        self,
        stockpile_area_index: int,
        destination: tuple[int, int],
        skip_assembly_lock: bool = False,
    ):
        """模拟从 stock area 移动食材到 destination"""
        self.use_stocked_ingredient_calls.append({
            "stockpile_area_index": stockpile_area_index,
            "destination": destination,
            "skip_assembly_lock": skip_assembly_lock,
        })
        self.call_log.append(f"use_stocked_ingredient({stockpile_area_index}, {destination})")
        await asyncio.sleep(0.05)


def create_test_recipe(name: str = "test-burger", ingredients: list[str] = None) -> Recipe:
    """创建测试用 Recipe"""
    if ingredients is None:
        ingredients = ["patty", "bun"]
    return Recipe(
        slug=name,
        name=name,
        raw_ingredients=ingredients,
        cookers=["grill"] * len(ingredients),
        cookers_layout=["grill"],
        cook_durations=[3.0] * len(ingredients),
        condiments=["ketchup"],
    )


def create_test_order(
    order_id: int,
    recipe: Recipe = None,
    is_rush: bool = False,
    ingredients: list[str] = None,
) -> Order:
    """创建测试用 Order"""
    if recipe is None:
        recipe = create_test_recipe(ingredients=ingredients)
    return Order(
        recipe=recipe,
        is_rush=is_rush,
        condiment_preference={"ketchup": 1},
        order_id=order_id,
        current_stage=OrderStage.PENDING,
        ingredients_at_assembly=[],
    )


class TestAssemblyStationConcurrency(unittest.TestCase):
    """测试 Assembly Station 并发安全性"""

    def setUp(self):
        self.mock_cooking_service = MockCookingService()
        self.assembly_station_manager = AssemblyStationManager(
            cooking_service=self.mock_cooking_service,
            assembly_station_position=(500, 300),
            stockpile_area_assignments={"stockpile_area_0": "patty", "stockpile_area_1": "bun"},
        )

    def test_single_order_adds_ingredient(self):
        """基本测试：单个订单添加食材"""
        order = create_test_order(1)
        
        async def run_test():
            result = await self.assembly_station_manager.add_ingredient(
                order, "patty", stockpile_area_index=0
            )
            self.assertTrue(result)
            self.assertEqual(self.assembly_station_manager.current_order_id, 1)
            self.assertIn("patty", self.assembly_station_manager.ingredients_at_station)
        
        asyncio.run(run_test())

    def test_duplicate_ingredient_blocked(self):
        """测试：重复添加相同食材被阻止"""
        order = create_test_order(1)
        
        async def run_test():
            await self.assembly_station_manager.add_ingredient(
                order, "patty", stockpile_area_index=0
            )
            result = await self.assembly_station_manager.add_ingredient(
                order, "patty", stockpile_area_index=0
            )
            self.assertFalse(result)
        
        asyncio.run(run_test())

    def test_different_order_blocked_without_wait(self):
        """测试：不同订单在未等待情况下被阻止"""
        order1 = create_test_order(1)
        order2 = create_test_order(2)
        
        async def run_test():
            await self.assembly_station_manager.add_ingredient(
                order1, "patty", stockpile_area_index=0
            )
            result = await self.assembly_station_manager.add_ingredient(
                order2, "bun", stockpile_area_index=1, wait_for_available=False
            )
            self.assertFalse(result)
            self.assertEqual(self.assembly_station_manager.current_order_id, 1)
        
        asyncio.run(run_test())

    def test_different_order_waits_with_wait_flag(self):
        """测试：不同订单在等待模式下会等待"""
        order1 = create_test_order(1)
        order2 = create_test_order(2)
        
        async def run_test():
            async def simulate_order1():
                await asyncio.sleep(0.1)
                self.assembly_station_manager.clear_for_order(order1)

            async def simulate_order2():
                result = await self.assembly_station_manager.add_ingredient(
                    order2, "bun", stockpile_area_index=1, wait_for_available=True, timeout=1.0
                )
                return result

            task1 = asyncio.create_task(simulate_order1())
            task2 = asyncio.create_task(simulate_order2())

            done, pending = await asyncio.wait([task1, task2], timeout=2.0)
            
            for t in pending:
                t.cancel()

        asyncio.run(run_test())

    def test_clear_for_order_resets_state(self):
        """测试：clear_for_order 正确重置状态"""
        order = create_test_order(1)
        
        async def run_test():
            await self.assembly_station_manager.add_ingredient(
                order, "patty", stockpile_area_index=0
            )
            await self.assembly_station_manager.add_ingredient(
                order, "bun", stockpile_area_index=1
            )
            
            self.assertEqual(self.assembly_station_manager.current_order_id, 1)
            self.assertEqual(len(self.assembly_station_manager.ingredients_at_station), 2)
            
            self.assembly_station_manager.clear_for_order(order)
            
            self.assertIsNone(self.assembly_station_manager.current_order_id)
            self.assertEqual(len(self.assembly_station_manager.ingredients_at_station), 0)
        
        asyncio.run(run_test())

    def test_concurrent_add_ingredient_from_same_order(self):
        """测试：同一订单并发添加多个食材（应该全部成功）"""
        order = create_test_order(1, ingredients=["patty", "bun", "lettuce"])
        
        async def run_test():
            tasks = [
                self.assembly_station_manager.add_ingredient(order, "patty", stockpile_area_index=0),
                self.assembly_station_manager.add_ingredient(order, "bun", stockpile_area_index=1),
                self.assembly_station_manager.add_ingredient(order, "lettuce", stockpile_area_index=2),
            ]
            
            results = await asyncio.gather(*tasks)
            
            self.assertTrue(all(results))
            self.assertEqual(len(self.assembly_station_manager.ingredients_at_station), 3)
        
        asyncio.run(run_test())

    def test_concurrent_add_ingredient_different_orders_race_condition(self):
        """
        关键测试：模拟用户报告的问题场景
        订单1的食材仍在 assembly station 时，订单2尝试添加食材
        
        这是一个并发竞态测试，验证系统行为
        """
        order1 = create_test_order(1, ingredients=["patty", "bun"])
        order2 = create_test_order(2, ingredients=["patty", "bun"])
        
        async def run_test():
            add_results = {"order1": [], "order2": []}
            errors = []
            
            async def add_for_order1():
                try:
                    for ing in ["patty", "bun"]:
                        result = await self.assembly_station_manager.add_ingredient(
                            order1, ing, stockpile_area_index=0, wait_for_available=True, timeout=2.0
                        )
                        add_results["order1"].append((ing, result))
                except Exception as e:
                    errors.append(f"order1: {e}")

            async def add_for_order2():
                await asyncio.sleep(0.02)
                try:
                    for ing in ["patty", "bun"]:
                        result = await self.assembly_station_manager.add_ingredient(
                            order2, ing, stockpile_area_index=1, wait_for_available=True, timeout=2.0
                        )
                        add_results["order2"].append((ing, result))
                except Exception as e:
                    errors.append(f"order2: {e}")

            task1 = asyncio.create_task(add_for_order1())
            task2 = asyncio.create_task(add_for_order2())
            
            await asyncio.gather(task1, task2)
            
            print(f"\nOrder1 results: {add_results['order1']}")
            print(f"Order2 results: {add_results['order2']}")
            print(f"Current order ID: {self.assembly_station_manager.current_order_id}")
            print(f"Ingredients at station: {self.assembly_station_manager.ingredients_at_station}")
            print(f"Errors: {errors}")
            
            self.assertEqual(self.assembly_station_manager.current_order_id, 1)
            self.assertEqual(len(self.assembly_station_manager.ingredients_at_station), 2)
        
        asyncio.run(run_test())

    def test_order_completion_then_new_order(self):
        """
        测试：订单1完成并清理后，订单2可以添加食材
        
        模拟正常流程：订单1完成 -> clear_for_order -> 订单2开始添加
        """
        order1 = create_test_order(1, ingredients=["patty"])
        order2 = create_test_order(2, ingredients=["bun"])
        
        async def run_test():
            result1 = await self.assembly_station_manager.add_ingredient(
                order1, "patty", stockpile_area_index=0
            )
            self.assertTrue(result1)
            self.assertEqual(self.assembly_station_manager.current_order_id, 1)
            
            self.assembly_station_manager.clear_for_order(order1)
            self.assertIsNone(self.assembly_station_manager.current_order_id)
            self.assertEqual(len(self.assembly_station_manager.ingredients_at_station), 0)
            
            result2 = await self.assembly_station_manager.add_ingredient(
                order2, "bun", stockpile_area_index=1
            )
            self.assertTrue(result2)
            self.assertEqual(self.assembly_station_manager.current_order_id, 2)
        
        asyncio.run(run_test())

    def test_can_add_ingredient_check(self):
        """测试：can_add_ingredient 方法正确检测可用性"""
        order1 = create_test_order(1)
        order2 = create_test_order(2)
        
        async def run_test():
            can_add = await self.assembly_station_manager.can_add_ingredient(order1, "patty")
            self.assertTrue(can_add)
            
            await self.assembly_station_manager.add_ingredient(order1, "patty", stockpile_area_index=0)
            
            can_add_same = await self.assembly_station_manager.can_add_ingredient(order1, "patty")
            self.assertFalse(can_add_same)
            
            can_add_other = await self.assembly_station_manager.can_add_ingredient(order2, "bun")
            self.assertFalse(can_add_other)
        
        asyncio.run(run_test())


class TestConcurrentOrderProcessing(unittest.TestCase):
    """测试多订单并发处理的完整场景"""

    def setUp(self):
        self.mock_cooking_service = MockCookingService()
        self.assembly_station_manager = AssemblyStationManager(
            cooking_service=self.mock_cooking_service,
            assembly_station_position=(500, 300),
            stockpile_area_assignments={
                "stockpile_area_0": "patty",
                "stockpile_area_1": "bun",
                "stockpile_area_2": "lettuce",
            },
        )

    def test_sequential_orders_complete(self):
        """测试：顺序处理多个订单"""
        orders = [
            create_test_order(i, ingredients=["patty", "bun"])
            for i in range(1, 4)
        ]
        
        async def run_test():
            for idx, order in enumerate(orders):
                for ingredient in order.recipe.raw_ingredients:
                    result = await self.assembly_station_manager.add_ingredient(
                        order, ingredient, stockpile_area_index=idx
                    )
                    self.assertTrue(result)
                
                self.assembly_station_manager.clear_for_order(order)
                self.assertIsNone(self.assembly_station_manager.current_order_id)
        
        asyncio.run(run_test())

    def test_rush_order_preemption(self):
        """测试：加急订单优先处理"""
        order1 = create_test_order(1, is_rush=False)
        order2 = create_test_order(2, is_rush=True)
        
        async def run_test():
            task1 = asyncio.create_task(
                self.assembly_station_manager.add_ingredient(
                    order1, "patty", stockpile_area_index=0, wait_for_available=True, timeout=1.0
                )
            )
            await asyncio.sleep(0.01)
            
            task2 = asyncio.create_task(
                self.assembly_station_manager.add_ingredient(
                    order2, "bun", stockpile_area_index=1, wait_for_available=True, timeout=1.0
                )
            )
            
            await asyncio.gather(task1, task2)
            
            print(f"Final current_order_id: {self.assembly_station_manager.current_order_id}")
            print(f"Ingredients: {self.assembly_station_manager.ingredients_at_station}")
        
        asyncio.run(run_test())

    def test_high_concurrency_stress(self):
        """压力测试：高并发场景"""
        num_orders = 10
        orders = [
            create_test_order(i, ingredients=["patty"])
            for i in range(num_orders)
        ]
        
        async def run_test():
            results = []
            
            async def add_ingredient(order):
                result = await self.assembly_station_manager.add_ingredient(
                    order, "patty", 
                    stockpile_area_index=order.order_id % 3,
                    wait_for_available=True,
                    timeout=3.0
                )
                return (order.order_id, result)
            
            tasks = [asyncio.create_task(add_ingredient(order)) for order in orders]
            results = await asyncio.gather(*tasks)
            
            successful = [r for r in results if r[1]]
            print(f"\nSuccessful additions: {len(successful)}/{num_orders}")
            print(f"Current order: {self.assembly_station_manager.current_order_id}")
            print(f"Ingredients at station: {self.assembly_station_manager.ingredients_at_station}")
            
            self.assertGreater(len(successful), 0)
        
        asyncio.run(run_test())


class TestStockpileDirectSendConcurrency(unittest.TestCase):
    """
    测试 Stockpile 直接发送到 Assembly 的并发场景
    
    这是用户报告的核心问题：
    "系统在前一个订单的菜品存在于assembly station时试图把新的订单的食材从stockpile area移动到assembly station"
    """

    def setUp(self):
        self.mock_cooking_service = MockCookingService()
        self.assembly_station_manager = AssemblyStationManager(
            cooking_service=self.mock_cooking_service,
            assembly_station_position=(500, 300),
            stockpile_area_assignments={
                "stockpile_area_0": "patty",
                "stockpile_area_1": "bun",
            },
        )

    def test_stockpile_sends_while_order_in_progress(self):
        """
        核心测试：模拟 Stockpile 直接发送到 assembly 的场景
        
        场景：
        1. 订单1正在处理，食材已添加到 assembly station
        2. Stockpile 尝试直接发送食材到同一 assembly station（用于订单1或订单2）
        3. 系统应该正确处理这个并发场景
        """
        order1 = create_test_order(1, ingredients=["patty", "bun"])
        
        async def run_test():
            await self.assembly_station_manager.add_ingredient(
                order1, "patty", stockpile_area_index=0
            )
            
            self.assertEqual(self.assembly_station_manager.current_order_id, 1)
            self.assertIn("patty", self.assembly_station_manager.ingredients_at_station)
            
            result = await self.assembly_station_manager.add_ingredient(
                order1, "bun", stockpile_area_index=1
            )
            self.assertTrue(result)
            
            print(f"After order1 complete:")
            print(f"  current_order_id: {self.assembly_station_manager.current_order_id}")
            print(f"  ingredients: {self.assembly_station_manager.ingredients_at_station}")
            
            self.assembly_station_manager.clear_for_order(order1)
            
            print(f"After clear:")
            print(f"  current_order_id: {self.assembly_station_manager.current_order_id}")
            print(f"  ingredients: {self.assembly_station_manager.ingredients_at_station}")
            
            order2 = create_test_order(2, ingredients=["patty"])
            result2 = await self.assembly_station_manager.add_ingredient(
                order2, "patty", stockpile_area_index=0
            )
            
            print(f"After order2 add:")
            print(f"  current_order_id: {self.assembly_station_manager.current_order_id}")
            print(f"  ingredients: {self.assembly_station_manager.ingredients_at_station}")
            
            self.assertEqual(self.assembly_station_manager.current_order_id, 2)
            self.assertIn("patty", self.assembly_station_manager.ingredients_at_station)
        
        asyncio.run(run_test())

    def test_stockpile_send_concurrent_with_order_finish(self):
        """
        测试：Stockpile 发送与订单完成的竞态
        
        模拟：
        1. 订单1完成，正在 clear_for_order
        2. 订单2同时尝试 add_ingredient
        """
        order1 = create_test_order(1, ingredients=["patty"])
        order2 = create_test_order(2, ingredients=["bun"])
        
        async def run_test():
            await self.assembly_station_manager.add_ingredient(
                order1, "patty", stockpile_area_index=0
            )
            
            async def clear_and_check():
                await asyncio.sleep(0.02)
                self.assembly_station_manager.clear_for_order(order1)
                return "cleared"
            
            async def try_add():
                result = await self.assembly_station_manager.add_ingredient(
                    order2, "bun", 
                    stockpile_area_index=1,
                    wait_for_available=True,
                    timeout=2.0
                )
                return result
            
            results = await asyncio.gather(
                clear_and_check(),
                try_add()
            )
            
            print(f"\nResults: {results}")
            print(f"Current order: {self.assembly_station_manager.current_order_id}")
            print(f"Ingredients: {self.assembly_station_manager.ingredients_at_station}")
            
            self.assertEqual(self.assembly_station_manager.current_order_id, 2)
            self.assertIn("bun", self.assembly_station_manager.ingredients_at_station)
        
        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main(verbosity=2)