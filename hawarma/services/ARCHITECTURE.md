# services Directory Architecture

## 📁 目录概述
此目录包含hawarma项目的所有业务逻辑服务，负责处理具体的业务操作。

## 📄 文件列表

### `detection_service.py`
- **地位**: 订单检测服务
- **功能**:
  - 从屏幕截图中检测客户订单
  - 识别订单中的配方、是否加急、调料偏好
  - 使用图像识别技术匹配模板
- **输入**: 配置对象、配方列表、屏幕截图
- **输出**: Order对象或None（当无订单时）

### `cooking_service.py`
- **地位**: 烹饪操作服务
- **功能**:
  - 执行游戏中的烹饪操作（滑动、点击）
  - 管理烹饪设备的并发访问（使用锁）
  - 处理原料囤积和组装站操作
  - 完成订单（添加调料、上菜）
- **输入**: 配方对象、目标位置、锁定状态
- **输出**: 异步操作结果

### `recipe_manager.py`
- **地位**: 配方管理服务
- **功能**:
  - 从JSON文件加载配方数据
  - 提供配方查询接口
  - 维护配方到对象的映射
- **输入**: JSON文件路径
- **输出**: Recipe对象列表

## 🔗 模块间关系
```
CookingBotApp (app.py)
    ↓
    ├─→ DetectionService (检测新订单)
    ├─→ CookingService (执行烹饪)
    └─→ RecipeManager (管理配方数据)
            ↓
    返回 Recipe 对象
```

## 🔒 并发控制
- **cooking_service.py**: 使用asyncio.Lock管理烹饪设备、组装站和stockpile区的并发访问
- **detection_service.py**: 无并发控制，主要为同步操作
- **recipe_manager.py**: 无并发控制，主要为只读操作

## ⚠️ 重要提示
**一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**
