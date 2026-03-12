"""
Assembly Station Manager

Position: Centralized management of assembly station access and state

Input: Ingredient addition requests from order processing or stockpile
Output: Synchronized ingredient delivery with proper locking and state tracking

NOTE: Once file content is updated, must update the header comment accordingly
NOTE: Once this directory changes, update ARCHITECTURE.md
"""

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from hawarma.models import Order


class AssemblyStationManager:
    """
    Manages assembly station access with proper locking and state tracking.
    
    Responsibilities:
    1. Serialize all operations to the assembly station
    2. Track which ingredients are currently at the station
    3. Prevent duplicate ingredient delivery
    4. Support waiting for availability (for rush orders)
    """

    def __init__(
        self,
        cooking_service,
        assembly_station_position: tuple[int, int],
        stockpile_area_assignments: dict[str, str],
    ):
        """
        Initialize AssemblyStationManager.
        
        Args:
            cooking_service: CookingService instance for performing UI operations
            assembly_station_position: (x, y) position of assembly station
            stockpile_area_assignments: Mapping from ingredient name to stockpile area index
        """
        self._cooking_service = cooking_service
        self._assembly_station_pos = assembly_station_position
        self._stockpile_area_assignments = stockpile_area_assignments
        
        # State
        self._current_order_id: int | None = None
        self._ingredients_at_station: list[str] = []
        self._lock = asyncio.Lock()

    async def add_ingredient(
        self,
        order: "Order",
        ingredient_name: str,
        stockpile_area_index: int | None = None,
        wait_for_available: bool = False,
        timeout: float = 30.0,
    ) -> bool:
        """
        Add an ingredient to the assembly station.
        
        This is the main entry point for adding ingredients. It handles:
        - Lock acquisition (ensures serial access)
        - Duplicate prevention (checks if ingredient already at station)
        - Order state tracking
        - Optional waiting for availability (for rush orders)
        
        Args:
            order: The order this ingredient belongs to
            ingredient_name: Name of the ingredient to add
            stockpile_area_index: Index of stockpile area (if using stocked ingredient)
            wait_for_available: If True, wait for station to be available
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if ingredient was added successfully, False otherwise
        """
        start_time = asyncio.get_event_loop().time()
        
        while True:
            async with self._lock:
                # Check if this ingredient is already at the station
                if ingredient_name in self._ingredients_at_station:
                    if not wait_for_available:
                        logger.debug(
                            f"Ingredient {ingredient_name} already at assembly station, skipping"
                        )
                        return False
                    # Wait for station to be released (fall through to waiting logic)
                
                # Check if station is occupied by a different order
                if self._current_order_id is not None and self._current_order_id != order.order_id:
                    if not wait_for_available:
                        logger.debug(
                            f"Assembly station occupied by order {self._current_order_id}, "
                            f"cannot add ingredient for order {order.order_id}"
                        )
                        return False
                    # Will retry after releasing lock
                else:
                    # Station is available for this order
                    # Check if ingredient was already there and we're in waiting mode
                    if ingredient_name in self._ingredients_at_station:
                        # Another order just added this ingredient while we were waiting
                        # This is OK - the ingredient is now at the station
                        logger.debug(
                            f"Ingredient {ingredient_name} already at assembly station (previous order), "
                            f"marking as ready for order {order.order_id}"
                        )
                        return True
                    
                    # Station is available - set current order and proceed
                    # If this is the first ingredient for the order, set current order
                    if self._current_order_id is None:
                        self._current_order_id = order.order_id
                        logger.debug(f"Assembly station now processing order {order.order_id}")
                    
                    # Perform the actual UI operation while holding the lock
                    # This prevents race conditions where multiple orders try to use assembly station
                    if stockpile_area_index is not None:
                        try:
                            # Skip assembly_lock since we already hold manager._lock
                            await self._cooking_service.use_stocked_ingredient(
                                stockpile_area_index,
                                self._assembly_station_pos,
                                skip_assembly_lock=True,
                            )
                        except Exception as e:
                            if self._current_order_id == order.order_id and not self._ingredients_at_station:
                                self._current_order_id = None
                            raise
                    # else: cooking from scratch is handled by caller
                    
                    # Update tracking AFTER UI operation completes (while still holding lock)
                    self._ingredients_at_station.append(ingredient_name)
                    order.ingredients_at_assembly.append(ingredient_name)
                    
                    logger.success(
                        f"Added {ingredient_name} to assembly station for order {order.order_id}. "
                        f"Ingredients: {self._ingredients_at_station}"
                    )
                    
                    return True
            
            # If we get here, station is occupied by another order and we need to wait
            if not wait_for_available:
                return False
            
            # Check timeout
            if asyncio.get_event_loop().time() - start_time >= timeout:
                logger.warning(
                    f"Order {order.order_id} timed out waiting for assembly station "
                    f"to add {ingredient_name}"
                )
                return False
            
            # Wait before retrying (lock is already released)
            logger.debug(
                f"Order {order.order_id} waiting for assembly station to add {ingredient_name}..."
            )
            await asyncio.sleep(0.1)

    async def can_add_ingredient(
        self,
        order: "Order",
        ingredient_name: str,
    ) -> bool:
        """
        Check if an ingredient can be added to the assembly station.
        
        Args:
            order: The order this ingredient belongs to
            ingredient_name: Name of the ingredient to add
            
        Returns:
            True if the ingredient can be added, False otherwise
        """
        async with self._lock:
            # Check if this ingredient is already at the station
            if ingredient_name in self._ingredients_at_station:
                return False
            
            # Check if station is occupied by a different order
            if self._current_order_id is not None and self._current_order_id != order.order_id:
                return False
            
            return True

    async def wait_for_available(
        self,
        order: "Order",
        timeout: float = 30.0,
    ) -> bool:
        """
        Wait for the assembly station to be available for this order.
        
        For rush orders that need to priority-process but must wait for station.
        
        Args:
            order: The order waiting for the station
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if station became available, False if timeout
        """
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            if await self.can_add_ingredient(order, ""):
                return True
            
            logger.debug(
                f"Order {order.order_id} waiting for assembly station..."
            )
            await asyncio.sleep(0.2)
        
        logger.warning(
            f"Order {order.order_id} timed out waiting for assembly station"
        )
        return False

    def clear_for_order(self, order: "Order") -> None:
        """
        Clear assembly station state when an order is completed or cancelled.
        
        Note: This should only be called when the order is done.
        
        Args:
            order: The order that was completed
        """
        if self._current_order_id == order.order_id:
            self._current_order_id = None
            self._ingredients_at_station.clear()
            logger.debug(f"Assembly station cleared after order {order.order_id}")

    def is_empty(self) -> bool:
        """Check if assembly station is empty."""
        return self._current_order_id is None

    @property
    def current_order_id(self) -> int | None:
        """Get the current order ID at the station."""
        return self._current_order_id

    @property
    def ingredients_at_station(self) -> list[str]:
        """Get list of ingredients currently at the station."""
        return self._ingredients_at_station.copy()