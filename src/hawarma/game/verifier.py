"""
组装站提交验证器

地位：可插拔组件，在送餐后验证组装站是否正确清空
      通过模板匹配检测 assembly 区域是否为空

fail-closed（Issue #20）：
- 模板缺失 / snapshot 失败或异常 → 返回 False + logger.error，
  不再 "assume empty" 当作成功——验证器静默失效会让 serve 失败被当
  成成功打分。返回 False 触发 runner 现有的 serve 重试 → 清 assembly
  安全路径
- 模板缺失额外打一次性熔断提示（类级 flag，进程内首个请求提示后
  不再重复刷屏）

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
from hawarma.paths import resolve_path


class Verifier:
    """
    组装站提交验证器

    在送餐后检测组装站区域是否已清空。
    如果未清空，说明提交失败，需要触发 fallback 清理。

    fail-closed（Issue #20）：任何无法完成验证的情况（模板缺失、
    snapshot 返回 None 或抛异常）都返回 False（验证失败），
    绝不静默当作成功。
    """

    # 类级熔断提示 flag（Issue #20）：模板缺失的详细提示进程内只打一次，
    # 之后每次只打单行 error，避免每个 serve 验证都刷屏
    _template_missing_hint_shown: bool = False

    def __init__(self, config: AppConfig):
        self.config = config
        self.image_dir = resolve_path(config.image_directory)
        self.assembly_region: tuple[int, int, int, int] = tuple(config.screen.assembly_region)
        self._empty_template: Optional[Template] = None
        self._save_debug = config.debug.save_assembly_verify_screenshots
        self._debug_dir = resolve_path(config.debug.screenshot_directory) / "assembly_verify"
        if self._save_debug and not self._debug_dir.exists():
            self._debug_dir.mkdir(parents=True, exist_ok=True)
        self._load_template()

    def _load_template(self) -> None:
        """加载空组装站模板"""
        empty_path = self.image_dir / "empty_assembly.jpg"
        if not empty_path.exists():
            logger.warning(f"Empty assembly template not found: {empty_path}")
            return
        threshold = self.config.matching.assembly_threshold
        self._empty_template = Template(str(empty_path), threshold=threshold)
        logger.info(f"Verifier loaded template from {empty_path} (threshold={threshold})")

    def is_assembly_empty(self) -> bool:
        """
        检测组装站区域是否为空（fail-closed，Issue #20）

        Returns:
            True 如果区域为空（提交成功）
            False 如果区域不为空（提交失败），或无法完成验证
            （模板缺失 / snapshot 失败 / 匹配过程异常）
        """
        if self._empty_template is None:
            logger.error(
                "Verifier: empty-assembly template not loaded, "
                "failing closed (serve treated as failed)"
            )
            if not Verifier._template_missing_hint_shown:
                Verifier._template_missing_hint_shown = True
                logger.error(
                    "Verifier circuit-breaker: template missing, ALL serve "
                    "verifications will fail closed and assemblies be "
                    "discarded. Provide static/img/empty_assembly.jpg to "
                    "restore verification. (This hint is logged once per "
                    "process.)"
                )
            return False

        try:
            screen = G.DEVICE.snapshot()
            if screen is None:
                logger.error(
                    "Verifier: failed to take snapshot, failing closed "
                    "(serve treated as failed)"
                )
                return False

            cropped = crop_image(screen, self.assembly_region)
            match = self._empty_template._cv_match(cropped)
        except Exception as e:
            logger.exception(f"Verifier: snapshot/match failed, failing closed: {e}")
            return False

        is_empty = match is not None

        if self._save_debug:
            self._save_debug_screenshot(screen, is_empty)

        return is_empty

    def _save_debug_screenshot(self, screen, is_empty: bool) -> None:
        """保存完整调试截图"""
        try:
            import cv2
            import time

            timestamp = int(time.time() * 1000)
            status = "empty" if is_empty else "not_empty"
            filename = f"assembly_full_{timestamp}_{status}.jpg"
            filepath = self._debug_dir / filename
            cv2.imwrite(str(filepath), screen)
            logger.debug(f"Saved assembly verify debug: {filename}")
        except Exception as e:
            logger.warning(f"Failed to save assembly verify debug: {e}")
