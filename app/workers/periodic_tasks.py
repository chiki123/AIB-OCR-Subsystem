"""
AIB OCR Subsystem — Periodic Tasks (Celery Beat)
Периодические задачи: повторная синхронизация с 1С и очистка старых данных
"""
from datetime import datetime, timedelta
from loguru import logger

from app.workers.celery_app import celery_app
from app.workers.tasks import DatabaseTask
from app.schemas.enums import SyncStatus, ProcessingStatus


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="aib_ocr.retry_pending_sync",
    queue="integration",
)
def retry_pending_sync(self):
    """
    Каждые 10 минут повторно отправляет документы в 1С
    со статусом sync_status=failed.
    
    Защищает от потери данных при временной недоступности 1С.
    """
    from app.models.document import Document
    from app.workers.tasks import integrate_1c_task
    
    db = self.db
    
    # Ищем документы с ошибкой синхронизации старше 5 минут
    cutoff = datetime.utcnow() - timedelta(minutes=5)
    
    failed_docs = db.query(Document).filter(
        Document.sync_status == SyncStatus.FAILED,
        Document.status == ProcessingStatus.SUCCESS,
        Document.processed_at < cutoff,
    ).limit(10).all()
    
    if not failed_docs:
        logger.debug("retry_pending_sync: нет документов для повторной отправки")
        return {"retried": 0}
    
    count = 0
    for doc in failed_docs:
        try:
            integrate_1c_task.apply_async(
                args=[str(doc.id)],
                queue="integration",
                countdown=count * 5,  # Разносим запросы
            )
            count += 1
            logger.info(f"Повторная отправка в 1С: document_id={doc.id}")
        except Exception as e:
            logger.error(f"Ошибка постановки задачи {doc.id}: {e}")
    
    logger.info(f"retry_pending_sync: поставлено {count} задач")
    return {"retried": count}


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="aib_ocr.cleanup_old_logs",
    queue="ocr_processing",
)
def cleanup_old_logs(self):
    """
    Раз в сутки удаляет старые записи ProcessingLog (> 30 дней).
    Предотвращает неограниченный рост таблицы.
    """
    from app.models.document import ProcessingLog
    
    db = self.db
    cutoff = datetime.utcnow() - timedelta(days=30)
    
    deleted = db.query(ProcessingLog).filter(
        ProcessingLog.created_at < cutoff
    ).delete()
    db.commit()
    
    logger.info(f"cleanup_old_logs: удалено {deleted} записей логов")
    return {"deleted": deleted}
