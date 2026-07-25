"""
GS-Prep Backend — Logging Configuration

Provides a consistent logging setup across all modules.
"""

import logging
import sys

from app.core.config import settings


def setup_logging() -> logging.Logger:
    """
    Configure and return the application root logger.

    Returns:
        logging.Logger: Configured root logger instance.
    """
    log_level = logging.DEBUG if settings.debug else logging.INFO

    # Root logger configuration
    logger = logging.getLogger("gs_prep")
    logger.setLevel(log_level)

    # Prevent duplicate handlers on reload
    if logger.handlers:
        return logger

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    # Formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


# Module-level logger for direct import
logger = setup_logging()
