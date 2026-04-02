"""
Services Package

地位：包含服务层组件。

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from hawarma.services.recipe_manager import RecipeManager

__all__ = ["RecipeManager"]
