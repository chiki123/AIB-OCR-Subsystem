"""
AIB OCR Subsystem — Celery Application
Конфигурация и инициализация Celery
"""
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "aib_ocr",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    # Сериализация
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Moscow",
    enable_utc=True,

    # Лимиты времени
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,

    # Надёжность
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,

    # Очереди
    task_queues={
        "ocr_processing": {"exchange": "ocr_processing", "routing_key": "ocr_processing"},
        "integration":    {"exchange": "integration",    "routing_key": "integration"},
    },
    task_default_queue="ocr_processing",

    # Результаты: хранить 24 часа
    result_expires=86400,

    # Периодические задачи (Beat)
    beat_schedule={
        # Повторная отправка неотправленных документов в 1С каждые 10 минут
        "retry-pending-sync": {
            "task": "aib_ocr.retry_pending_sync",
            "schedule": 600,  # 10 минут
        },
        # Очистка старых логов раз в день
        "cleanup-old-logs": {
            "task": "aib_ocr.cleanup_old_logs",
            "schedule": 86400,  # 24 часа
        },
    },
)
