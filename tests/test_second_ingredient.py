"""
Test case to reproduce the issue: Order 0 has 2 ingredients, second ingredient never gets added
"""
import asyncio
import unittest
from unittest.mock import Mock, AsyncMock

from hawarma.services.assembly_station_manager import AssemblyStationManager
from hawarma.models import Order, Recipe, OrderStage


def create_test_recipe(ingredients: list[str] = None) -> Recipe:
    if ingredients is None:
        ingredients = ["patty", "bun"]
    return Recipe(
        slug="test-burger",
        name="Test Burger",
        raw_ingredients=ingredients,
        cookers=["grill"] * len(ingredients),
        cookers_layout=["grill"] * len(ingredients),
        cook_durations=[2.0] * len(ingredients),
        condiments=["ketchup"]
    )


def create_test_order(order_id: int, recipe: Recipe = None, is_rush: bool = False, ingredients: list[str] = None) -> Order:
    if recipe is None:
        recipe = create_test_recipe(ingredients=ingredients)
    return Order(
        recipe=recipe,
        is_rush=is_rush,
        condiment_preference={"ketchup": 1},
        order_id=order_id,
        current_stage=OrderStage.PENDING,
    )


class MockCookingService:
    """Mock cooking service that simulates UI operations"""
    
    def __init__(self):
        self.use_stocked_ingredient_calls = []
    
    async def use_stocked_ingredient(self, stockpile_index: int, destination: tuple, skip_assembly_lock: bool = False):
        """Simulate moving ingredient from stockpile to destination"""
        self.use_stocked_ingredient_calls.append((stockpile_index, destination))
        # Simulate UI operation time
        await asyncio.sleep(0.05)
        return True


class TestSecondIngredientIssue(unittest.TestCase):
    """
    Test case to reproduce the issue where the second ingredient of an order
    fails to be added because of nested lock acquisition.
    """
    
    def setUp(self):
        self.mock_cooking_service = MockCookingService()
        self.assembly_station_manager = AssemblyStationManager(
            cooking_service=self.mock_cooking_service,
            assembly_station_position=(500, 300),
            stockpile_area_assignments={
                "stockpile_0": "patty",
                "stockpile_1": "bun"
            },
        )
    
    def test_same_order_two_ingredients_sequential(self):
        """
        Test: Order with 2 ingredients added sequentially (one after another).
        This should work but currently fails due to nested lock issue.
        """
        async def run_test():
            order = create_test_order(0, ingredients=["patty", "bun"])
            
            # Add first ingredient
            result1 = await self.assembly_station_manager.add_ingredient(
                order=order,
                ingredient_name="patty",
                stockpile_area_index=0,
                wait_for_available=True,
            )
            print(f"First ingredient added: {result1}")
            self.assertTrue(result1)
            
            # Add second ingredient - this is where it fails
            result2 = await self.assembly_station_manager.add_ingredient(
                order=order,
                ingredient_name="bun",
                stockpile_area_index=1,
                wait_for_available=True,
            )
            print(f"Second ingredient added: {result2}")
            self.assertTrue(result2)
            
            # Verify both ingredients are tracked
            self.assertEqual(len(order.ingredients_at_assembly), 2)
            self.assertIn("patty", order.ingredients_at_assembly)
            self.assertIn("bun", order.ingredients_at_assembly)
        
        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
