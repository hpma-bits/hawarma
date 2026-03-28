# 为 env_simulator 添加"选菜单"功能的设计方案

## 问题理解

当前 env_simulator 的问题：
1. **加载所有菜谱**：`load_recipes()` 加载 data/recipes.json 中的全部14个菜谱
2. **固定灶台配置**：`setup_cookers()` 固定为 ['grill', 'oven', 'skillet', 'pot']
3. **固定库存配置**：`setup_stockpile()` 固定为3个槽位，但没有绑定具体食材
4. **缺少食材/调料区**：没有定义这局游戏哪些食材/调料可用

**真实游戏逻辑**：
1. 每局游戏开始时**选择4个菜谱**（从14个中选4个）
2. **灶台**：显示这局4个菜谱需要的所有厨具（可能少于4个，也可能刚好4个）
3. **食材区**：显示这局4个菜谱需要的所有食材（最多8个槽位）
4. **调料区**：显示这局4个菜谱需要的所有调料
5. **库存区**：**初始为空**，Agent自己决定存什么

## 设计方案

### 1. 新增数据结构

```python
@dataclass
class GameConfig:
    """
    单局游戏配置
    
    记录当前游戏局的具体配置：选中的菜谱、可用的道具等
    """
    selected_recipes: List[str] = field(default_factory=list)  # 选中的菜谱slug列表（最多4个）
    available_cookers: List[str] = field(default_factory=list)  # 本局可用的灶台
    available_ingredients: List[str] = field(default_factory=list)  # 食材区的食材
    available_condiments: List[str] = field(default_factory=list)  # 调料区的调料
    
    @property
    def is_configured(self) -> bool:
        """检查游戏是否已配置"""
        return len(self.selected_recipes) > 0
```

### 2. 新增/修改方法

**A. 选择菜谱**
```python
def select_recipes(self, count: int = 4, random_seed: Optional[int] = None) -> List[str]:
    """
    从所有菜谱中随机选择指定数量的菜谱（最多4个）
    
    Args:
        count: 选择的菜谱数量（默认4，最多4）
        random_seed: 随机种子（用于可复现的测试）
    
    Returns:
        选中的菜谱slug列表
    """
```

**B. 根据菜谱配置游戏**
```python
def setup_from_recipes(self, recipe_slugs: List[str]) -> GameConfig:
    """
    根据选中的菜谱自动配置游戏
    
    自动设置：
    - 灶台（从菜谱的cookers字段收集）
    - 食材区（从菜谱的raw_ingredients字段收集）
    - 调料区（从菜谱的condiments字段收集）
    - 库存区（初始化为3个空槽位）
    """
```

**C. 修改现有方法**
```python
def start_cooking(self, ingredient: str, cooker: str) -> ActionResult:
    """
    开始烹饪
    
    新增验证：
    - ingredient 必须在 available_ingredients 中
    - cooker 必须在 available_cookers 中
    """

def add_condiment(self, condiment: str) -> ActionResult:
    """
    添加调料
    
    新增验证：
    - condiment 必须在 available_condiments 中
    """
```

### 3. 新的初始化流程

```python
# 初始化游戏（新流程）
sim = GameSimulator()
sim.load_recipes("data/recipes.json")  # 加载所有14个菜谱

# 选菜单（4个菜谱）
selected = sim.select_recipes(count=4, random_seed=42)
print(f"本局菜谱: {selected}")

# 自动配置游戏
game_config = sim.setup_from_recipes(selected)
print(f"可用灶台: {game_config.available_cookers}")
print(f"食材区: {game_config.available_ingredients}")
print(f"调料区: {game_config.available_condiments}")
# 注意：库存区初始为空

# 游戏开始！
```

### 4. Agent 接口设计

为了让 Agent 知道当前游戏的布局：

```python
@property
def game_config(self) -> GameConfig:
    """返回当前游戏的配置（Agent需要知道哪些食材/调料可用）"""
    return self._game_config

@property
def available_actions(self) -> List[str]:
    """
    返回当前可用的动作列表
    
    例如：
    - start_cooking_clearwater_fish_on_skillet
    - start_cooking_creamfield_rice_on_pot
    - add_condiment_hearthspice
    """
```

## 实现步骤

1. **添加 GameConfig 数据类**到 env_simulator_types.py
2. **修改 env_simulator.py**:
   - 添加 `_game_config` 属性
   - 实现 `select_recipes()`
   - 实现 `setup_from_recipes()`
   - 修改 `start_cooking()` 验证食材和灶台是否在配置中
   - 修改 `add_condiment()` 验证调料是否在配置中
3. **添加测试用例**验证选菜单逻辑
4. **更新文档**说明新的初始化流程

## 优势

1. **更真实**：模拟了真实游戏的"选菜单"机制
2. **更多变**：不同菜谱组合需要不同的策略
3. **可测试**：可以针对特定菜谱组合测试Agent
4. **可控**：可以固定菜谱进行回归测试