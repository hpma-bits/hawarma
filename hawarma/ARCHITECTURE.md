# hawarma Directory Architecture

## 📁 目录概述
此目录是hawarma项目的核心模块，包含应用的主要逻辑、服务、模型和工具。

## 📄 文件列表

### `__init__.py`
- **地位**: 包初始化文件，标识Python包
- **功能**: 使hawarma成为一个可导入的Python包

### `app.py`
- **地位**: 核心应用类
- **功能**: 
  - 协调整个烹饪流程
  - 管理订单队列和处理管道
  - 协调detection_service和cooking_service
  - 处理库存管理和原料囤积策略
- **输入**: 配置对象、配方列表
- **输出**: 应用运行状态、订单完成统计

### `config.py`
- **地位**: 配置管理模块
- **功能**: 
  - 从YAML文件加载配置
  - 使用Pydantic进行配置验证
  - 提供类型安全的配置访问
- **输入**: YAML配置文件路径
- **输出**: AppConfig对象

### `logging_setup.py`
- **地位**: 日志配置模块
- **功能**: 使用loguru配置应用日志系统
- **输入**: 日志级别
- **输出**: 配置好的日志系统

### `models.py`
- **地位**: 数据模型定义模块
- **功能**: 
  - 定义Ingredient、Cooker、Recipe等数据模型
  - 定义Order和OrderStage枚举
  - 提供数据验证和序列化
- **输入**: JSON数据或构造参数
- **输出**: 验证后的模型对象

### `monkey_patches.py`
- **地位**: 兼容性补丁模块
- **功能**: 
  - 修复airtest框架的兼容性问题
  - 覆盖Template类的私有方法
- **输入**: 无
- **输出**: 修改后的Template._cv_match方法

### `services/` 子目录
包含业务逻辑服务：
- `detection_service.py`: 订单检测服务
- `cooking_service.py`: 烹饪操作服务
- `recipe_manager.py`: 配方管理服务

### `utils/` 子目录
包含工具函数：
- `image_utils.py`: 图像处理工具

## 🔗 模块间关系
```
main.py
    ↓
CookingBotApp (app.py)
    ↓
    ├─→ DetectionService (订单检测)
    ├─→ CookingService (烹饪操作)
    └─→ RecipeManager (配方管理)
```

## ⚠️ 重要提示
**一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**
