# 烹饪 Agent 统一架构设计

## 1. 设计原则

### 1.1 核心目标
- **最大化订单完成数量**：在90秒游戏时间内完成尽可能多的订单
- **避免订单超时**：Rush订单40秒，普通订单70秒
- **最大化资源利用率**：4个灶台并行，组装站流水线作业
- **最小化等待时间**：减少所有资源的空闲时间

### 1.2 关键瓶颈
| 资源 | 数量 | 瓶颈影响 |
|------|------|----------|
| 灶台 | 最多4个 | 决定并行烹饪能力 |
| 组装站 | 1 | 主要瓶颈，一次只能处理一份菜品 |
| 库存槽 | 3 | 限制可预存的食材种类 |

### 1.3 设计决策
| 问题 | 决策 |
|------|------|
| Agent类型 | CookingAgent，支持真实游戏环境 |
| 环境接口 | BaseEnvironment抽象基类，GameEnvironment实现 |
| 状态追踪 | 环境层维护状态，操作成功后更新 |
| 决策频率 | 0.05秒决策，0.4-2.0秒自适应扫描 |
| 优化方向 | 并行最大化（同时使用多个灶台） |
| 性能目标 | 90秒内最大化完成订单数和得分 |
| Serve失败处理 | 快速重试机制（依次尝试所有slot） |
| 食材超时防护 | WARN_THRESHOLD=4s，提前存入库存 |

---

## 2. 架构概述

### 2.1 整体架构
```
┌─────────────────────────────────────────────────────────┐
│                    CookingAgent                          │
│  （持有配方数据，执行决策逻辑）                            │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────────┐      ┌──────────────────┐         │
│  │ BaseEnvironment  │◄────►│ CookingAgent    │         │
│  │  (抽象接口)       │      │  (决策逻辑)       │         │
│  └────────┬─────────┘      └──────────────────┘         │
│           │                                              │
│           ▼                                              │
│  GameEnvironment                                      │
│  (真实游戏状态追踪)                                       │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 2.2 组件职责
- **CookingAgent** (`agent/agent.py`)：持有配方数据，执行决策逻辑
- **BaseEnvironment** (`bridge/base_environment.py`)：抽象基类，定义环境交互接口
- **GameEnvironment** (`bridge/environment.py`)：真实游戏环境，维护状态
- **RealGameBridge** (`bridge/bridge.py`)：协调扫描、超时检测、Agent决策三个并行循环

---

## 3. 核心接口定义

### 3.1 BaseEnvironment 抽象基类

`BaseEnvironment` 定义在 `hawarma/bridge/base_environment.py`，包含统一的数据结构和抽象方法。

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CookerState:
    """灶台状态（统一数据结构）"""
    busy: bool = False
    ingredient_name: str | None = None
    cooker_type: str | None = None
    started_at: float | None = None
    done_at: float | None = None
    expired_at: float | None = None
    
    def is_done(self, current_time: float) -> bool:
        """检查烹饪是否已完成"""
        return self.done_at is not None and current_time >= self.done_at
    
    def is_expired(self, current_time: float) -> bool:
        """检查食材是否已过期"""
        return self.expired_at is not None and current_time >= self.expired_at


@dataclass
class AssemblyState:
    """组装站状态"""
    ingredients_cookers: list[tuple[str, str]] = field(default_factory=list)
    target_recipe_slug: str | None = None
    owner_order_id: int | None = None
    condiments: dict[str, int] = field(default_factory=dict)
    
    @property
    def is_free(self) -> bool:
        """组装站是否空闲"""
        return len(self.ingredients_cookers) == 0 and self.target_recipe_slug is None


@dataclass
class StockpileSlot:
    """库存槽位"""
    ingredient_name: str | None = None
    cooker_type: str | None = None
    count: int = 0
    
    def can_add(self, ingredient: str, cooker: str) -> bool:
        """检查是否可以添加食材"""
        if self.ingredient_name is None:
            return True
        return self.ingredient_name == ingredient and self.cooker_type == cooker


class BaseEnvironment(ABC):
    """
    游戏环境抽象基类
    
    定义Agent与环境交互的最小接口。
    GameEnvironment 和 SimulatorEnvironment 都必须实现这些方法。
    """
    
    @property
    @abstractmethod
    def time(self) -> float:
        """当前游戏时间（秒）"""
        pass
    
    @property
    @abstractmethod
    def orders(self) -> list[OrderInfo | None]:
        """
        当前订单列表（4个槽位）
        
        Returns:
            订单列表，每个元素为 None 或 OrderInfo 对象
        """
        pass
    
    @property
    @abstractmethod
    def cookers(self) -> dict[str, CookerState]:
        """
        灶台状态
        
        Returns:
            灶台名称 -> 状态的映射
        """
        pass
    
    @property
    @abstractmethod
    def assembly(self) -> AssemblyState:
        """组装站状态"""
        pass
    
    @property
    @abstractmethod
    def stockpile(self) -> dict[str, StockpileSlot]:
        """
        库存状态
        
        Returns:
            库存槽位名称 -> 状态的映射
        """
        pass
    
    @abstractmethod
    def is_in_animation_window(self) -> bool:
        """是否在动画窗口期间（禁止送餐操作）"""
        pass
    
    @abstractmethod
    def start_cooking(self, ingredient: str, cooker: str, duration: float) -> bool:
        """
        开始烹饪
        
        Args:
            ingredient: 食材名称
            cooker: 灶台名称
            duration: 烹饪时长（秒）
            
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    def move_to_assembly(self, cooker: str) -> bool:
        """
        将灶台完成的食材移动到组装站
        
        Args:
            cooker: 灶台名称
            
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    def move_to_stockpile(self, cooker: str, slot: str) -> bool:
        """
        将灶台完成的食材移动到库存
        
        Args:
            cooker: 灶台名称
            slot: 库存槽位名称
            
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    def pull_from_stockpile(self, slot: str) -> bool:
        """
        从库存取用食材到组装站
        
        Args:
            slot: 库存槽位名称
            
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    def add_condiment(self, condiment: str) -> bool:
        """
        添加调料到组装站
        
        Args:
            condiment: 调料名称
            
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    def serve_order(self, slot_idx: int) -> bool:
        """
        送餐
        
        Args:
            slot_idx: 订单槽位索引（0-3）
            
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    def clear_cooker(self, cooker: str) -> bool:
        """
        清理灶台（丢弃过期食材）
        
        Args:
            cooker: 灶台名称
            
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    def clear_assembly(self) -> bool:
        """
        清空组装站（丢弃食材）
        
        Returns:
            是否成功
        """
        pass
```

### 3.2 Action 类型定义

定义在 `hawarma/agent/agent.py`：

```python
from dataclasses import dataclass


@dataclass
class Action:
    """动作基类"""
    pass


@dataclass
class CookAction(Action):
    """烹饪动作"""
    ingredient: str
    cooker: str
    duration: float
    order_id: int | None = None


@dataclass
class MoveToAssemblyAction(Action):
    """移动到组装站"""
    cooker: str
    order_id: int | None = None


@dataclass
class MoveToStockpileAction(Action):
    """移动到库存"""
    cooker: str
    slot: str


@dataclass
class PullFromStockpileAction(Action):
    """从库存取用"""
    slot: str
    ingredient: str


@dataclass
class AddCondimentAction(Action):
    """添加调料"""
    condiment: str


@dataclass
class ServeOrderAction(Action):
    """送餐"""
    slot_idx: int


@dataclass
class ClearCookerAction(Action):
    """清理灶台"""
    cooker: str


@dataclass
class ClearAssemblyAction(Action):
    """清空组装站（丢弃食材）"""
    pass
```



## 4. Agent 核心设计

### 4.1 CookingAgent 类

实际实现位置：`hawarma/agent/agent.py`

```python
class CookingAgent:
    """
    统一烹饪 Agent
    
    贪心策略（按优先级）：
    1. 检查过期组装站并清空
    2. 检查停滞组装站并清空
    3. 送餐（动画窗口期间跳过）
    4. 清理过期食材
    5. 移动完成食材到组装站
    6. 开始烹饪（动画窗口期间允许）
    7. 添加调料
    8. 存入库存
    9. 从库存取用
    """
    
    def __init__(self, env, recipes: list):
        self.env = env
        self.recipes = recipes
        
        # 配方映射
        self._recipe_by_slug: dict = {}
        self._ingredient_info_dict: dict[str, tuple[str, float]] = {}
        self._recipe_condiments: dict[str, dict[str, int]] = {}
        
        # 构建食材信息映射
        self._build_ingredient_info()
        
        # 统计
        self.stats = {
            "orders_served": 0,
            "total_score": 0,
            "orders_timeout": 0,
            "actions_taken": 0,
        }
        
        # 停滞检测
        self._consecutive_none = 0
        self._stagnation_warned = False
        self._assembly_stale_since: float | None = None
    
    def step(self) -> Action | None:
        """
        单步决策：多订单并行策略
        
        优先级顺序：
        0. 检查过期组装站 (_check_and_clear_expired_assembly)
        0.5. 检查停滞组装站 (_check_stale_assembly)
        1. 送餐 (_try_serve) - 动画窗口期间跳过
        2. 清理过期食材 (_try_clear_expired)
        3. 移动完成食材 (_try_move_to_assembly)
        4. 开始烹饪 (_try_parallel_cooking) - 动画窗口期间允许
        5. 添加调料 (_try_add_condiment)
        6. 存入库存 (_try_store_to_stockpile)
        7. 从库存取用 (_try_pull_from_stockpile)
        """
        # 0. 检查过期组装站
        if action := self._check_and_clear_expired_assembly():
            return action
        
        # 0.5 检查停滞组装站
        if action := self._check_stale_assembly():
            return action
        
        # 1. 送餐
        if action := self._try_serve():
            return action
        
        # 2. 清理过期食材
        if action := self._try_clear_expired():
            return action
        
        # 3. 移动完成食材
        if action := self._try_move_to_assembly():
            return action
        
        # 4. 开始烹饪
        if action := self._try_parallel_cooking():
            return action
        
        # 5. 添加调料
        if action := self._try_add_condiment():
            return action
        
        # 6. 存入库存
        if action := self._try_store_to_stockpile():
            return action
        
        # 7. 从库存取用
        if action := self._try_pull_from_stockpile():
            return action
        
        return None
    
    # ========================================================================
    # 动作尝试方法
    # ========================================================================
    
    def _check_and_clear_expired_assembly(self) -> ClearAssemblyAction | None:
        """检查组装站是否属于已超时订单，如果是则清空"""
        for order in self.env.orders:
            if order and not order.done:
                target_slug = self.env.assembly.target_recipe_slug
                if target_slug and target_slug == order.recipe_slug:
                    if self.env.time >= order.timeout_at:
                        logger.warning(
                            f"Clearing assembly: belongs to expired order {order.recipe_slug}"
                        )
                        return ClearAssemblyAction()
        return None
    
    def _check_stale_assembly(self) -> ClearAssemblyAction | None:
        """检查组装站是否长时间停滞（食材齐全但调料缺失）"""
        STALE_THRESHOLD = 15.0
        assembly = self.env.assembly
        
        if not assembly.ingredients_cookers or not assembly.target_recipe_slug:
            self._assembly_stale_since = None
            return None
        
        recipe = self._recipe_by_slug.get(assembly.target_recipe_slug)
        if not recipe:
            self._assembly_stale_since = None
            return None
        
        # 检查食材是否齐全
        if not self._ingredients_match(assembly.ingredients_cookers, recipe):
            self._assembly_stale_since = None
            return None
        
        # 检查调料是否完整
        condiments_needed = self._recipe_condiments.get(assembly.target_recipe_slug, {})
        if self._condiments_complete(assembly.condiments, condiments_needed):
            self._assembly_stale_since = None
            return None
        
        # 调料不完整，检查是否超时
        if self._assembly_stale_since is None:
            self._assembly_stale_since = self.env.time
            return None
        
        if self.env.time - self._assembly_stale_since >= STALE_THRESHOLD:
            logger.warning(
                f"Clearing stale assembly: {assembly.ingredients_cookers}, "
                f"target={assembly.target_recipe_slug}, "
                f"stagnant for {self.env.time - self._assembly_stale_since:.1f}s"
            )
            return ClearAssemblyAction()
        
        return None
    
    def _try_serve(self) -> ServeOrderAction | None:
        """送餐：组装站菜品匹配某个订单时立即送"""
        if self.env.is_in_animation_window():
            return None
        
        assembly = self.env.assembly
        if not assembly.ingredients_cookers:
            return None
        
        target_slug = assembly.target_recipe_slug
        
        # 按优先级遍历订单：rush 优先，timeout 近的优先
        for slot_idx, order in self._prioritized_orders():
            if order is None or order.done:
                continue
            
            # 如果组装站有目标配方，必须匹配
            if target_slug and target_slug != order.recipe_slug:
                continue
            
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe and self._ingredients_match(assembly.ingredients_cookers, recipe):
                # 检查调料是否齐全
                condiments_needed = self._recipe_condiments.get(order.recipe_slug, {})
                if self._condiments_complete(assembly.condiments, condiments_needed):
                    return ServeOrderAction(slot_idx=slot_idx)
        
        return None
    
    def _try_add_condiment(self) -> AddCondimentAction | None:
        """添加调料：只有当食材齐全时才添加调料"""
        assembly = self.env.assembly
        target_slug = assembly.target_recipe_slug
        
        # 如果没有目标配方，尝试从食材推断
        if not target_slug:
            target_slug = self._infer_recipe_from_assembly()
            if not target_slug:
                return None
        
        recipe = self._recipe_by_slug.get(target_slug)
        if not recipe:
            return None
        
        # 检查食材是否齐全
        if not self._ingredients_match(assembly.ingredients_cookers, recipe):
            return None
        
        condiments_needed = self._recipe_condiments.get(target_slug, {})
        if not condiments_needed:
            return None
        
        for condiment, required in condiments_needed.items():
            current = self.env.get_condiment_count(condiment)
            if current < required:
                return AddCondimentAction(condiment=condiment)
        
        return None
    
    def _try_move_to_assembly(self) -> MoveToAssemblyAction | None:
        """尝试将完成的食材移到组装站"""
        # 获取当前需要的食材（基于组装站目标配方或全部订单）
        needed = self._get_needed_ingredients()
        
        for cooker_name, cooker in self.env.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            
            # 检查是否完成烹饪
            if self.env.time < cooker.done_at:
                continue
            
            # 检查是否过期
            if cooker.is_expired(self.env.time):
                continue
            
            # 检查是否是需要的食材
            if cooker.ingredient_name not in needed:
                continue
            
            # 检查组装站是否可以接受
            if self._can_add_to_assembly(cooker.ingredient_name, cooker.cooker_type):
                return MoveToAssemblyAction(cooker=cooker_name)
        
        return None
    
    def _try_parallel_cooking(self) -> CookAction | None:
        """尝试开始烹饪（并行最大化，动画窗口期间允许）"""
        free_cookers = self._get_free_cookers()
        if not free_cookers:
            return None
        
        # 获取所有订单需要的食材
        needed = self._get_all_needed_ingredients()
        
        # 优先烹饪订单需要的食材（按订单优先级）
        for ing_name in needed:
            if ing_name not in self._ingredient_info:
                continue
            
            cooker_type, duration = self._ingredient_info[ing_name]
            
            # 检查灶台是否空闲
            if cooker_type not in free_cookers:
                continue
            
            # 检查是否已在烹饪
            if self._is_cooking(ing_name):
                continue
            
            # 检查库存是否有（优先使用库存）
            if self._has_in_stockpile(ing_name):
                continue
            
            return CookAction(
                ingredient=ing_name,
                cooker=cooker_type,
                duration=duration
            )
        
        # 空闲灶台预烹饪高频食材（如果配置了）
        for cooker_type in free_cookers:
            if action := self._try_precook(cooker_type):
                return action
        
        return None
    
    def _try_clear_expired(self) -> ClearCookerAction | None:
        """尝试清理过期食材"""
        WARN_THRESHOLD = 4.0  # 提前警告阈值
        
        for cooker_name, cooker in self.env.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            
            time_since_done = self.env.time - cooker.done_at
            
            # 超过警告阈值，存入库存
            if time_since_done > WARN_THRESHOLD:
                if self._try_store_to_stockpile_for_cooker(cooker_name):
                    return None  # 已处理，继续其他检查
            
            # 已过期，清理
            if cooker.is_expired(self.env.time):
                return ClearCookerAction(cooker=cooker_name)
        
        return None
    
    def _try_store_to_stockpile(self) -> MoveToStockpileAction | None:
        """尝试将完成的食材存入库存"""
        for cooker_name, cooker in self.env.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            
            if self.env.time < cooker.done_at:
                continue
            
            # 找到合适的库存槽位
            slot = self._find_available_slot(cooker.ingredient_name, cooker.cooker_type)
            if slot:
                return MoveToStockpileAction(
                    cooker=cooker_name,
                    slot=slot
                )
        
        return None
    
    def _try_pull_from_stockpile(self) -> PullFromStockpileAction | None:
        """尝试从库存取用食材到组装站"""
        assembly = self.env.assembly
        
        # 组装站空闲时不允许取用
        if assembly.is_free:
            return None
        
        needed = self._get_needed_ingredients()
        
        for slot_name, slot in self.env.stockpile.items():
            if slot.ingredient_name in needed and slot.count > 0:
                return PullFromStockpileAction(
                    slot=slot_name,
                    ingredient=slot.ingredient_name
                )
        
        return None
    
    def _try_precook(self, cooker_type: str) -> Optional[CookAction]:
        """预烹饪高频食材"""
        # 动态确定需要补货的食材
        for slot_name, slot in self.env.stockpile.items():
            if slot.cooker_type == cooker_type and slot.count < 2:
                if slot.ingredient_name:
                    _, duration = self.ingredient_info.get(
                        slot.ingredient_name, (None, 0)
                    )
                    if duration > 0:
                        return CookAction(
                            ingredient=slot.ingredient_name,
                            cooker=cooker_type,
                            duration=duration
                        )
        
        return None
    
    # ========================================================================
    # 辅助方法
    # ========================================================================
    
    def _get_needed_ingredients(self) -> list[str]:
        """获取当前组装所需的食材（基于组装站目标配方）"""
        assembly = self.env.assembly
        
        if assembly.target_recipe_slug:
            recipe = self._recipe_by_slug.get(assembly.target_recipe_slug)
            if recipe:
                present = set(
                    ing[0] if isinstance(ing, tuple) else ing
                    for ing in assembly.ingredients_cookers
                )
                raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
                return [ing for ing in raw if ing not in present]
        
        return []
    
    def _get_all_needed_ingredients(self) -> list[str]:
        """获取所有活跃订单需要的食材（去重，按优先级排序）"""
        needed = []
        seen = set()
        
        for _, order in self._prioritized_orders():
            if order is None or order.done:
                continue
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe:
                raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
                for ing in raw:
                    if ing not in seen:
                        needed.append(ing)
                        seen.add(ing)
        
        return needed
    
    def _ingredients_match(
        self, assembly_ingredients, recipe
    ) -> bool:
        """检查组装站食材是否匹配配方"""
        # 处理 assembly.ingredients_cookers 格式
        actual = [
            ing[0] if isinstance(ing, tuple) else ing
            for ing in assembly_ingredients
        ]
        
        if hasattr(recipe, "slug") or isinstance(recipe, dict):
            expected = self._get_recipe_attr(recipe, "raw_ingredients", [])
        else:
            expected = recipe.get("raw_ingredients", [])
        
        return sorted(actual) == sorted(expected)
    
    def _condiments_complete(
        self, current: dict[str, int], needed: dict[str, int]
    ) -> bool:
        """检查调料是否齐全"""
        for condiment, required in needed.items():
            if current.get(condiment, 0) < required:
                return False
        return True
    
    def _infer_recipe_from_assembly(self) -> str | None:
        """从组装站食材推断目标配方"""
        assembly = self.env.assembly
        ingredients = [
            ing[0] if isinstance(ing, tuple) else ing
            for ing in assembly.ingredients_cookers
        ]
        
        for _, order in self._prioritized_orders():
            if order is None or order.done:
                continue
            recipe = self._recipe_by_slug.get(order.recipe_slug)
            if recipe and self._ingredients_match(assembly.ingredients_cookers, recipe):
                return order.recipe_slug
        
        # 尝试从所有配方中推断
        for slug, recipe in self._recipe_by_slug.items():
            if self._ingredients_match(assembly.ingredients_cookers, recipe):
                return slug
        
        return None
    
    def _prioritized_orders(self) -> list[tuple[int, OrderInfo | None]]:
        """返回按优先级排序的订单（rush优先，timeout近优先）"""
        orders = []
        for i, o in enumerate(self.env.orders):
            if o and not o.done:
                orders.append((i, o))
        
        # 排序：rush优先，然后按timeout_at升序
        orders.sort(
            key=lambda x: (not x[1].is_rush, x[1].timeout_at)
        )
        return orders
    
    def _get_free_cookers(self) -> list[str]:
        """获取空闲灶台列表"""
        return [
            name for name, cooker in self.env.cookers.items()
            if not cooker.busy
        ]
    
    def _is_cooking(self, ingredient: str) -> bool:
        """检查食材是否正在烹饪"""
        for cooker in self.env.cookers.values():
            if cooker.busy and cooker.ingredient_name == ingredient:
                return True
        return False
    
    def _has_in_stockpile(self, ingredient: str) -> bool:
        """检查库存是否有该食材"""
        for slot in self.env.stockpile.values():
            if slot.ingredient_name == ingredient and slot.count > 0:
                return True
        return False
    
    def _find_available_slot(
        self, ingredient: str, cooker_type: str
    ) -> str | None:
        """找到可用的库存槽位"""
        for slot_name, slot in self.env.stockpile.items():
            if slot.can_add(ingredient, cooker_type):
                if slot.count < 5:  # 最大库存限制
                    return slot_name
        return None
    
    def _can_add_to_assembly(
        self, ingredient: str, cooker_type: str
    ) -> bool:
        """检查食材是否可以添加到组装站"""
        assembly = self.env.assembly
        
        # 组装站为空
        if assembly.is_free:
            return True
        
        # 检查配方是否存在
        if not assembly.target_recipe_slug:
            return False
        
        recipe = self._recipe_by_slug.get(assembly.target_recipe_slug)
        if not recipe:
            return False
        
        # 检查食材是否在配方中
        raw = self._get_recipe_attr(recipe, "raw_ingredients", [])
        if ingredient not in raw:
            return False
        
        # 检查是否已有该食材
        present = set(
            ing[0] if isinstance(ing, tuple) else ing
            for ing in assembly.ingredients_cookers
        )
        return ingredient not in present
```

---

## 5. 库存管理策略

### 5.1 动态槽位分配

实际实现使用 `StockpileSlot` 的 `can_add()` 方法进行动态分配：

```python
# hawarma/bridge/base_environment.py
@dataclass
class StockpileSlot:
    """库存槽位"""
    ingredient_name: str | None = None
    cooker_type: str | None = None
    count: int = 0
    
    def can_add(self, ingredient: str, cooker: str) -> bool:
        """检查是否可以添加食材"""
        if self.ingredient_name is None:
            return True
        return self.ingredient_name == ingredient and self.cooker_type == cooker
    
    def add(self, ingredient: str, cooker: str) -> bool:
        """添加食材"""
        if not self.can_add(ingredient, cooker):
            return False
        if self.ingredient_name is None:
            self.ingredient_name = ingredient
            self.cooker_type = cooker
        self.count += 1
        return True
```

### 5.2 补货决策

实际实现在 `_try_store_to_stockpile()` 和 `_try_precook()` 中：

```python
# 存入库存的判断条件：
# 1. 组装站有目标配方时，非目标食材存入库存
# 2. 食材已烹饪完成且不在当前需求中
# 3. 通过 StockpileSlot.can_add() 检查槽位兼容性

# 预烹饪判断（在 _try_precook 中）：
# 1. 检查库存槽位 count < 5
# 2. 优先补充同槽位数量（WARN_THRESHOLD=4s 提前存入）
```

### 5.3 食材过期防护

```python
# 在 _try_clear_expired() 中：
WARN_THRESHOLD = 4.0  # 提前警告阈值

time_since_done = self.env.time - cooker.done_at

# 超过警告阈值，主动存入库存
if time_since_done > WARN_THRESHOLD:
    self._try_store_to_stockpile_for_cooker(cooker_name)

# 已过期（5秒），清理
if cooker.is_expired(self.env.time):
    return ClearCookerAction(cooker=cooker_name)
```

## 6. 并行烹饪策略

### 6.1 核心思想

实际实现在 `_try_parallel_cooking()` 中：

```python
def _try_parallel_cooking(self) -> CookAction | None:
    """尝试开始烹饪（并行最大化，动画窗口期间允许）"""
    free_cookers = self._get_free_cookers()
    if not free_cookers:
        return None
    
    # 获取所有订单需要的食材
    needed = self._get_all_needed_ingredients()
    
    # 优先烹饪订单需要的食材（按订单优先级）
    for ing_name in needed:
        if ing_name not in self._ingredient_info:
            continue
        
        cooker_type, duration = self._ingredient_info[ing_name]
        
        # 检查灶台是否空闲
        if cooker_type not in free_cookers:
            continue
        
        # 检查是否已在烹饪
        if self._is_cooking(ing_name):
            continue
        
        # 检查库存是否有（优先使用库存）
        if self._has_in_stockpile(ing_name):
            continue
        
        return CookAction(
            ingredient=ing_name,
            cooker=cooker_type,
            duration=duration
        )
    
    # 空闲灶台预烹饪高频食材（如果配置了）
    for cooker_type in free_cookers:
        if action := self._try_precook(cooker_type):
            return action
    
    return None
```

### 6.2 策略要点

1. **并行最大化**：同时启动所有空闲灶台
2. **订单优先**：优先烹饪活跃订单需要的食材
3. **动画窗口允许**：烹饪操作不受动画窗口限制
4. **预烹饪机制**：空闲灶台烹饪库存槽位中需要补货的食材

---

## 7. 测试框架

### 7.1 当前状态

测试文件位于 `tests/` 目录：
- `tests/test_capture_speed.py` - Airtest 截图速度测试
- `tests/test_rush_detection.py` - Rush 订单检测测试
- `tests/test_timer_detection.py` - 定时器检测测试
- `tests/test_simulator_environment.py` - SimulatorEnvironment 适配器测试

### 7.2 测试原则

- 使用真实游戏环境或 SimulatorEnvironment 进行测试
- 重点测试状态转换序列（如 assembly_deadlock_analysis.md 中的教训）
- 测试需要覆盖边界情况和错误恢复

---

## 8. 当前文件结构

### 8.1 实际文件结构

```
hawarma/
├── agent/
│   ├── __init__.py          # Agent模块导出
│   ├── agent.py             # CookingAgent核心类
│   └── ARCHITECTURE.md     # Agent架构文档
├── bridge/
│   ├── __init__.py
│   ├── base_environment.py  # BaseEnvironment抽象基类 + 数据结构
│   ├── environment.py       # GameEnvironment（真实游戏状态追踪）
│   ├── scanner.py           # OrderScanner（订单检测）
│   ├── ui_runner.py         # UIRunner（UI操作执行）
│   ├── bridge.py            # RealGameBridge（双循环协调）
│   ├── assembly_verifier.py # AssemblyVerifier（组装站验证）
│   └── simulator_environment.py # SimulatorEnvironment（模拟器适配器）
├── models.py                # Recipe, Order等数据模型
├── config.py                # AppConfig配置管理
└── services/
    └── recipe_manager.py    # RecipeManager（配方数据加载）
```

### 8.2 核心组件说明

1. **CookingAgent** (`agent/agent.py`)
   - 7级优先级贪婪策略
   - 阶段驱动决策（NOT_READY/NEEDS_SEASONING/READY）
   - 停滞检测和诊断

2. **BaseEnvironment** (`bridge/base_environment.py`)
   - 抽象基类定义环境接口
   - CookerState, AssemblyState, StockpileSlot数据类

3. **GameEnvironment** (`bridge/environment.py`)
   - 真实游戏状态追踪
   - 订单管理、灶台状态、组装站状态、库存状态

4. **RealGameBridge** (`bridge/bridge.py`)
   - 3个并行asyncio循环（scan/timeout/agent）
   - 动作执行和验证

---

## 9. 性能优化

### 9.1 当前性能指标（50局平均）

| 指标 | 值 | 说明 |
|------|-----|------|
| 订单完成数 | 14.7个 | 平均每90秒完成订单数 |
| 超时率 | 0.0% | 订单超时比例 |
| 平均得分 | 2620分 | 每局游戏的平均得分 |
| 效率 | 82% | 实际/理论最大值（18个） |

### 9.2 经验教训

**有效优化**：
1. **烹饪优先策略**：动画窗口期间允许烹饪，灶台尽早启动（+11.2%）
2. **动态扫描频率**：根据灶台/订单状态调整扫描间隔
3. **送餐验证机制**：快速重试取代扫描匹配，避免动画窗口问题
4. **停滞检测**：连续无动作时输出诊断日志，便于排查问题
5. **组装站超时清理**：食材齐全但调料缺失超时后自动清空
6. **食材过期防护**：WARN_THRESHOLD=4s 提前存入库存

**无效优化**：
1. **预烹饪到assembly**：与订单不匹配，导致停滞（-30%）
2. **预烹饪到stockpile**：额外开销，库存管理更复杂（-2%）

**关键发现**：
- 按需响应策略已经足够好（82%效率）
- 灶台是异步的，尽早开始烹饪是关键
- 状态完整性比逻辑正确性更重要（见 assembly_deadlock_analysis.md）
- 日志要覆盖"为什么没做"，而不仅仅是"做了什么"

### 9.3 优化方向

已实现的优化：
1. **动态swipe参数**：根据距离调整送餐参数
2. **前瞻性烹饪**：基于订单紧迫度提前烹饪
3. **Serve失败重试**：依次尝试所有slot，无需扫描匹配
4. **多点snapshot验证**：避免单次截图的时效性问题

待探索的优化：
- 分析具体哪些订单导致超时
- 针对性优化复杂订单的处理
- 进一步优化扫描和决策的配合

---

## 10. 总结

高效Agent的核心策略：

1. **统一架构**：CookingAgent + BaseEnvironment 接口，支持真实游戏和模拟器
2. **阶段驱动**：NOT_READY → NEEDS_SEASONING → READY
3. **烹饪优先**：动画窗口期间允许烹饪，让灶台尽早开始异步工作
4. **多层防御**：环境层预防 + Agent 层恢复（见 assembly_deadlock_analysis.md）
5. **诊断友好**：停滞检测、状态日志、动作记录

关键成功因素：
- 让灶台尽早开始异步工作
- 保持状态完整性（target_recipe_slug 等关键字段）
- 从实际游戏反馈中迭代优化
