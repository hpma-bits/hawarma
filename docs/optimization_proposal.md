# Agent 优化方案

> 供审阅，批准后实施

---

## 问题分析

### 1. 送餐成功率问题
日志显示 Serve verification failed 反复出现，当前 swipe 参数：
- 送餐: `duration=0.25s, steps=12`
- 可能需要增大以提高成功率

### 2. 烹饪优先级问题
当前 Agent 采用7级贪心策略，主要问题：
- 总是先处理 assembly 中的食材，然后才考虑烹饪新食材
- 导致灶台空闲时间未被充分利用
- 仅按需响应可能导致烹饪滞后

---

## 方案一：提升送餐成功率

**修改位置**: `hawarma/bridge/ui_runner.py`

```python
# 当前
await self.swipe(self._assembly_position, pickup_pos, duration=0.25, steps=12)

# 建议改为
await self.swipe(self._assembly_position, pickup_pos, duration=0.3, steps=15)
```

---

## 方案二：优化烹饪优先级策略

### 核心思路
引入"预烹饪"机制，基于订单时间紧迫度提前开始烹饪，而非被动等待。

### 具体策略

#### 2.1 新增：前瞻性烹饪判断

在 `_try_start_cooking()` 中增加：

```python
def _try_start_cooking(self) -> Optional[CookAction]:
    free_cookers = self._get_free_cookers()
    if not free_cookers:
        return None

    # ===== 新增：前瞻性烹饪评估 =====
    # 计算订单剩余时间紧迫度
    urgent_ingredients = self._get_urgent_ingredients()

    for ing_name, cooker_type, timeout_needed in urgent_ingredients:
        if cooker_type not in free_cookers:
            continue
        if self._is_cooking(ing_name):
            continue
        if self._has_in_stockpile(ing_name):
            continue

        # 检查烹饪时间是否足够在订单超时前完成
        _, duration = self._ingredient_info.get(ing_name, (None, 3.0))
        time_until_timeout = self._get_time_until_needed(ing_name)

        if time_until_timeout >= duration:
            order_id = self._get_order_id_for_ingredient(ing_name)
            return CookAction(
                ingredient=ing_name,
                cooker=cooker_type,
                duration=duration,
                order_id=order_id,
            )
    # ===== 前瞻性烹饪结束 =====

    # 原有的按需响应逻辑
    ...
```

#### 2.2 辅助方法

```python
def _get_urgent_ingredients(self) -> list[tuple[str, str, float]]:
    """
    获取需要紧急烹饪的食材列表
    返回: [(ingredient, cooker, time_needed)]
    """
    result = []
    for _, order in self._prioritized_orders():
        remaining = order.timeout_at - self.env.time
        if remaining <= 0:
            continue  # 已超时

        recipe = self._recipe_by_slug.get(order.recipe_slug)
        if not recipe:
            continue

        raw = self._get_recipe_attr(recipe, 'raw_ingredients', [])
        cookers = self._get_recipe_attr(recipe, 'cookers', [])

        for i, ing in enumerate(raw):
            cooker = cookers[i] if i < len(cookers) else None
            if not cooker:
                continue
            if self._is_cooking(ing):
                continue
            if self._has_in_stockpile(ing):
                continue
            # 检查灶台是否有完成食材可用
            if self._has_cooked_ingredient(ing):
                continue

            result.append((ing, cooker, remaining))

    return result

def _get_time_until_needed(self, ingredient: str) -> float:
    """获取该食材最紧迫的订单剩余时间"""
    min_remaining = float('inf')
    for _, order in self._prioritized_orders():
        recipe = self._recipe_by_slug.get(order.recipe_slug)
        if not recipe:
            continue
        raw = self._get_recipe_attr(recipe, 'raw_ingredients', [])
        if ingredient in raw:
            remaining = order.timeout_at - self.env.time
            min_remaining = min(min_remaining, remaining)
    return min_remaining if min_remaining != float('inf') else 0

def _has_cooked_ingredient(self, ingredient: str) -> bool:
    """检查灶台上是否有已完成的该食材"""
    for cooker in self.env.cookers.values():
        if cooker.done_at and cooker.ingredient_name == ingredient:
            return True
    return False
```

#### 2.3 优先级调整

保持原有优先级顺序，但在烹饪选择时优先选择紧迫订单的食材。

---

## 方案三（可选）：灶台利用率优化

### 防止灶台空转

在 `_try_move_to_assembly()` 中增加：
- 如果灶台有完成食材，但 assembly 已有同类食材 → 考虑存入库存或等待

---

## 实施计划

1. **方案一（必须）**: 修改 swipe 参数，提高送餐成功率
2. **方案二（核心）**: 实现前瞻性烹饪策略
3. 验证测试

---

## 待确认

1. 送餐参数调整是否足够？
2. 前瞻性策略的紧迫度阈值是否合理？