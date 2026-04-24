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


def setup_logging(log_level: str = "INFO") -> None:
    """
    配置日志：终端 + 文件。

    终端：带颜色，显示 INFO 及以上。
    文件：logs/game_{时间戳}.log，纯文本，包含所有级别。
    """
    import logging
    logging.getLogger("airtest").setLevel(logging.WARNING)
    logging.getLogger("pocoui").setLevel(logging.WARNING)

    logger.remove()

    # 终端输出
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:HH:mm:ss.SSS}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>",
        colorize=True,
    )

    # 日志文件
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    logger.add(
        str(log_dir / "game_{time:YYYYMMDD_HHmmss}.log"),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        encoding="utf-8",
        enqueue=True,  # 线程安全
    )

    logger.info("Logging initialized.")
