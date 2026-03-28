# 选菜单功能实现完成

## 完成的工作

### 1. 添加 GameConfig 数据类
- **文件**: `hawarma/env_simulator_types.py`
- **内容**:
  ```python
  @dataclass
  class GameConfig:
      selected_recipes: List[str]      # 选中的菜谱slug列表（最多4个）
      available_cookers: List[str]      # 本局可用的灶台
      available_ingredients: List[str]  # 食材区的食材
      available_condiments: List[str]   # 调料区的调料
      
      @property
      def is_configured(self) -> bool:
          """检查游戏是否已配置"""
          return len(self.selected_recipes) > 0
  ```

### 2. 实现 select_recipes() 方法
- **位置**: `GameSimulator` 类
- **功能**: 从所有菜谱中随机选择指定数量的菜谱（最多4个）
- **特点**:
  - 支持随机种子（用于可复现的测试）
  - 自动限制最多4个菜谱

### 3. 实现 setup_from_recipes() 方法
- **位置**: `GameSimulator` 类
- **功能**: 根据选中的菜谱自动配置游戏
- **自动设置**:
  - **灶台**: 从菜谱的 cookers 字段收集
  - **食材区**: 从菜谱的 raw_ingredients 字段收集
  - **调料区**: 从菜谱的 condiments 字段收集
  - **库存区**: 初始为空（由Agent自己决定存什么）

### 4. 修改 start_cooking() 添加验证
- **新增验证**:
  1. 检查游戏是否已配置（已选菜谱）
  2. 检查食材是否在 available_ingredients 中
  3. 检查灶台是否在 available_cookers 中

### 5. 修改 add_condiment() 添加验证
- **新增验证**:
  1. 检查游戏是否已配置
  2. 检查调料是否在 available_condiments 中

## 使用示例

```python
from hawarma.env_simulator import GameSimulator

# 1. 创建模拟器并加载所有菜谱
sim = GameSimulator()
sim.load_recipes("data/recipes.json")

# 2. 选菜单（从14个菜谱中选择4个）
selected = sim.select_recipes(count=4, random_seed=42)
print(f"本局选中的菜谱: {selected}")

# 3. 自动配置游戏
config = sim.setup_from_recipes(selected)
print(f"可用灶台: {config.available_cookers}")
print(f"食材区食材: {config.available_ingredients}")
print(f"调料区调料: {config.available_condiments}")

# 4. 游戏开始！Agent只能使用本局可用的资源
# 尝试使用不可用的资源会失败
result = sim.start_cooking('invalid_ingredient', 'skillet')
print(result.error_message)
# 输出: Ingredient 'invalid_ingredient' not available in this game...
```

## 测试结果

✅ 所有测试通过！
- 20 passed
- 2 skipped

新增测试覆盖了：
- 选菜单功能
- 游戏配置验证
- 资源可用性检查

## 优势

1. **更真实**: 模拟了真实游戏的"选菜单"机制
2. **更多变**: 不同菜谱组合需要不同的策略
3. **可测试**: 可以针对特定菜谱组合测试Agent
4. **可控**: 可以固定菜谱进行回归测试（通过random_seed）