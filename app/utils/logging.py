"""
AIB OCR Subsystem — Logging (Local Dev Version)
"""
import sys
import logging
from pathlib import Path
from loguru import logger
from app.core.config import settings


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging() -> None:
    logger.remove()

    log_level = settings.LOG_LEVEL.upper()

    # Всегда цветной вывод в терминал для локальной разработки
    logger.add(
        sys.stdout,
        level=log_level,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
        enqueue=False,
        backtrace=True,
        diagnose=True,
    )

    # Файловый лог
    try:
        log_file = settings.log_file_abs
        logger.add(
            log_file,
            level=log_level,
            rotation="50 MB",
            retention="7 days",
            encoding="utf-8",
            enqueue=True,
        )
    except Exception as e:
        logger.warning(f"Не удалось создать файловый лог: {e}")

    # Перехватываем стандартные логи
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for name in ["uvicorn", "uvicorn.error", "uvicorn.access",
                 "fastapi", "sqlalchemy.engine", "celery"]:
        lg = logging.getLogger(name)
        lg.handlers = [InterceptHandler()]
        lg.propagate = False

    logger.info(f"Логирование настроено: {log_level}")