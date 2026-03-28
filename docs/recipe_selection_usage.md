# 选菜单功能使用示例

## 新的游戏流程

```python
from hawarma.env_simulator import GameSimulator

# 1. 创建模拟器并加载所有菜谱
sim = GameSimulator()
sim.load_recipes("data/recipes.json")

# 2. 选菜单（从14个菜谱中选择4个）
selected_recipes = sim.select_recipes(count=4, random_seed=42)
print(f"本局选中的菜谱: {selected_recipes}")
# 输出: ['newYearJiaozi', 'woodlandMushroomRisotto', ...]

# 3. 根据选中的菜谱自动配置游戏
config = sim.setup_from_recipes(selected_recipes)

# 4. 查看游戏配置
print(f"可用灶台: {config.available_cookers}")
# 输出: ['oven', 'pot', 'skillet', 'grill']

print(f"食材区食材: {config.available_ingredients}")
# 输出: ['dough_wrappers', 'tender_lamb', 'wild_mushroom', ...]

print(f"调料区调料: {config.available_condiments}")
# 输出: ['hearthspice', 'fleur_de_sel', 'elderberry_liqueur', ...]

# 5. 游戏开始！Agent只能使用本局可用的资源
# 尝试使用本局不可用的食材会失败
result = sim.start_cooking('invalid_ingredient', 'skillet')
print(result.error_message)
# 输出: Ingredient 'invalid_ingredient' not available in this game. Available: [...]

# 使用本局可用的食材可以成功
result = sim.start_cooking('clearwater_fish', 'skillet')
print(f"烹饪开始: {result.success}")
```

## 关键概念

1. **GameConfig**: 每局游戏的配置对象，包含：
   - `selected_recipes`: 选中的4个菜谱
   - `available_cookers`: 本局可用的灶台
   - `available_ingredients`: 食材区的食材
   - `available_condiments`: 调料区的调料

2. **选菜单流程**：
   - 从14个菜谱中随机选择4个
   - 根据这4个菜谱决定哪些灶台、食材、调料可用
   - 库存区初始为空，由Agent自己决定存什么

3. **验证机制**：
   - `start_cooking()`: 验证食材和灶台是否在本局可用
   - `add_condiment()`: 验证调料是否在本局可用
   - 如果尝试使用不可用的资源，操作会失败并返回错误信息

## 优势

1. **更真实**: 模拟了真实游戏的"选菜单"机制
2. **更多变**: 不同菜谱组合需要不同的策略
3. **可测试**: 可以针对特定菜谱组合测试Agent
4. **可控**: 可以固定菜谱进行回归测试（通过random_seed）