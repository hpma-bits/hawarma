# src/hawarma/services 目录架构

## 📁 目录概述

此目录包含服务层组件，提供配方管理等业务逻辑。

## ⚠️ 重要提示

**一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**

## 📄 文件列表

### `__init__.py`
- **地位**: 包初始化文件
- **导出**: `RecipeManager`

### `recipe_manager.py`
- **地位**: 配方管理服务
- **状态**: ✅ 完成
- **功能**: 从 JSON 文件加载和管理配方数据
- **输入**: JSON 文件路径
- **输出**: Recipe 对象列表

## 🔗 模块间关系

```
RealGameBridge
    ↓
RecipeManager → data/recipes.json
```
