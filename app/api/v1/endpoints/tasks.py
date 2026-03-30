"""
AIB OCR Subsystem — Tasks Endpoints
Отслеживание статуса задач Celery

GET /tasks/{task_id}/status — статус и прогресс задачи
"""
from datetime import datetime
from typing import Optional

from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.base import get_db
from app.models.document import Document
from app.schemas.enums import ProcessingStatus
from app.schemas.document import TaskStatusResponse
from app.workers.celery_app import celery_app

router = APIRouter()

# Маппинг статусов Celery → наши статусы
CELERY_STATE_MAP = {
    "PENDING":  ProcessingStatus.PENDING,
    "STARTED":  ProcessingStatus.PROCESSING,
    "PROGRESS": ProcessingStatus.PROCESSING,
    "SUCCESS":  ProcessingStatus.SUCCESS,
    "FAILURE":  ProcessingStatus.FAILED,
    "RETRY":    ProcessingStatus.RETRY,
    "REVOKED":  ProcessingStatus.FAILED,
}

# Прогресс по этапам (приблизительный)
STAGE_PROGRESS = {
    "preprocessor": 20,
    "ocr":          50,
    "classifier":   60,
    "extractor":    75,
    "validator":    85,
    "integrator":   95,
}


@router.get(
    "/{task_id}/status",
    response_model=TaskStatusResponse,
    summary="Статус задачи обработки",
    description="""
Возвращает текущий статус задачи Celery.

**Статусы:**
- `pending` — ожидает в очереди
- `processing` — обрабатывается
- `success` — успешно завершено
- `failed` — ошибка
- `retry` — повторная попытка
    """,
)
async def get_task_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Возвращает статус задачи Celery"""

    # Получаем результат из Celery (Redis backend)
    celery_result = AsyncResult(task_id, app=celery_app)
    celery_state = celery_result.state  # PENDING / STARTED / SUCCESS / FAILURE / ...

    # Ищем документ в БД по celery_task_id
    db_result = await db.execute(
        select(Document).options(selectinload(Document.processing_logs)).where(Document.celery_task_id == task_id)
    )
    document = db_result.scalar_one_or_none()

    # Определяем статус
    status = CELERY_STATE_MAP.get(celery_state, ProcessingStatus.PENDING)

    # Если документ есть в БД — берём статус из него (более точный)
    if document:
        status = document.status

    # Прогресс
    progress = 0
    stage = None
    if celery_state == "SUCCESS":
        progress = 100
    elif celery_state in ("STARTED", "PROGRESS"):
        progress = 10
        # Определяем прогресс из последнего лога
        if document and document.processing_logs:
            last_log = document.processing_logs[-1]
            stage = last_log.stage
            progress = STAGE_PROGRESS.get(last_log.stage, 30)

    # Результат (если успех)
    result_data = None
    error_message = None
    document_id = str(document.id) if document else None

    if celery_state == "SUCCESS" and celery_result.result:
        result_data = celery_result.result
    elif celery_state == "FAILURE":
        error_message = str(celery_result.result) if celery_result.result else "Неизвестная ошибка"

    return TaskStatusResponse(
        task_id=task_id,
        document_id=document_id,
        status=status,
        progress=progress,
        stage=stage,
        result=result_data,
        error=error_message,
        created_at=document.created_at if document else None,
        updated_at=document.updated_at if document else None,
    )
