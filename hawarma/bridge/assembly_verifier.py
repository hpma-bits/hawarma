"""
组装站提交验证器

地位：可插拔组件，在送餐后验证组装站是否正确清空
      通过模板匹配检测 assembly 区域是否为空

输入：配置对象
输出：验证结果（成功/失败），失败时触发 fallback 清理

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from airtest.core.api import G, Template
from airtest.aircv import crop_image
from loguru import logger

from hawarma.config import AppConfig


class AssemblyVerifier:
    """
    组装站提交验证器

    在送餐后检测组装站区域是否已清空。
    如果未清空，说明提交失败，需要触发 fallback 清理。
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.image_dir = Path(config.image_directory)
        self.assembly_region: tuple[int, int, int, int] = (1150, 720, 1600, 1030)
        self._empty_template: Optional[Template] = None
        self._load_template()

    def _load_template(self) -> None:
        """加载空组装站模板"""
        empty_path = self.image_dir / "empty_assembly.jpg"
        if not empty_path.exists():
            logger.warning(f"Empty assembly template not found: {empty_path}")
            return
        self._empty_template = Template(str(empty_path), threshold=0.7)
        logger.info(f"AssemblyVerifier loaded template from {empty_path}")

    def is_assembly_empty(self) -> bool:
        """
        检测组装站区域是否为空

        Returns:
            True 如果区域为空（提交成功），False 如果区域不为空（提交失败）
        """
        if self._empty_template is None:
            logger.warning("AssemblyVerifier: template not loaded, assuming empty")
            return True

        screen = G.DEVICE.snapshot()
        if screen is None:
            logger.warning("AssemblyVerifier: failed to take snapshot")
            return True

        cropped = crop_image(screen, self.assembly_region)
        match = self._empty_template._cv_match(cropped)
        return match is not None
