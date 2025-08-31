import asyncio
import time


async def capture():
    await asyncio.to_thread(print, "\nCapturing screen ...")
    time.sleep(0.2)  # Simulate blocking I/O operation


async def handle_ingredient(order_id, ingredient_num, duration):
    """Simulates heating one ingredient and then moving it."""
    print(
        f"[Order {order_id}] Heating up ingredient {ingredient_num} ({duration}s) ..."
    )
    await asyncio.sleep(duration)
    print(f"[Order {order_id}] Moving ingredient {ingredient_num} to assembly ...")


async def handle_ingredients(order_id, durations: list):
    """Simulates preparing all ingredients for an order up to the assembly point."""
    print(f"-> [Order {order_id}] Starting ingredient preparation.")
    tasks = [
        handle_ingredient(order_id, i, duration) for i, duration in enumerate(durations)
    ]
    await asyncio.gather(*tasks)
    print(f"<- [Order {order_id}] All ingredients are at the assembly station.")


async def season(order_id):
    """Simulates seasoning the dish at the assembly station."""
    print(f"-> [Order {order_id}] Seasoning dish ...")
    time.sleep(0.1)
    print(f"<- [Order {order_id}] Dish seasoned.")


async def serve_dish(order_id):
    """Simulates serving the final dish."""
    print(f"-> [Order {order_id}] Serving dish ...")
    time.sleep(0.1)
    print(f"<- [Order {order_id}] Dish served.")


async def main():
    """
    Simulates a pipelined cooking process for three orders.
    The cooking for the next order starts as soon as the previous
    order's ingredients are at the assembly station.
    """
    order_durations = [[2, 3], [2.5, 2], [1.5, 3.5]]
    cooking_tasks = {}

    # --- Start Order 0 ---
    await capture()
    print("--- Starting Order 0 ---")
    # Start cooking ingredients for Order 0 in the background.
    cooking_tasks[0] = asyncio.create_task(handle_ingredients(0, order_durations[0]))

    # --- Start Order 1 ---
    # Wait for Order 0's ingredients to be ready at the assembly station.
    await cooking_tasks[0]
    await capture()
    print("--- Order 0 ingredients ready, starting Order 1 cooking ---")
    # Start cooking ingredients for Order 1.
    cooking_tasks[1] = asyncio.create_task(handle_ingredients(1, order_durations[1]))
    # Now that Order 1's cooking has started, we can finish Order 0.
    await capture()
    print("--- Finishing Order 0 (season & serve) ---")
    await season(0)
    await serve_dish(0)
    print("====== Order 0 Complete ======")

    # --- Start Order 2 ---
    # Wait for Order 1's ingredients to be ready.
    await cooking_tasks[1]
    await capture()
    print("--- Order 1 ingredients ready, starting Order 2 cooking ---")
    # Start cooking ingredients for Order 2.
    cooking_tasks[2] = asyncio.create_task(handle_ingredients(2, order_durations[2]))
    # Finish Order 1.
    await capture()
    print("--- Finishing Order 1 (season & serve) ---")
    await season(1)
    await serve_dish(1)
    print("====== Order 1 Complete ======")

    # --- Finish the last order ---
    # Wait for Order 2's ingredients.
    await cooking_tasks[2]
    await capture()
    print("--- Finishing Order 2 (season & serve) ---")
    await season(2)
    await serve_dish(2)
    print("====== Order 2 Complete ======")


if __name__ == "__main__":
    asyncio.run(main())
