"""
StockpileFirstStrategy: 优先使用库存的并行策略

与 DefaultStrategy 的区别：
- 把 pull_from_stockpile 提到 cook 之前
- 当库存中有 needed 食材时，直接取用而不是重新烹饪

适用场景：当 stockpile 中积累了较多食材时，减少重复烹饪，加快 assembly 组装。
"""

from __future__ import annotations

from hawarma.agent.strategies.cooking_first_v2 import CookingFirstV2Strategy
from hawarma.agent.unified_state import UnifiedState
from hawarma.agent.agent import Action


class StockpileFirstStrategy(CookingFirstV2Strategy):
    """
    优先使用库存的并行策略。

    决策优先级：
    1. 送餐
    2. 清理过期食材
    3. 移动完成食材到组装站
    4. 从库存取用  ← 提前（相对于 DefaultStrategy）
    5. 开始烹饪
    6. 添加调料
    7. 存入 stockpile
    """

    def decide(self, state: UnifiedState) -> Action | None:
        assembly_ings = [
            ing[0] if isinstance(ing, tuple) else ing
            for ing in state.assembly.ingredients_cookers
        ]

        if action := self._try_clear_assembly(state, assembly_ings):
            return action
        if action := self._try_serve(state, assembly_ings):
            return action
        if action := self._try_clear_expired(state):
            return action
        if action := self._try_move_to_assembly(state, assembly_ings):
            return action
        if action := self._try_pull_from_stockpile(state):
            return action
        if action := self._try_parallel_cooking(state, assembly_ings):
            return action
        if action := self._try_add_condiment(state, assembly_ings):
            return action
        if action := self._try_store_to_stockpile(state):
            return action

        return None
