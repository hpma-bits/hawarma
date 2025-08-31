# hawarma/logging_setup.py
import sys
from loguru import logger

def setup_logging(log_level="INFO"):
    """
    Configures the application's logging using Loguru.
    """
    logger.remove()
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>",
        colorize=True,
    )
    logger.add(
        "logs/app_{time}.log",
        level=log_level,
        rotation="10 MB",
        retention="10 days",
        format="{time} {level} {message}",
        encoding="utf-8",
    )
    logger.info("Logging has been set up.")

