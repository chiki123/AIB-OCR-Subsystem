"""
AIB OCR Subsystem — Pydantic Schemas
Схемы для валидации запросов и ответов API
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

from app.schemas.enums import DocumentType, SourceType, ProcessingStatus, SyncStatus


# ── Upload Response ──────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    """Ответ на загрузку документа — возвращается немедленно"""
    task_id: str = Field(..., description="Celery task ID для отслеживания прогресса")
    document_id: str = Field(..., description="UUID документа в базе данных")
    status: str = Field(default="queued", description="Начальный статус")
    message: str = Field(default="Документ принят в обработку")
    status_url: str = Field(..., description="URL для проверки статуса")


# ── Task Status ──────────────────────────────────────────────────────────────

class TaskStatusResponse(BaseModel):
    """Статус задачи Celery"""
    task_id: str
    document_id: Optional[str] = None
    status: ProcessingStatus
    progress: int = Field(default=0, ge=0, le=100, description="Прогресс в процентах")
    stage: Optional[str] = Field(None, description="Текущий этап обработки")
    message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── Extracted Document Data ───────────────────────────────────────────────────

class LineItem(BaseModel):
    """Строка табличной части документа"""
    name: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    price: Optional[float] = None
    amount: Optional[float] = None
    vat_rate: Optional[str] = None
    vat_amount: Optional[float] = None
    amount_with_vat: Optional[float] = None


class ExtractedFields(BaseModel):
    """Извлечённые поля документа"""
    supplier_name: Optional[str] = None
    supplier_inn: Optional[str] = None
    supplier_kpp: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_inn: Optional[str] = None
    buyer_kpp: Optional[str] = None
    document_number: Optional[str] = None
    document_date: Optional[str] = None
    total_amount: Optional[float] = None
    vat_amount: Optional[float] = None
    currency: str = "RUB"
    line_items: List[LineItem] = Field(default_factory=list)


class DocumentResult(BaseModel):
    """Полный результат обработки документа"""
    document_id: str
    task_id: Optional[str] = None
    document_type: Optional[DocumentType] = None
    source_type: SourceType
    status: ProcessingStatus
    sync_status: SyncStatus
    confidence_score: Optional[float] = None
    original_filename: str
    extracted_fields: Optional[ExtractedFields] = None
    created_at: datetime
    processed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Document List ─────────────────────────────────────────────────────────────

class DocumentListItem(BaseModel):
    """Элемент списка документов"""
    document_id: str
    document_type: Optional[DocumentType] = None
    source_type: SourceType
    status: ProcessingStatus
    sync_status: SyncStatus
    original_filename: str
    confidence_score: Optional[float] = None
    created_at: datetime


class DocumentListResponse(BaseModel):
    """Список документов с пагинацией"""
    items: List[DocumentListItem]
    total: int
    page: int
    page_size: int
    pages: int


# ── Health Check ──────────────────────────────────────────────────────────────

class ServiceStatus(BaseModel):
    name: str
    status: str  # healthy / unhealthy / degraded
    latency_ms: Optional[float] = None
    details: Optional[str] = None


class HealthResponse(BaseModel):
    """Статус всех сервисов системы"""
    status: str  # healthy / degraded / unhealthy
    version: str
    services: List[ServiceStatus]
    timestamp: datetime


# ── 1С Integration ────────────────────────────────────────────────────────────

class SendTo1CRequest(BaseModel):
    """Запрос на ручную отправку в 1С"""
    document_id: str
    force: bool = Field(default=False, description="Принудительно отправить даже при низкой уверенности")


class SendTo1CResponse(BaseModel):
    """Результат отправки в 1С"""
    document_id: str
    success: bool
    message: str
    c1_response: Optional[Dict[str, Any]] = None
