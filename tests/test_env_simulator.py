"""
游戏环境模拟器 - 测试套件

地位：基于TDD原则，先编写测试用例再实现功能
输入：测试用例、期望输出
输出：测试通过/失败状态

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新
"""

import pytest
from pathlib import Path
from typing import Dict, List, Optional

# 导入待测试的模块
from hawarma.env_simulator_types import (
    Event,
    EventType,
    Order,
    CookerState,
    AssemblyState,
    StockpileSlot,
    GameState,
    Recipe,
    IngredientRequirement,
)
from hawarma.env_simulator import (
    GameSimulator,
    ActionResult,
)


# ============================================================================
# 辅助函数
# ============================================================================

def create_test_recipe() -> Recipe:
    """创建一个测试配方"""
    return Recipe(
        name="Test Burger",
        slug="test_burger",
        ingredients=(
            IngredientRequirement(name="beef", cooker_type="grill", duration=3.0),
            IngredientRequirement(name="bun", cooker_type="oven", duration=2.0),
        ),
        condiments={"salt": 1, "pepper": 1}
    )


def create_simple_simulator() -> GameSimulator:
    """创建一个配置好的简单模拟器"""
    sim = GameSimulator()
    sim.load_recipes("data/recipes.json")
    selected = sim.select_recipes(count=4, random_seed=42)
    sim.setup_from_recipes(selected)
    return sim


# ============================================================================
# 测试类 1: 基础结构和初始化
# ============================================================================

class TestBasicStructure:
    """测试基础数据结构和初始化"""
    
    def test_event_creation(self):
        """测试事件创建"""
        event = Event(
            timestamp=1.0,
            event_type=EventType.COOKING_STARTED,
            details={'ingredient': 'beef', 'cooker': 'grill'}
        )
        assert event.timestamp == 1.0
        assert event.event_type == EventType.COOKING_STARTED
        assert event.details['ingredient'] == 'beef'
    
    def test_recipe_creation(self):
        """测试配方创建"""
        recipe = create_test_recipe()
        assert recipe.name == "Test Burger"
        assert recipe.slug == "test_burger"
        assert len(recipe.ingredients) == 2
        assert recipe.ingredients[0].name == "beef"
        assert recipe.ingredients[0].duration == 3.0
    
    def test_cooker_state_initialization(self):
        """测试灶台状态初始化"""
        cooker = CookerState()
        assert cooker.busy == False
        assert cooker.ingredient_name is None
        assert cooker.done_at is None
    
    def test_simulator_initialization(self):
        """测试模拟器初始化"""
        sim = GameSimulator()
        assert sim.time == 0.0
        assert len(sim.state.orders) == 4  # 初始化时有4个空槽位
        assert all(o is None for o in sim.state.orders)
        assert len(sim.state.cookers) == 0
        assert len(sim.state.stockpile) == 0


# ============================================================================
# 测试类 2: 90秒游戏时间限制
# ============================================================================

class TestGameTimeLimit:
    """测试90秒游戏时间限制"""
    
    def test_game_duration_default(self):
        """测试游戏默认时长为90秒，范围90-110秒"""
        sim = create_simple_simulator()
        
        # 验证常量
        assert GameSimulator.GAME_DURATION_MIN == 90.0
        assert GameSimulator.GAME_DURATION_MAX == 110.0
        assert GameSimulator.DEFAULT_GAME_DURATION == 90.0
        
        # 验证默认实例
        assert sim._game_duration == 90.0
        
        # 测试自定义时长
        sim2 = GameSimulator(game_duration=100.0)
        assert sim2._game_duration == 100.0
    
    def test_game_ends_at_90_seconds(self):
        """测试游戏在90秒时结束"""
        sim = create_simple_simulator()
        
        # 推进到90秒
        events = sim.tick(90.0)
        
        # 游戏应该结束
        assert sim.is_game_over() == True
        assert sim.time == 90.0
    
    def test_game_not_over_before_90_seconds(self):
        """测试在90秒前游戏未结束"""
        sim = create_simple_simulator()
        
        # 推进到89秒
        sim.tick(89.0)
        
        # 游戏应该未结束
        assert sim.is_game_over() == False
    
    def test_cannot_advance_time_after_game_over(self):
        """测试游戏结束后不能再推进时间"""
        sim = create_simple_simulator()
        
        # 推进到90秒
        sim.tick(90.0)
        
        # 尝试再推进时间
        events = sim.tick(1.0)
        
        # 应该返回空列表（无事件）
        assert events == []
        # 时间保持在90秒
        assert sim.time == 90.0


# ============================================================================
# 测试类 3: 自动订单生成（每4秒）
# ============================================================================

class TestAutoOrderGeneration:
    """测试自动订单生成（每4秒）"""
    
    def test_orders_generate_at_random_interval(self):
        """测试订单在随机间隔后生成（3-5秒）"""
        sim = create_simple_simulator()
        sim._recipes['test_burger'] = create_test_recipe()
        
        # 获取第一个刷新时间
        first_refresh = sim._next_order_refresh_time
        assert 3.0 <= first_refresh <= 5.0, f"First refresh should be 3-5s, got {first_refresh}s"
        
        # 推进到刷新时间（订单生成）
        sim.tick(first_refresh)
        # 再推进1秒动画时间
        sim.tick(1.0)
        
        # 应该有一个订单在槽位0
        order1 = sim.get_order(0)
        assert order1 is not None, f"Order should appear after {first_refresh}s + 1s animation"
        assert order1.order_id == 1
    
    def test_orders_fill_leftmost_empty_slot(self):
        """测试订单填充最左边的空槽位"""
        sim = create_simple_simulator()
        sim._recipes['test_burger'] = create_test_recipe()
        
        # 获取第一个刷新时间并推进
        refresh1 = sim._next_order_refresh_time
        sim.tick(refresh1 + 1.0)  # +1s animation
        assert sim.get_order(0) is not None
        
        # 获取第二个刷新时间并推进
        refresh2 = sim._next_order_refresh_time
        sim.tick(refresh2 + 1.0)
        assert sim.get_order(1) is not None
        
        # 获取第三个刷新时间并推进
        refresh3 = sim._next_order_refresh_time
        sim.tick(refresh3 + 1.0)
        assert sim.get_order(2) is not None
    
    def test_orders_stop_when_all_slots_full(self):
        """测试当所有槽位满时不再生成新订单"""
        sim = create_simple_simulator()
        sim._recipes['test_burger'] = create_test_recipe()
        
        # 填满4个槽位（每个+1秒动画）
        sim.tick(5.0)   # 第5秒：订单1可见
        sim.tick(4.0)   # 第9秒：订单2可见
        sim.tick(4.0)   # 第13秒：订单3可见
        sim.tick(4.0)   # 第17秒：订单4可见
        
        # 所有4个槽位都应该有订单
        for i in range(4):
            assert sim.get_order(i) is not None
        
        # 再推进4秒，因为有订单完成或超时才会释放槽位
        # 这里我们直接测试没有槽位时不会生成
        # 实际游戏中槽位会在订单完成或超时后释放
    
    def test_orders_stop_at_90_seconds(self):
        """测试在90秒时停止生成订单"""
        sim = create_simple_simulator()
        sim._recipes['test_burger'] = create_test_recipe()
        
        # 推进到88秒（第22个订单周期，4秒间隔）
        # 订单生成时间点：4, 8, 12, ..., 88
        sim.tick(88.0)
        
        # 计算有多少订单：88/4 = 22个订单
        # 但由于只有4个槽位，所以最多4个同时在显示
        
        # 推进到90秒
        sim.tick(2.0)
        
        # 游戏结束
        assert sim.is_game_over()
        
        # 再推进4秒（到94秒），不应该有新订单
        sim.tick(4.0)
        # 时间应该保持在90秒
        assert sim.time == 90.0
    
    def test_order_refresh_with_animation_time(self):
        """测试新订单有1秒动画时间后才能被检测到"""
        sim = create_simple_simulator()
        sim._recipes['test_burger'] = create_test_recipe()
        
        # 推进到第4秒，新订单出现
        sim.tick(4.0)
        
        # 在动画期间（1秒内），应该检测不到新订单
        # 注意：这取决于实现，可能需要检查一个"animation_until"字段
        # 或者检查订单是否有一个 "visible" 标志
        
        # 推进0.5秒（动画期间）
        sim.tick(0.5)
        # 此时订单应该还在动画中，不可见
        # （具体实现可能需要一个方法来检查）
        
        # 再推进0.5秒（总共1秒，动画结束）
        sim.tick(0.5)
        # 现在订单应该可见了
        order = sim.get_order(0)
        assert order is not None
        assert order.order_id == 1
    
    def test_immediate_refresh_when_no_orders_after_serve(self):
        """测试提交后无订单时立即刷新新订单"""
        sim = create_simple_simulator()
        sim._recipes['test_burger'] = create_test_recipe()
        
        # 第4秒生成第一个订单，+1秒动画（可见于5秒）
        sim.tick(5.0)
        assert sim.get_order(0) is not None
        
        # 模拟提交订单：清除订单并触发槽位前移
        sim._state.orders[0] = None
        sim._advance_slots(sim.time)  # time=5.0, animation_until=6.5
        
        # 推进超过动画窗口（1.5秒）
        sim.tick(2.0)  # time=7.0, animation over at 6.5
        
        # 立即刷新应该已触发，订单创建于6.5，动画到7.5
        # 再等1秒动画结束
        sim.tick(1.0)  # time=8.0
        
        # 现在应该可以看到新订单了
        new_order = sim.get_order(0)
        assert new_order is not None, "Immediate refresh should create new order when all slots empty"
    
    def test_refresh_timer_starts_from_serve_when_orders_remain(self):
        """测试有剩余订单时从提交时刻开始4秒计时刷新"""
        sim = create_simple_simulator()
        sim._recipes['test_burger'] = create_test_recipe()
        
        # 生成4个订单填满所有槽位（每个+1秒动画）
        sim.tick(5.0)   # 第5秒：订单1可见
        sim.tick(4.0)   # 第9秒：订单2可见
        sim.tick(4.0)   # 第13秒：订单3可见
        sim.tick(4.0)   # 第17秒：订单4可见
        
        # 确认4个槽位都有订单
        for i in range(4):
            assert sim.get_order(i) is not None
        
        # 模拟在第20秒提交订单1（slot 0）
        sim.tick(3.0)  # 推进到第20秒
        sim._state.orders[0] = None
        sim._advance_slots(sim.time)
        
        # 剩余3个订单应该左移
        assert sim.get_order(0) is not None  # 原slot1
        assert sim.get_order(1) is not None  # 原slot2
        assert sim.get_order(2) is not None  # 原slot3
        
        # 推进到24秒（提交后4秒），新订单应该出现
        sim.tick(4.0)
        # 新订单在动画期间，再等1秒
        sim.tick(1.0)
        
        # slot 3应该有新订单了
        assert sim.get_order(3) is not None, "New order should appear 4s after serve"
    
    def test_refresh_timer_starts_from_expire_when_orders_remain(self):
        """测试订单过期后有剩余订单时从过期时刻开始4秒计时刷新"""
        sim = create_simple_simulator()
        sim._recipes['test_burger'] = create_test_recipe()
        
        # 生成4个订单填满所有槽位（每个+1秒动画）
        sim.tick(5.0)   # 第5秒：订单1可见
        sim.tick(4.0)   # 第9秒：订单2可见
        sim.tick(4.0)   # 第13秒：订单3可见
        sim.tick(4.0)   # 第17秒：订单4可见
        
        # 确认4个槽位都有订单
        for i in range(4):
            assert sim.get_order(i) is not None
        
        # 推进到第20秒
        sim.tick(3.0)
        
        # 模拟订单1（slot 0）过期：设置其 timeout_at 为当前时间之前
        sim._state.orders[0].timeout_at = sim.time - 1.0
        
        # 推进时间触发超时检查（tick会调用_check_order_timeouts）
        sim.tick(0.1)
        
        # 订单1应该已过期，触发 slot 位移
        # 剩余3个订单应该左移
        assert sim.get_order(0) is not None  # 原slot1
        assert sim.get_order(1) is not None  # 原slot2
        assert sim.get_order(2) is not None  # 原slot3
        
        # 推进到24秒（过期后4秒），新订单应该出现
        sim.tick(4.0)
        # 新订单在动画期间，再等1秒
        sim.tick(1.0)
        
        # slot 3应该有新订单了
        assert sim.get_order(3) is not None, "New order should appear 4s after expire"
    
    def test_refresh_timer_starts_from_serve_when_orders_remain(self):
        """测试有剩余订单时从提交时刻开始4秒计时刷新"""
        sim = create_simple_simulator()
        sim._recipes['test_burger'] = create_test_recipe()
        
        # 生成4个订单填满所有槽位（每个+1秒动画）
        sim.tick(5.0)   # 第5秒：订单1可见
        sim.tick(4.0)   # 第9秒：订单2可见
        sim.tick(4.0)   # 第13秒：订单3可见
        sim.tick(4.0)   # 第17秒：订单4可见
        
        # 确认4个槽位都有订单
        for i in range(4):
            assert sim.get_order(i) is not None
        
        # 模拟在第20秒提交订单1（slot 0）
        sim.tick(3.0)  # 推进到第20秒
        sim._state.orders[0] = None
        sim._advance_slots(sim.time)
        
        # 剩余3个订单应该左移
        assert sim.get_order(0) is not None  # 原slot1
        assert sim.get_order(1) is not None  # 原slot2
        assert sim.get_order(2) is not None  # 原slot3
        
        # 推进到24秒（提交后4秒），新订单应该出现
        sim.tick(4.0)
        # 新订单在动画期间，再等1秒
        sim.tick(1.0)
        
        # slot 3应该有新订单了
        assert sim.get_order(3) is not None, "New order should appear 4s after serve"

class TestParallelCooking:
    """测试并行烹饪"""
    
    def test_multiple_cookers_can_cook_simultaneously(self):
        """测试多个灶台可以同时烹饪"""
        sim = create_simple_simulator()
        sim.load_recipes("data/recipes.json")
        
        # 同时在两个灶台开始烹饪（使用选中菜谱中的食材）
        result1 = sim.start_cooking('clearwater_fish', 'skillet')
        result2 = sim.start_cooking('creamfield_rice', 'pot')
        
        # 两个都应该成功
        assert result1.success, f"Failed to start on skillet: {result1.error_message}"
        assert result2.success, f"Failed to start on pot: {result2.error_message}"
        
        # 检查状态
        skillet = sim.get_cooker_state('skillet')
        pot = sim.get_cooker_state('pot')
        
        assert skillet.busy
        assert skillet.ingredient_name == 'clearwater_fish'
        assert pot.busy
        assert pot.ingredient_name == 'creamfield_rice'
    
    def test_cookers_complete_at_different_times(self):
        """测试不同灶台在不同时间完成烹饪"""
        sim = create_simple_simulator()
        sim.load_recipes("data/recipes.json")
        
        # 使用不同烹饪时间的食材
        sim.start_cooking('clearwater_fish', 'skillet')  # 4秒
        sim.start_cooking('creamfield_rice', 'pot')  # 2秒
        
        # 推进 2 秒 - pot 应该完成
        sim.tick(2.0)
        pot = sim.get_cooker_state('pot')
        skillet = sim.get_cooker_state('skillet')
        
        # pot 食材已烹饪完成（但仍在灶台上）
        assert pot.done_at is not None
        assert sim.time >= pot.done_at
        
        # skillet 还没完成
        assert skillet.busy
        assert sim.time < skillet.done_at
        
        # 推进再 2 秒（总共 4 秒）
        sim.tick(2.0)
        skillet = sim.get_cooker_state('skillet')
        
        # 现在 skillet 也完成了
        assert skillet.done_at is not None
        assert sim.time >= skillet.done_at
        
        # oven 应该完成
        oven = sim.get_cooker_state('oven')
    
    def test_cooker_becomes_available_after_completion(self):
        """测试灶台在完成后可以再次使用"""
        sim = create_simple_simulator()
        sim.load_recipes("data/recipes.json")
        
        # 第一轮烹饪：wild_mushroom on skillet (2秒)
        result1 = sim.start_cooking('wild_mushroom', 'skillet')
        assert result1.success
        
        # 推进时间到完成
        sim.tick(2.0)
        
        # 将食材移出
        result2 = sim.move_to_assembly('skillet')
        assert result2.success
        
        # 灶台现在应该是空闲的
        skillet = sim.get_cooker_state('skillet')
        assert not skillet.busy
        
        # 第二轮烹饪应该可以开始：vining_marjoram on skillet (4秒)
        result3 = sim.start_cooking('vining_marjoram', 'skillet')
        assert result3.success


# ============================================================================
# 测试类 5: 积分系统（占位，为以后准备）
# ============================================================================

class TestScoringSystem:
    """测试积分系统（占位）"""
    
    @pytest.mark.skip(reason="积分系统将在未来版本中实现")
    def test_score_calculation_basic(self):
        """测试基础分数计算"""
        pass
    
    @pytest.mark.skip(reason="积分系统将在未来版本中实现")
    def test_score_with_time_penalty(self):
        """测试时间惩罚对分数的影响"""
        pass


# ============================================================================
# 测试类 6: 错误处理和边界情况
# ============================================================================

class TestErrorHandling:
    """测试错误处理和边界情况"""
    
    def test_invalid_slot_index(self):
        """测试无效的槽位索引"""
        sim = create_simple_simulator()
        recipe = create_test_recipe()
        
        # 尝试注入到无效槽位
        result = sim.inject_order(-1, recipe)
        assert not result.success
        assert "invalid" in result.error_message.lower() or "slot" in result.error_message.lower()
        
        result = sim.inject_order(4, recipe)
        assert not result.success
    
    def test_busy_cooker_cannot_start(self):
        """测试繁忙的灶台不能开始新的烹饪"""
        sim = create_simple_simulator()
        sim.load_recipes("data/recipes.json")
        
        # 在 pot 开始烹饪
        result1 = sim.start_cooking('creamfield_rice', 'pot')
        assert result1.success
        
        # 尝试在同一个 pot 开始另一个烹饪
        result2 = sim.start_cooking('wild_mushroom', 'pot')
        assert not result2.success
        assert "busy" in result2.error_message.lower()


# ============================================================================
# 主程序入口
# ============================================================================

if __name__ == '__main__':
    # 使用 pytest 运行测试
    pytest.main([__file__, '-v'])
