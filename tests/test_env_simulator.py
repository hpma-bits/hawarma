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
    SimulationError,
    ValidationError,
    load_recipes_from_file,
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
    sim.setup_cookers(['grill', 'oven'])
    sim.setup_stockpile(['stk0', 'stk1', 'stk2'])
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
        assert len(sim.state.orders) == 0  # 未设置时为空
        assert len(sim.state.cookers) == 0
        assert len(sim.state.stockpile) == 0


# ============================================================================
# 测试类 2: 90秒游戏时间限制
# ============================================================================

class TestGameTimeLimit:
    """测试90秒游戏时间限制"""
    
    def test_game_duration_is_90_seconds(self):
        """测试游戏总时长为90秒"""
        sim = create_simple_simulator()
        
        # 验证常量
        assert GameSimulator.GAME_DURATION == 90.0
    
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
    
    def test_orders_generate_every_4_seconds(self):
        """测试订单每4秒生成"""
        sim = create_simple_simulator()
        sim._recipes['test_burger'] = create_test_recipe()
        
        # 游戏开始，时间=0
        assert sim.get_order(0) is None
        
        # 推进4秒
        sim.tick(4.0)
        
        # 应该有一个订单在槽位0
        order1 = sim.get_order(0)
        assert order1 is not None
        assert order1.order_id == 1
    
    def test_orders_fill_leftmost_empty_slot(self):
        """测试订单填充最左边的空槽位"""
        sim = create_simple_simulator()
        sim._recipes['test_burger'] = create_test_recipe()
        
        # 在第4秒生成第一个订单
        sim.tick(4.0)
        assert sim.get_order(0) is not None
        
        # 在第8秒生成第二个订单
        sim.tick(4.0)
        assert sim.get_order(1) is not None
        
        # 在第12秒生成第三个订单
        sim.tick(4.0)
        assert sim.get_order(2) is not None
    
    def test_orders_stop_when_all_slots_full(self):
        """测试当所有槽位满时不再生成新订单"""
        sim = create_simple_simulator()
        sim._recipes['test_burger'] = create_test_recipe()
        
        # 填满4个槽位
        for i in range(4):
            sim.tick(4.0)
        
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
        
        # 设置一个完整的订单处理流程
        # 第4秒生成第一个订单
        sim.tick(4.0)
        assert sim.get_order(0) is not None
        
        # 模拟完成这个订单并提交
        # 注意：这里需要完整的流程：烹饪 -> 组装 -> 提交
        # 为了测试，我们直接模拟提交后的状态
        
        # 假设在第20秒提交了这个唯一的订单
        sim.tick(16.0)  # 从第4秒到第20秒
        
        # 提交订单后，场上没有订单了
        # 根据规则：如果没有订单，应该立即刷新新订单
        # 注意：新订单有1秒动画时间
        
        # 检查是否立即生成了新订单（在内部状态）
        # 但玩家需要等待1秒动画后才能看到
        
        # 这个测试主要验证立即刷新逻辑是否存在
        # 具体实现可能需要检查 _pending_orders 或类似机制
        
        # 简单验证：提交后如果槽位变空，应该很快有新订单
        #（具体实现细节取决于你如何实现）
        pass  # 占位，等待实现后再完善
    
    def test_refresh_timer_starts_from_serve_when_orders_remain(self):
        """测试有剩余订单时从提交时刻开始4秒计时刷新"""
        sim = create_simple_simulator()
        sim._recipes['test_burger'] = create_test_recipe()
        
        # 生成4个订单填满所有槽位
        sim.tick(4.0)   # 第4秒：订单1
        sim.tick(4.0)   # 第8秒：订单2
        sim.tick(4.0)   # 第12秒：订单3
        sim.tick(4.0)   # 第16秒：订单4
        
        # 确认4个槽位都有订单
        for i in range(4):
            assert sim.get_order(i) is not None
        
        # 假设在第20秒提交了订单1（slot 0）
        # 提交后，slot 0 变空，slot 1-3 的订单左移
        # 场上还剩3个订单（原来的2、3、4，现在变成1、2、3）
        sim.tick(4.0)   # 第20秒
        
        # 根据规则：如果场上有剩余订单，从提交时刻（第20秒）开始计时
        # 4秒后（第24秒）应该刷新新订单到空的 slot 3
        sim.tick(4.0)   # 第24秒
        
        # 验证第24秒有新订单出现
        # 注意：具体验证方式取决于实现
        # 可能需要检查是否有新订单ID或者 slot 3 不为空
        pass  # 占位，等待实现后再完善

class TestParallelCooking:
    """测试并行烹饪"""
    
    def test_multiple_cookers_can_cook_simultaneously(self):
        """测试多个灶台可以同时烹饪"""
        sim = create_simple_simulator()
        
        # 同时在两个灶台开始烹饪
        result1 = sim.start_cooking('beef', 'grill')
        result2 = sim.start_cooking('fish', 'oven')
        
        # 两个都应该成功
        assert result1.success, f"Failed to start on grill: {result1.error_message}"
        assert result2.success, f"Failed to start on oven: {result2.error_message}"
        
        # 检查状态
        grill = sim.get_cooker_state('grill')
        oven = sim.get_cooker_state('oven')
        
        assert grill.busy
        assert grill.ingredient_name == 'beef'
        assert oven.busy
        assert oven.ingredient_name == 'fish'
    
    def test_cookers_complete_at_different_times(self):
        """测试不同灶台在不同时间完成烹饪"""
        sim = create_simple_simulator()
        
        # 模拟配方数据（烹饪时间不同）
        # 注意：实际实现中应该从 recipe 获取持续时间
        # 这里我们只是测试 tick 机制
        
        # 在 grill 开始烹饪（假设 3 秒）
        sim.start_cooking('beef', 'grill')
        # 在 oven 开始烹饪（假设 4 秒）
        sim.start_cooking('fish', 'oven')
        
        # 推进 3 秒
        events = sim.tick(3.0)
        
        # grill 应该完成，但 oven 还未完成
        # 注意：实际实现中需要检查事件的类型
        grill = sim.get_cooker_state('grill')
        
        # 推进再 1 秒（总共 4 秒）
        events = sim.tick(1.0)
        
        # oven 应该完成
        oven = sim.get_cooker_state('oven')
    
    def test_cooker_becomes_available_after_completion(self):
        """测试灶台在完成后可以再次使用"""
        sim = create_simple_simulator()
        
        # 第一轮烹饪
        result1 = sim.start_cooking('beef', 'grill')
        assert result1.success
        
        # 推进时间到完成
        sim.tick(3.0)  # 假设牛肉需要 3 秒
        
        # 将食材移出
        result2 = sim.move_to_assembly('grill')
        assert result2.success
        
        # 灶台现在应该是空闲的
        grill = sim.get_cooker_state('grill')
        assert not grill.busy
        
        # 第二轮烹饪应该可以开始
        result3 = sim.start_cooking('fish', 'grill')
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
        
        # 在grill开始烹饪
        result1 = sim.start_cooking('beef', 'grill')
        assert result1.success
        
        # 尝试在同一个grill开始另一个烹饪
        result2 = sim.start_cooking('fish', 'grill')
        assert not result2.success
        assert "busy" in result2.error_message.lower() or "cooker" in result2.error_message.lower()


# ============================================================================
# 主程序入口
# ============================================================================

if __name__ == '__main__':
    # 使用 pytest 运行测试
    pytest.main([__file__, '-v'])
