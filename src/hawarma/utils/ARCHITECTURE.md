# src/hawarma/utils Directory Architecture

## 📁 目录概述
此目录包含hawarma项目的工具函数，提供通用的辅助功能。

## ⚠️ 重要提示
**一旦本目录有变化（新增/删除/重命名文件），请立即更新本文档！**

## 📄 文件列表

### `image_utils.py`
- **地位**: 图像处理工具模块
- **功能**:
  - 在屏幕的指定区域中查找模板图像
  - 使用airtest框架进行图像匹配
  - 支持调试图像保存
- **输入**: Template对象、ROI区域、屏幕截图
- **输出**: 匹配结果坐标或None

## 🔗 模块间关系
```
OrderScanner (bridge/scanner.py)
    ↓
local_match (image_utils.py)
```
