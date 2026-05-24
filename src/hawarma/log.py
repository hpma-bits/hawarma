"""
日志配置模块

地位：使用 loguru 配置应用日志系统，同时输出到终端和日志文件

输入：日志级别
输出：无（配置全局 logger）

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新
"""

import sys
from pathlib import Path

from loguru import logger

from hawarma.paths import log_dir


def setup_logging(log_level: str = "INFO", terminal: bool = True, log_name: str = "game") -> None:
    """
    配置日志系统。

    Args:
        log_level: 终端日志级别（文件始终为 DEBUG）
        terminal: 是否输出到终端 stderr。TUI 模式设为 False 避免终端刷屏
        log_name: 日志文件名前缀，如 "game" → logs/game_{timestamp}.log
    """
    import logging
    logging.getLogger("airtest").setLevel(logging.WARNING)
    logging.getLogger("pocoui").setLevel(logging.WARNING)

    logger.remove()

    if terminal:
        logger.add(
            sys.stderr,
            level=log_level,
            format="<green>{time:HH:mm:ss.SSS}</green> | "
                   "<level>{level: <8}</level> | "
                   "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                   "<level>{message}</level>",
            colorize=True,
        )

    log_path = log_dir()
    log_path.mkdir(exist_ok=True)

    logger.add(
        str(log_path / f"{log_name}_{{time:YYYYMMDD_HHmmss}}.log"),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        encoding="utf-8",
        enqueue=True,
    )

    logger.info(f"Logging initialized (terminal={terminal}, log_name={log_name})")
