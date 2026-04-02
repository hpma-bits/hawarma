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
| 灶台 | 4 | 决定并行烹饪能力 |
| 组装站 | 1 | 主要瓶颈，一次只能处理一份菜品 |
| 库存槽 | 3 | 限制可预存的食材种类 |

### 1.3 设计决策
| 问题 | 决策 |
|------|------|
| Agent类型 | 统一Agent，支持游戏环境和模拟器两种交互模式 |
| 状态追踪 | 信任操作成功，不添加验证机制（先实现基本功能） |
| 决策频率 | 需要根据实际测试调整（目标：0.1秒决策，0.5秒扫描） |
| 优化方向 | 并行最大化（同时使用4个灶台） |
| 性能目标 | 优化平均分，而非单纯追求订单数量 |

---

## 2. 架构概述

### 2.1 整体架构
```
┌─────────────────────────────────────────────────────────┐
│                    CookingAgent                          │
│  （统一Agent，支持两种环境交互）                           │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────────┐      ┌──────────────────┐         │
│  │ BaseEnvironment  │◄────►│ AgentCore        │         │
│  │  (抽象接口)       │      │  (决策逻辑)       │         │
│  └────────┬─────────┘      └──────────────────┘         │
│           │                                              │
│  ┌────────┴─────────┐                                    │
│  │                  │                                    │
│  ▼                  ▼                                    │
│ GameEnvironment   SimulatorEnvironment                   │
│  (真实游戏)        (模拟测试)                             │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 2.2 组件职责
- **CookingAgent**：统一Agent类，持有配方数据，执行决策逻辑
- **BaseEnvironment**：抽象基类，定义环境交互接口
- **GameEnvironment**：真实游戏环境，通过UI操作控制
- **SimulatorEnvironment**：模拟器环境，用于测试和算法优化
- **AgentCore**：核心决策逻辑，包含订单优先级、灶台分配、库存管理

---

## 3. 核心接口定义

### 3.1 BaseEnvironment 抽象基类

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class CookerState:
    """灶台状态"""
    busy: bool = False
    ingredient_name: Optional[str] = None
    cooker_type: Optional[str] = None
    started_at: Optional[float] = None
    done_at: Optional[float] = None


@dataclass
class AssemblyState:
    """组装站状态"""
    ingredients: list[str] = None
    target_recipe_slug: Optional[str] = None
    order_id: Optional[int] = None
    
    def __post_init__(self):
        if self.ingredients is None:
            self.ingredients = []


@dataclass
class StockpileSlot:
    """库存槽位"""
    ingredient_name: Optional[str] = None
    cooker_type: Optional[str] = None
    count: int = 0


class BaseEnvironment(ABC):
    """
    游戏环境抽象基类
    
    定义Agent与环境交互的最小接口。
    GameEnvironment和SimulatorEnvironment都必须实现这些方法。
    """
    
    @property
    @abstractmethod
    def time(self) -> float:
        """当前游戏时间（秒）"""
        pass
    
    @property
    @abstractmethod
    def orders(self) -> list[Optional[dict]]:
        """
        当前订单列表（4个槽位）
        
        Returns:
            订单列表，每个元素为None或包含recipe、is_rush等信息的字典
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
```

### 3.2 Action 类型定义

```python
from dataclasses import dataclass
from typing import Optional


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
    order_id: Optional[int] = None  # 关联的订单ID（可选）


@dataclass
class MoveToAssemblyAction(Action):
    """移动到组装站"""
    cooker: str
    order_id: Optional[int] = None


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
```

---

## 4. Agent 核心设计

### 4.1 CookingAgent 统一类

```python
class CookingAgent:
    """
    统一烹饪Agent
    
    支持与GameEnvironment（真实游戏）和SimulatorEnvironment（模拟测试）交互。
    在模拟环境中测试和改进算法，然后用于真实环境。
    """
    
    def __init__(self, env: BaseEnvironment, recipes: list[Recipe]):
        """
        初始化Agent
        
        Args:
            env: 游戏环境（真实或模拟）
            recipes: 配方列表
        """
        self.env = env
        self.recipes = {r.slug: r for r in recipes}
        
        # 食材 -> (灶台, 时长) 映射
        self.ingredient_info: dict[str, tuple[str, float]] = {}
        for recipe in recipes:
            for i, ing in enumerate(recipe.raw_ingredients):
                cooker = recipe.cookers[i] if i < len(recipe.cookers) else recipe.cookers_layout[i]
                duration = recipe.cook_durations[i]
                self.ingredient_info[ing] = (cooker, duration)
        
        # 库存槽位分配（动态计算）
        self.stockpile_assignments: dict[str, str] = {}  # slot -> ingredient
        
        # 统计信息
        self.stats = {
            "orders_served": 0,
            "total_score": 0,
            "actions_taken": 0,
        }
    
    def run(self, tick_interval: float = 0.1) -> dict:
        """
        运行完整游戏
        
        Args:
            tick_interval: 决策间隔（秒）
            
        Returns:
            游戏统计
        """
        while not self._is_game_over():
            self.step()
            # 注意：真实环境和模拟环境的时间推进方式不同
            # 真实环境：time.sleep()
            # 模拟环境：env.tick()
        return self.get_stats()
    
    def step(self) -> Optional[Action]:
        """
        单步决策：选择并执行最优动作
        
        Returns:
            执行的动作，如果没有动作可执行则返回None
        """
        # 1. 送餐（最高优先级）
        if action := self._try_serve():
            return action
        
        # 2. 添加调料
        if action := self._try_add_condiment():
            return action
        
        # 3. 从灶台移动到组装站
        if action := self._try_move_to_assembly():
            return action
        
        # 4. 从库存取用到组装站
        if action := self._try_pull_from_stockpile():
            return action
        
        # 5. 开始烹饪（并行最大化）
        if action := self._try_start_cooking():
            return action
        
        # 6. 清理过期食材
        if action := self._try_clear_expired():
            return action
        
        # 7. 多余食材存入库存
        if action := self._try_store_to_stockpile():
            return action
        
        return None
    
    # ========================================================================
    # 动作尝试方法
    # ========================================================================
    
    def _try_serve(self) -> Optional[ServeOrderAction]:
        """尝试送餐"""
        if self.env.is_in_animation_window():
            return None
        
        assembly = self.env.assembly
        if not assembly.ingredients:
            return None
        
        # 找到匹配的订单
        for slot_idx, order in enumerate(self.env.orders):
            if order is None:
                continue
            
            # 检查食材是否匹配
            if self._ingredients_match(assembly.ingredients, order["recipe"]):
                return ServeOrderAction(slot_idx=slot_idx)
        
        return None
    
    def _try_add_condiment(self) -> Optional[AddCondimentAction]:
        """尝试添加调料"""
        assembly = self.env.assembly
        if not assembly.target_recipe_slug:
            return None
        
        recipe = self.recipes.get(assembly.target_recipe_slug)
        if not recipe:
            return None
        
        # 检查是否需要添加调料
        for condiment, required_count in recipe.condiments.items():
            # TODO: 检查当前已添加数量
            # 需要环境提供查询当前调料数量的接口
            pass
        
        return None
    
    def _try_move_to_assembly(self) -> Optional[MoveToAssemblyAction]:
        """尝试将完成的食材从灶台移到组装站"""
        needed = self._get_needed_ingredients()
        
        for cooker_name, cooker in self.env.cookers.items():
            if not cooker.busy or cooker.done_at is None:
                continue
            
            # 检查是否完成烹饪
            if self.env.time < cooker.done_at:
                continue
            
            # 检查是否过期
            # TODO: 添加过期检查
            
            # 检查是否是需要的食材
            if cooker.ingredient_name not in needed:
                continue
            
            # 检查组装站是否可以接受
            if self._can_add_to_assembly(cooker.ingredient_name):
                return MoveToAssemblyAction(cooker=cooker_name)
        
        return None
    
    def _try_pull_from_stockpile(self) -> Optional[PullFromStockpileAction]:
        """尝试从库存取用食材到组装站"""
        if not self._is_assembly_free():
            return None
        
        needed = self._get_needed_ingredients()
        
        for slot_name, slot in self.env.stockpile.items():
            if slot.ingredient_name in needed and slot.count > 0:
                return PullFromStockpileAction(
                    slot=slot_name,
                    ingredient=slot.ingredient_name
                )
        
        return None
    
    def _try_start_cooking(self) -> Optional[CookAction]:
        """尝试开始烹饪（并行最大化）"""
        free_cookers = self._get_free_cookers()
        if not free_cookers:
            return None
        
        # 获取需要烹饪的食材（按优先级）
        to_cook = self._get_ingredients_to_cook()
        
        # 优先烹饪订单需要的食材
        for ing_name in to_cook:
            if ing_name not in self.ingredient_info:
                continue
            
            cooker_type, duration = self.ingredient_info[ing_name]
            
            # 检查灶台是否空闲
            if cooker_type in free_cookers:
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
        
        # 空闲灶台预烹饪高频食材
        for cooker_type in free_cookers:
            if action := self._try_precook(cooker_type):
                return action
        
        return None
    
    def _try_clear_expired(self) -> Optional[ClearCookerAction]:
        """尝试清理过期食材"""
        for cooker_name, cooker in self.env.cookers.items():
            if cooker.busy and cooker.done_at:
                # 检查是否过期（5秒后过期）
                if self.env.time >= cooker.done_at + 5.0:
                    return ClearCookerAction(cooker=cooker_name)
        
        return None
    
    def _try_store_to_stockpile(self) -> Optional[MoveToStockpileAction]:
        """尝试将多余食材存入库存"""
        # 组装站未被占用时不存储
        assembly = self.env.assembly
        if not assembly.ingredients and not assembly.target_recipe_slug:
            return None
        
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
        """获取当前组装所需的食材"""
        assembly = self.env.assembly
        
        if assembly.target_recipe_slug:
            recipe = self.recipes.get(assembly.target_recipe_slug)
            if recipe:
                present = set(assembly.ingredients)
                return [ing for ing in recipe.raw_ingredients if ing not in present]
        
        # 组装站为空，返回第一个订单的第一个食材
        for order in self.env.orders:
            if order:
                return order["recipe"].raw_ingredients
        
        return []
    
    def _get_ingredients_to_cook(self) -> list[str]:
        """获取需要烹饪的食材列表（按优先级排序）"""
        needed = self._get_needed_ingredients()
        result = []
        
        for ing_name in needed:
            # 检查是否已在灶台
            if self._is_cooking(ing_name):
                continue
            
            # 检查库存是否有
            if self._has_in_stockpile(ing_name):
                continue
            
            result.append(ing_name)
        
        return result
    
    def _can_add_to_assembly(self, ingredient: str) -> bool:
        """检查食材是否可以添加到组装站"""
        assembly = self.env.assembly
        
        # 组装站为空
        if not assembly.ingredients and not assembly.target_recipe_slug:
            return True
        
        # 检查配方是否存在
        if not assembly.target_recipe_slug:
            return False
        
        recipe = self.recipes.get(assembly.target_recipe_slug)
        if not recipe:
            return False
        
        # 检查食材是否在配方中
        if ingredient not in recipe.raw_ingredients:
            return False
        
        # 检查是否已有该食材
        return ingredient not in assembly.ingredients
    
    def _is_assembly_free(self) -> bool:
        """组装站是否空闲"""
        assembly = self.env.assembly
        return not assembly.ingredients and not assembly.target_recipe_slug
    
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
    
    def _get_free_cookers(self) -> list[str]:
        """获取空闲灶台列表"""
        return [name for name, cooker in self.env.cookers.items() if not cooker.busy]
    
    def _find_available_slot(self, ingredient: str, cooker_type: str) -> Optional[str]:
        """找到可用的库存槽位"""
        for slot_name, slot in self.env.stockpile.items():
            if slot.ingredient_name == ingredient and slot.cooker_type == cooker_type:
                if slot.count < 5:  # 最大库存限制
                    return slot_name
        return None
    
    def _ingredients_match(self, actual: list[str], recipe) -> bool:
        """检查食材是否匹配配方"""
        if hasattr(recipe, 'raw_ingredients'):
            expected = recipe.raw_ingredients
        else:
            expected = recipe.get('raw_ingredients', [])
        
        return sorted(actual) == sorted(expected)
    
    def _is_game_over(self) -> bool:
        """游戏是否结束"""
        # 需要环境提供游戏结束的判断
        return False
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return self.stats
```

---

## 5. 库存槽位分配算法

### 5.1 动态分配策略

```python
def calculate_stockpile_assignments(
    recipes: list[Recipe],
    current_orders: list[Optional[dict]],
    stockpile_slots: int = 3
) -> dict[str, str]:
    """
    动态计算库存槽位分配
    
    评分公式：
    score = frequency × 2 + duration × 0.5 + cooker_contention × 1
    
    其中：
    - frequency: 食材在当前订单和所有配方中出现的频率
    - duration: 烹饪时长（长时食材优先预存）
    - cooker_contention: 同灶台食材数量（冲突越多，越需要预存）
    
    Args:
        recipes: 所有配方列表
        current_orders: 当前订单列表
        stockpile_slots: 库存槽数量（默认3）
        
    Returns:
        槽位名称 -> 食材名称的映射
    """
    # 统计食材信息
    ingredient_stats = {}
    
    for recipe in recipes:
        for i, ing in enumerate(recipe.raw_ingredients):
            if ing not in ingredient_stats:
                ingredient_stats[ing] = {
                    "frequency": 0,
                    "duration": recipe.cook_durations[i] if i < len(recipe.cook_durations) else 0,
                    "cooker": recipe.cookers[i] if i < len(recipe.cookers) else None,
                    "cooker_contention": 0
                }
            ingredient_stats[ing]["frequency"] += 1
    
    # 计算灶台冲突
    cooker_ingredients = {}
    for ing, stats in ingredient_stats.items():
        cooker = stats["cooker"]
        if cooker:
            if cooker not in cooker_ingredients:
                cooker_ingredients[cooker] = []
            cooker_ingredients[cooker].append(ing)
    
    for cooker, ings in cooker_ingredients.items():
        for ing in ings:
            ingredient_stats[ing]["cooker_contention"] = len(ings) - 1
    
    # 计算得分
    scores = {}
    for ing, stats in ingredient_stats.items():
        scores[ing] = (
            stats["frequency"] * 2 +
            stats["duration"] * 0.5 +
            stats["cooker_contention"] * 1
        )
    
    # 选择得分最高的食材
    sorted_ingredients = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    
    # 分配槽位
    assignments = {}
    for i, (ing, score) in enumerate(sorted_ingredients[:stockpile_slots]):
        slot_name = f"slot{i}"
        assignments[slot_name] = ing
    
    return assignments
```

### 5.2 补货决策

```python
def should_refill_stockpile(
    slot: StockpileSlot,
    threshold: int = 2
) -> bool:
    """
    判断是否需要补货
    
    Args:
        slot: 库存槽位状态
        threshold: 补货阈值（默认2）
        
    Returns:
        是否需要补货
    """
    if slot.ingredient_name is None:
        return False
    
    return slot.count < threshold
```

---

## 6. 并行最大化策略

### 6.1 灶台分配算法

```python
def assign_cookers_parallel(
    needed_ingredients: list[str],
    free_cookers: list[str],
    ingredient_info: dict[str, tuple[str, float]],
    stockpile: dict[str, StockpileSlot]
) -> list[CookAction]:
    """
    并行最大化灶台分配
    
    策略：
    1. 同时启动所有空闲灶台
    2. 优先烹饪订单需要的食材
    3. 空闲灶台预烹饪高频食材
    
    Args:
        needed_ingredients: 需要烹饪的食材列表
        free_cookers: 空闲灶台列表
        ingredient_info: 食材 -> (灶台, 时长) 映射
        stockpile: 库存状态
        
    Returns:
        烹饪动作列表
    """
    actions = []
    available_cookers = set(free_cookers)
    
    # 第一轮：烹饪订单需要的食材
    for ing in needed_ingredients:
        if ing not in ingredient_info:
            continue
        
        cooker_type, duration = ingredient_info[ing]
        
        if cooker_type in available_cookers:
            actions.append(CookAction(
                ingredient=ing,
                cooker=cooker_type,
                duration=duration
            ))
            available_cookers.remove(cooker_type)
    
    # 第二轮：预烹饪高频食材
    for cooker_type in available_cookers:
        # 找到该灶台对应的高频食材
        for slot_name, slot in stockpile.items():
            if slot.cooker_type == cooker_type and slot.count < 2:
                if slot.ingredient_name and slot.ingredient_name in ingredient_info:
                    _, duration = ingredient_info[slot.ingredient_name]
                    actions.append(CookAction(
                        ingredient=slot.ingredient_name,
                        cooker=cooker_type,
                        duration=duration
                    ))
                    available_cookers.remove(cooker_type)
                    break
    
    return actions
```

### 6.2 组装站流水线

```python
def plan_assembly_pipeline(
    assembly: AssemblyState,
    cookers: dict[str, CookerState],
    env_time: float
) -> list[Action]:
    """
    组装站流水线规划
    
    策略：
    1. 送餐后立即开始下一份菜品组装
    2. 灶台完成后立即移动到组装站
    3. 避免组装站空闲
    
    Args:
        assembly: 组装站状态
        cookers: 灶台状态
        env_time: 当前时间
        
    Returns:
        动作列表
    """
    actions = []
    
    # 检查是否有完成的食材可以移动
    for cooker_name, cooker in cookers.items():
        if cooker.busy and cooker.done_at and env_time >= cooker.done_at:
            # 检查是否可以添加到组装站
            # TODO: 实现组装站容量检查
            actions.append(MoveToAssemblyAction(cooker=cooker_name))
    
    return actions
```

---

## 7. 测试框架设计

### 7.1 测试环境

```python
class SimulatorEnvironment(BaseEnvironment):
    """
    模拟器环境实现
    
    用于测试Agent算法，不依赖真实游戏。
    """
    
    def __init__(self, config: dict):
        self.config = config
        self.time = 0.0
        self.orders = [None] * 4
        self.cookers = {}
        self.assembly = AssemblyState()
        self.stockpile = {}
        self._animation_until = 0.0
        
        # 初始化灶台
        for cooker_name in config.get("cookers", ["grill", "oven", "pot", "skillet"]):
            self.cookers[cooker_name] = CookerState()
        
        # 初始化库存
        for i in range(config.get("stockpile_slots", 3)):
            slot_name = f"slot{i}"
            self.stockpile[slot_name] = StockpileSlot()
    
    # 实现BaseEnvironment的所有抽象方法...
```

### 7.2 测试用例

```python
class TestAgentBasicFlow(unittest.TestCase):
    """基础流程测试"""
    
    def test_single_order_complete(self):
        """单订单完整流程"""
        # 创建模拟环境
        env = SimulatorEnvironment({
            "cookers": ["grill", "oven", "pot", "skillet"],
            "stockpile_slots": 3
        })
        
        # 创建Agent
        recipes = [...]  # 测试配方
        agent = CookingAgent(env, recipes)
        
        # 模拟订单出现
        env.orders[0] = {
            "recipe": recipes[0],
            "is_rush": False,
            "created_at": 0.0,
            "timeout_at": 70.0
        }
        
        # 运行Agent
        actions = []
        for _ in range(100):  # 模拟100个tick
            action = agent.step()
            if action:
                actions.append(action)
            env.tick(0.1)
        
        # 验证
        self.assertGreater(len(actions), 0)
        self.assertEqual(agent.stats["orders_served"], 1)


class TestAgentParallel(unittest.TestCase):
    """并行场景测试"""
    
    def test_multiple_cookers_simultaneous(self):
        """多灶台同时烹饪"""
        # TODO: 实现测试
        pass
    
    def test_multiple_orders_parallel(self):
        """多订单并行处理"""
        # TODO: 实现测试
        pass


class TestAgentBoundary(unittest.TestCase):
    """边界情况测试"""
    
    def test_order_timeout(self):
        """订单超时处理"""
        # TODO: 实现测试
        pass
    
    def test_cooker_conflict(self):
        """灶台冲突处理"""
        # TODO: 实现测试
        pass
    
    def test_assembly_busy(self):
        """组装站占用处理"""
        # TODO: 实现测试
        pass
    
    def test_ingredient_expired(self):
        """食材过期处理"""
        # TODO: 实现测试
        pass


class TestAgentPerformance(unittest.TestCase):
    """性能测试"""
    
    def test_tick_interval_comparison(self):
        """不同tick间隔性能对比"""
        intervals = [0.05, 0.1, 0.2, 0.5]
        results = {}
        
        for interval in intervals:
            # 创建环境和Agent
            env = SimulatorEnvironment(...)
            agent = CookingAgent(env, ...)
            
            # 运行测试
            # ...
            
            results[interval] = agent.stats
        
        # 输出对比结果
        print("Tick interval performance comparison:")
        for interval, stats in results.items():
            print(f"  {interval}s: {stats['orders_served']} orders, {stats['total_score']} score")
```

---

## 8. 实现计划

### 8.1 文件结构

```
hawarma/
├── agent/
│   ├── __init__.py          # 统一Agent导出
│   ├── agent.py             # CookingAgent核心类
│   ├── environment.py       # BaseEnvironment抽象基类
│   ├── actions.py           # Action类型定义
│   └── algorithms.py        # 库存分配、并行最大化等算法
├── bridge/
│   ├── __init__.py
│   ├── game_environment.py  # GameEnvironment实现
│   └── ui_runner.py         # UI操作执行器
tests/
├── agent/
│   ├── __init__.py
│   ├── test_basic_flow.py   # 基础流程测试
│   ├── test_parallel.py     # 并行场景测试
│   ├── test_boundary.py     # 边界情况测试
│   └── test_performance.py  # 性能测试
```

### 8.2 开发顺序

1. **Phase 1: 核心接口**
   - 定义BaseEnvironment抽象基类
   - 定义Action类型
   - 实现SimulatorEnvironment

2. **Phase 2: Agent核心**
   - 实现CookingAgent基本逻辑
   - 实现库存分配算法
   - 实现并行最大化策略

3. **Phase 3: 测试框架**
   - 设计测试用例
   - 实现性能对比测试
   - 优化算法参数

4. **Phase 4: 真实环境集成**
   - 实现GameEnvironment
   - 集成UI操作
   - 实际测试和调优

---

## 9. 性能优化

### 9.1 当前性能指标（30局平均）

| 指标 | 值 | 说明 |
|------|-----|------|
| 订单完成数 | 14.1个 | 平均每90秒完成订单数 |
| 超时率 | 2.3% | 订单超时比例 |
| 平均得分 | 2492分 | 每局游戏的平均得分 |
| 效率 | 78% | 实际/理论最大值（18个） |

### 9.2 经验教训

**有效优化**：
1. 烹饪优先于调味（+10.8%）
2. 优先烹饪时间长的食材（+2%）

**无效优化**：
1. 预烹饪到assembly（与订单不匹配，-30%）
2. 预烹饪到stockpile（额外开销，-2%）

**关键发现**：
- 按需响应策略已经足够好（78%效率）
- 灶台是异步的，尽早开始烹饪是关键
- 在不确定的环境中，预测性优化反而可能引入问题

### 9.3 优化方向

1. **按需响应**（已验证）
   - 只烹饪当前订单需要的食材
   - 避免预烹饪

2. **烹饪优先**（已验证）
   - 送餐 → 移动食材 → 开始烹饪 → 添加调料
   - 灶台是异步的，尽早开始烹饪

3. **进一步优化**（待探索）
   - 分析具体哪些订单导致超时
   - 针对性优化复杂订单的处理

---

## 10. 总结

高效Agent的核心策略：

1. **统一设计**：单一Agent类，支持游戏环境和模拟器两种交互模式
2. **按需响应**：只处理当前订单，避免预烹饪
3. **烹饪优先**：让灶台尽早开始异步工作
4. **测试驱动**：在模拟环境中测试和优化算法

关键成功因素：**让灶台尽早开始异步工作**
