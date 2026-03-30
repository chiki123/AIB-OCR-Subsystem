"""
AIB OCR Subsystem — Documents Endpoints

POST   /documents/upload         — загрузка документа (немедленный ответ)
GET    /documents/                — список документов с фильтрами
GET    /documents/{id}            — результат обработки конкретного документа
POST   /documents/{id}/send-to-1c — ручная отправка в 1С
DELETE /documents/{id}            — удаление документа
"""
import uuid
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter, UploadFile, File, HTTPException,
    Depends, Query, BackgroundTasks
)
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from loguru import logger
from app.workers.tasks import process_document_task
from app.core.config import settings
from app.db.base import get_db
from app.models.document import Document, ExtractedData
from app.schemas.enums import DocumentType, SourceType, ProcessingStatus, SyncStatus
from app.schemas.document import (
    UploadResponse, DocumentResult, DocumentListResponse,
    DocumentListItem, ExtractedFields, LineItem,
    SendTo1CRequest, SendTo1CResponse,
)

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _validate_file(file: UploadFile) -> None:
    """Валидирует загружаемый файл"""
    # Проверка расширения
    ext = Path(file.filename).suffix.lower().lstrip(".")
    if ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимый формат файла: .{ext}. "
                   f"Разрешены: {', '.join(settings.allowed_extensions_list)}"
        )


def _detect_source_type(file: UploadFile) -> SourceType:
    """Определяет тип источника по MIME"""
    mime = file.content_type or ""
    if "pdf" in mime:
        return SourceType.FILE_UPLOAD
    elif "image" in mime:
        return SourceType.IMAGE_UPLOAD
    return SourceType.FILE_UPLOAD


async def _save_upload(file: UploadFile, document_id: str) -> tuple[Path, int, str]:
    """Сохраняет загруженный файл в storage"""
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename).suffix.lower()
    # Структура: uploads/YYYY-MM/document_id.ext
    dated_dir = upload_dir / datetime.now().strftime("%Y-%m")
    dated_dir.mkdir(parents=True, exist_ok=True)

    file_path = dated_dir / f"{document_id}{ext}"

    # Читаем и сохраняем
    contents = await file.read()
    file_path.write_bytes(contents)
    file_size = len(contents)

    mime_type = file.content_type or "application/octet-stream"
    return file_path, file_size, mime_type


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=202,
    summary="Загрузить документ для обработки",
    description="""
Принимает файл (PDF/JPG/PNG/TIFF) и немедленно возвращает task_id.
Обработка выполняется асинхронно в фоне.
Используйте `/tasks/{task_id}/status` для отслеживания прогресса.
    """,
)
async def upload_document(
    file: UploadFile = File(..., description="Файл документа (PDF, JPG, PNG, TIFF)"),
    db: AsyncSession = Depends(get_db),
):
    """Загрузка документа — основной endpoint системы"""

    _validate_file(file)

    doc_id = str(uuid.uuid4())

    # Сохраняем файл
    try:
        file_path, file_size, mime_type = await _save_upload(file, doc_id)
    except Exception as e:
        logger.error(f"Ошибка сохранения файла: {e}")
        raise HTTPException(status_code=500, detail="Ошибка сохранения файла")

    # Проверяем размер
    if file_size > settings.max_upload_bytes:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=413,
            detail=f"Файл слишком большой: {file_size // 1024 // 1024}MB. "
                   f"Максимум: {settings.MAX_UPLOAD_SIZE_MB}MB"
        )

    # 1. Генерируем task_id заранее (Создаем ID المهمة مسبقا)
    task_id_str = str(uuid.uuid4())

    # 2. Создаём запись в БД и сохраняем task_id
    document = Document(
        id=doc_id,
        source_type=_detect_source_type(file),
        original_filename=file.filename,
        file_path=str(file_path),
        file_size_bytes=file_size,
        mime_type=mime_type,
        status=ProcessingStatus.PENDING,
        celery_task_id=task_id_str  # تم حفظه هنا
    )
    
    # 3. Полный коммит в БД ПЕРЕД запуском Celery (حفظ نهائي قبل تشغيل سيليراي)
    db.add(document)
    await db.commit()
    await db.refresh(document)

    # 4. Ставим задачу в очередь Celery
    #from app.workers.tasks import process_document_task
    task = process_document_task.apply_async(
        args=[doc_id],
        queue="ocr_processing",
        task_id=task_id_str, # نستخدم نفس الـ ID
    )

    logger.info(f"Документ принят: {doc_id}, task: {task.id}, файл: {file.filename}")

    return UploadResponse(
        task_id=task.id,
        document_id=doc_id,
        status="queued",
        message=f"Документ «{file.filename}» принят в обработку",
        status_url=f"/api/v1/tasks/{task.id}/status",
    )


@router.get(
    "/",
    response_model=DocumentListResponse,
    summary="Список документов",
)
async def list_documents(
    status: Optional[ProcessingStatus] = Query(None, description="Фильтр по статусу"),
    document_type: Optional[DocumentType] = Query(None, description="Фильтр по типу"),
    sync_status: Optional[SyncStatus] = Query(None, description="Фильтр по статусу 1С"),
    page: int = Query(1, ge=1, description="Номер страницы"),
    page_size: int = Query(20, ge=1, le=100, description="Элементов на странице"),
    db: AsyncSession = Depends(get_db),
):
    """Возвращает список документов с фильтрацией и пагинацией"""

    query = select(Document).options(selectinload(Document.extracted_data))

    if status:
        query = query.where(Document.status == status)
    if document_type:
        query = query.where(Document.document_type == document_type)
    if sync_status:
        query = query.where(Document.sync_status == sync_status)

    # Подсчёт
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Пагинация и сортировка
    query = query.order_by(Document.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    documents = result.scalars().all()

    items = [
        DocumentListItem(
            document_id=str(doc.id),
            document_type=doc.document_type,
            source_type=doc.source_type,
            status=doc.status,
            sync_status=doc.sync_status,
            original_filename=doc.original_filename,
            confidence_score=doc.extracted_data.confidence_score if doc.extracted_data else None,
            created_at=doc.created_at,
        )
        for doc in documents
    ]

    return DocumentListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResult,
    summary="Результат обработки документа",
)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Возвращает полный результат обработки документа включая извлечённые поля"""

    result = await db.execute(
        select(Document).options(selectinload(Document.extracted_data)).where(Document.id == document_id)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail=f"Документ {document_id} не найден")

    # Формируем ответ
    extracted = None
    if document.extracted_data:
        ed = document.extracted_data
        extracted = ExtractedFields(
            supplier_name=ed.supplier_name,
            supplier_inn=ed.supplier_inn,
            supplier_kpp=ed.supplier_kpp,
            buyer_name=ed.buyer_name,
            buyer_inn=ed.buyer_inn,
            buyer_kpp=ed.buyer_kpp,
            document_number=ed.document_number,
            document_date=ed.document_date,
            total_amount=ed.total_amount,
            vat_amount=ed.vat_amount,
            currency=ed.currency or "RUB",
            line_items=[LineItem(**item) for item in (ed.line_items or [])],
        )

    return DocumentResult(
        document_id=str(document.id),
        task_id=document.celery_task_id,
        document_type=document.document_type,
        source_type=document.source_type,
        status=document.status,
        sync_status=document.sync_status,
        confidence_score=document.extracted_data.confidence_score if document.extracted_data else None,
        original_filename=document.original_filename,
        extracted_fields=extracted,
        created_at=document.created_at,
        processed_at=document.processed_at,
    )


@router.post(
    "/{document_id}/send-to-1c",
    response_model=SendTo1CResponse,
    summary="Ручная отправка документа в 1С",
)
async def send_to_1c(
    document_id: str,
    request: SendTo1CRequest,
    db: AsyncSession = Depends(get_db),
):
    """Вручную отправляет обработанный документ в 1С"""

    result = await db.execute(
        select(Document).options(selectinload(Document.extracted_data)).where(Document.id == document_id)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Документ не найден")

    if document.status != ProcessingStatus.SUCCESS:
        raise HTTPException(
            status_code=400,
            detail=f"Документ не обработан (статус: {document.status.value})"
        )

    if not document.extracted_data:
        raise HTTPException(status_code=400, detail="Нет извлечённых данных")

    # Ставим задачу интеграции
    from app.workers.tasks import integrate_1c_task
    task = integrate_1c_task.apply_async(
        args=[document_id],
        queue="integration",
    )

    logger.info(f"Ручная отправка в 1С: document={document_id}, task={task.id}")

    return SendTo1CResponse(
        document_id=document_id,
        success=True,
        message=f"Задача отправки в 1С поставлена в очередь (task_id: {task.id})",
    )


@router.delete(
    "/{document_id}",
    status_code=204,
    summary="Удалить документ",
)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Удаляет документ и связанный файл"""

    result = await db.execute(
        select(Document).options(selectinload(Document.extracted_data)).where(Document.id == document_id)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Документ не найден")

    # Удаляем файл
    file_path = Path(document.file_path)
    if file_path.exists():
        file_path.unlink()

    await db.delete(document)
    await db.commit()

    logger.info(f"Документ удалён: {document_id}")