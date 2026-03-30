"""
AIB OCR Subsystem — Celery Tasks
Главный оркестратор пайплайна обработки документов

Цепочка задач:
  process_document_task
    → classify → preprocess → ocr → extract → validate → integrate_1c
    
ВАЖНО: PaddleOCR инициализируется один раз при старте воркера (Singleton)
"""
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any

from celery import Task
from loguru import logger

from app.workers.celery_app import celery_app
from app.core.config import settings
from app.schemas.enums import (
    DocumentType, ProcessingStatus, SyncStatus, PipelineStage
)
from app.services.classifier import DocumentClassifier
from app.services.preprocessor import ImagePreprocessor
from app.services.ocr_engine import OCREngine
from app.services.extractor import EntityExtractor
from app.services.validator import DataValidator
from app.services.integrator_1c import Integrator1C


# ── Сервисы (инициализируются один раз на воркер) ────────────────────────────
classifier = DocumentClassifier()
preprocessor = ImagePreprocessor()
ocr_engine = OCREngine()
extractor = EntityExtractor()
validator = DataValidator()
integrator = Integrator1C()


class DatabaseTask(Task):
    """
    Базовый класс задачи с доступом к синхронной БД.
    Celery worker использует синхронный SQLAlchemy.
    """
    _db = None
    
    @property
    def db(self):
        if self._db is None:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            engine = create_engine(settings.DATABASE_URL_SYNC)
            Session = sessionmaker(bind=engine)
            self._db = Session()
        return self._db


# ── Главная задача пайплайна ──────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="aib_ocr.process_document",
    queue="ocr_processing",
    max_retries=settings.CELERY_MAX_RETRIES,
    default_retry_delay=settings.CELERY_RETRY_BACKOFF,
    soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    time_limit=settings.CELERY_TASK_TIME_LIMIT,
    acks_late=True,  # Подтверждаем только после успешного завершения
    reject_on_worker_lost=True,
)
def process_document_task(self, document_id: str) -> Dict[str, Any]:
    """
    Главная задача обработки документа.
    
    Оркестрирует весь пайплайн:
    1. Загрузка файла из storage
    2. Предобработка изображения (OpenCV)
    3. OCR (PaddleOCR)
    4. Классификация типа документа
    5. Извлечение данных (Regex)
    6. Валидация данных
    7. Сохранение в БД
    8. Отправка в 1С
    
    Args:
        document_id: UUID документа в базе данных
    """
    start_time = time.time()
    logger.info(f"=== Начало обработки документа {document_id} ===")
    
    from app.models.document import Document, ExtractedData, ProcessingLog
    from app.db.base import Base
    
    db = self.db
    
    # Загружаем документ из БД
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        logger.error(f"Документ {document_id} не найден в БД")
        return {"error": "Document not found", "document_id": document_id}
    
    def log_stage(stage: str, status: str, message: str = "", duration_ms: int = 0):
        """Логирует этап в БД и в файловый лог"""
        log_entry = ProcessingLog(
            document_id=document.id,
            stage=stage,
            status=status,
            message=message,
            duration_ms=duration_ms,
        )
        db.add(log_entry)
        db.commit()
        logger.info(f"[{stage}] {status}: {message}")
    
    def update_status(status: ProcessingStatus):
        document.status = status
        db.commit()
    
    try:
        # ── Шаг 1: Обновляем статус ────────────────────────────────────────
        update_status(ProcessingStatus.PROCESSING)
        
        # ── Шаг 2: Читаем файл ─────────────────────────────────────────────
        file_path = Path(document.file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Файл не найден: {file_path}")
        
        file_bytes = file_path.read_bytes()
        log_stage(PipelineStage.PREPROCESSOR, "started", f"Размер файла: {len(file_bytes)} байт")
        
        # ── Шаг 3: Предобработка ───────────────────────────────────────────
        t = time.time()
        
        if document.mime_type == "application/pdf":
            # PDF → список страниц
            images = preprocessor.pdf_to_images(file_bytes)
            # Для MVP берём первую страницу
            processed_image = preprocessor.preprocess_for_paddle(images[0])
        else:
            processed_image = preprocessor.preprocess_for_paddle(file_bytes)
        
        preprocess_ms = int((time.time() - t) * 1000)
        log_stage(PipelineStage.PREPROCESSOR, "success", 
                  f"Предобработка завершена", preprocess_ms)
        
        # ── Шаг 4: OCR ─────────────────────────────────────────────────────
        t = time.time()
        log_stage(PipelineStage.OCR, "started")
        
        ocr_result = ocr_engine.recognize_with_structure(processed_image)
        full_text = ocr_result["full_text"]
        ocr_confidence = ocr_result["avg_confidence"]
        
        ocr_ms = int((time.time() - t) * 1000)
        log_stage(PipelineStage.OCR, "success",
                  f"Распознано {len(full_text)} символов, "
                  f"уверенность {ocr_confidence:.2f}",
                  ocr_ms)
        
        if not full_text.strip():
            raise ValueError("OCR не смог извлечь текст из документа")
        
        # ── Шаг 5: Классификация ───────────────────────────────────────────
        t = time.time()
        doc_type, class_confidence = classifier.classify(full_text)
        class_ms = int((time.time() - t) * 1000)
        
        document.document_type = doc_type
        db.commit()
        log_stage(PipelineStage.CLASSIFIER, "success",
                  f"Тип: {doc_type.value}, уверенность: {class_confidence:.2f}",
                  class_ms)
        
        # ── Шаг 6: Извлечение данных ───────────────────────────────────────
        t = time.time()
        log_stage(PipelineStage.EXTRACTOR, "started")
        
        extracted_fields = extractor.extract(
            full_text, 
            doc_type,
            ocr_blocks=ocr_result.get("blocks"),
        )
        extract_ms = int((time.time() - t) * 1000)
        
        filled_count = sum(1 for v in extracted_fields.values() if v is not None)
        log_stage(PipelineStage.EXTRACTOR, "success",
                  f"Извлечено {filled_count}/{len(extracted_fields)} полей",
                  extract_ms)
        
        # ── Шаг 7: Валидация ───────────────────────────────────────────────
        validation_result, adjusted_confidence = validator.validate(
            extracted_fields,
            doc_type,
            initial_confidence=min(ocr_confidence, class_confidence),
        )
        
        if validation_result.errors:
            log_stage(PipelineStage.VALIDATOR, "warning",
                      f"Ошибки: {'; '.join(validation_result.errors)}")
        else:
            log_stage(PipelineStage.VALIDATOR, "success",
                      f"Валидация пройдена. Уверенность: {adjusted_confidence:.2f}")
        
        # ── Шаг 8: Сохранение в БД ─────────────────────────────────────────
        extracted_data = ExtractedData(
            document_id=document.id,
            confidence_score=adjusted_confidence,
            supplier_name=extracted_fields.get("supplier_name"),
            supplier_inn=extracted_fields.get("supplier_inn"),
            supplier_kpp=extracted_fields.get("supplier_kpp"),
            buyer_name=extracted_fields.get("buyer_name"),
            buyer_inn=extracted_fields.get("buyer_inn"),
            buyer_kpp=extracted_fields.get("buyer_kpp"),
            document_number=extracted_fields.get("document_number"),
            document_date=extracted_fields.get("document_date"),
            total_amount=extracted_fields.get("total_amount"),
            vat_amount=extracted_fields.get("vat_amount"),
            currency="RUB",
            raw_fields=extracted_fields,
            raw_ocr_text=full_text[:10000],  # Ограничиваем размер
        )
        db.add(extracted_data)
        
        # Обновляем статус документа
        from datetime import datetime
        document.status = ProcessingStatus.SUCCESS
        document.processed_at = datetime.utcnow()
        db.commit()
        
        total_ms = int((time.time() - start_time) * 1000)
        logger.success(
            f"=== Документ {document_id} обработан за {total_ms}мс. "
            f"Тип: {doc_type.value}, уверенность: {adjusted_confidence:.2f} ==="
        )
        
        # ── Шаг 9: Отправка в 1С ──────────────────────────────────────────
        # Отправляем в 1С если уверенность выше порога
        if adjusted_confidence >= 0.6:
            integrate_1c_task.apply_async(
                args=[document_id],
                queue="integration",
                countdown=2,  # Небольшая задержка для гарантии записи в БД
            )
        else:
            document.sync_status = SyncStatus.SKIPPED
            db.commit()
            log_stage(PipelineStage.INTEGRATOR, "skipped",
                      f"Уверенность {adjusted_confidence:.2f} ниже порога 0.6 — требуется ручная проверка")
        
        return {
            "document_id": document_id,
            "document_type": doc_type.value,
            "confidence": adjusted_confidence,
            "status": "success",
            "processing_time_ms": total_ms,
        }
    
    except Exception as exc:
        logger.error(f"Ошибка обработки документа {document_id}: {exc}", exc_info=True)
        
        # Обновляем статус
        document.status = ProcessingStatus.FAILED
        db.commit()
        
        # Retry при временных ошибках
        if self.request.retries < self.max_retries:
            retry_delay = settings.CELERY_RETRY_BACKOFF * (2 ** self.request.retries)
            logger.info(f"Повтор через {retry_delay} сек (попытка {self.request.retries + 1})")
            raise self.retry(exc=exc, countdown=retry_delay)
        
        log_stage("pipeline", "error", str(exc)[:500])
        raise


# ── Задача интеграции с 1С ───────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="aib_ocr.integrate_1c",
    queue="integration",
    max_retries=3,
    default_retry_delay=30,
)
def integrate_1c_task(self, document_id: str) -> Dict[str, Any]:
    """Отдельная задача отправки данных в 1С"""
    from app.models.document import Document
    
    db = self.db
    document = db.query(Document).filter(Document.id == document_id).first()
    
    if not document or not document.extracted_data:
        logger.error(f"1С интеграция: документ или данные не найдены ({document_id})")
        return {"error": "Not found"}
    
    payload = document.extracted_data.to_1c_payload()
    
    try:
        success, response = integrator.send_document(document_id, payload)
        
        if success:
            document.sync_status = SyncStatus.SENT
            db.commit()
            logger.success(f"1С: документ {document_id} успешно отправлен")
            return {"status": "sent", "c1_response": response}
        else:
            document.sync_status = SyncStatus.FAILED
            db.commit()
            return {"status": "failed", "error": response}
    
    except Exception as exc:
        document.sync_status = SyncStatus.FAILED
        db.commit()
        
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
        raise
