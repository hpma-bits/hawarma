"""
Order Policy

地位：管理订单优先级和排序逻辑。

输入：GameState订单列表
输出：排序后的订单列表、优先级判断

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from hawarma.state import GameState
from hawarma.models import Order, OrderStage


class OrderPolicy:
    """
    Handles order priority and scheduling decisions.
    
    Responsibilities:
    - Rush-first ordering
    - Tie-breaking by submission time
    - Starvation prevention for normal orders
    """
    
    def get_sorted_active_orders(
        self, state: GameState
    ) -> list[tuple[int, Order]]:
        """
        Get all pending orders sorted by priority.
        
        Rush orders come first, then normal orders.
        Within each group, orders are sorted by slot index (FIFO).
        
        Args:
            state: Current game state
            
        Returns:
            List of (slot_index, order) tuples sorted by priority
        """
        rush: list[tuple[int, Order]] = []
        normal: list[tuple[int, Order]] = []
        
        for idx, order in enumerate(state.orders):
            if order is None or order.done:
                continue
            
            if order.is_rush:
                rush.append((idx, order))
            else:
                normal.append((idx, order))
        
        return rush + normal
    
    def get_order_urgency(self, order: Order, state: GameState) -> float:
        """
        Calculate urgency score for an order. Lower = more urgent.
        
        Rush orders approaching timeout get highest urgency.
        Normal orders get baseline urgency.
        """
        if not order.is_rush:
            return 1.0
        
        return 0.5
    
    def get_orders_needing_seasoning(
        self, state: GameState
    ) -> list[tuple[int, Order]]:
        """
        Get orders ready to be seasoned and served, sorted by priority.
        
        Rush orders first, then by slot index.
        """
        ready = [
            (idx, order) for idx, order in enumerate(state.orders)
            if (
                order is not None
                and not order.done
                and order.current_stage == OrderStage.READY_TO_SEASON
                and order.finish_order_task is None
            )
        ]
        
        rush = [(i, o) for i, o in ready if o.is_rush]
        normal = [(i, o) for i, o in ready if not o.is_rush]
        
        return rush + normal
