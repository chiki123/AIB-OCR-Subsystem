"""
AIB OCR Subsystem — Database Models
"""
import uuid
from typing import Dict, Any
from sqlalchemy import (
    Column, String, Float, DateTime, Text, 
    Enum as SAEnum, ForeignKey, Integer
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.schemas.enums import DocumentType, SourceType, ProcessingStatus, SyncStatus


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    source_type = Column(
        SAEnum(SourceType, name="source_type_enum", values_callable=lambda obj: [e.value for e in obj]), 
        nullable=False
    )
    document_type = Column(
        SAEnum(DocumentType, name="document_type_enum", values_callable=lambda obj: [e.value for e in obj]),
        nullable=True
    )
    
    original_filename = Column(String(500), nullable=False)
    file_path = Column(Text, nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    mime_type = Column(String(100), nullable=False)
    
    status = Column(
        SAEnum(ProcessingStatus, name="processing_status_enum", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=ProcessingStatus.PENDING
    )
    sync_status = Column(
        SAEnum(SyncStatus, name="sync_status_enum", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=SyncStatus.PENDING
    )
    
    celery_task_id = Column(String(255), nullable=True, index=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)
    
    extracted_data = relationship("ExtractedData", back_populates="document", uselist=False)
    processing_logs = relationship("ProcessingLog", back_populates="document", order_by="ProcessingLog.created_at")


class ExtractedData(Base):
    __tablename__ = "extracted_data"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True)
    
    confidence_score = Column(Float, nullable=True)
    
    supplier_name = Column(String(500), nullable=True)
    supplier_inn = Column(String(12), nullable=True)
    supplier_kpp = Column(String(9), nullable=True)
    buyer_name = Column(String(500), nullable=True)
    buyer_inn = Column(String(12), nullable=True)
    buyer_kpp = Column(String(9), nullable=True)
    document_number = Column(String(100), nullable=True)
    document_date = Column(String(20), nullable=True)
    total_amount = Column(Float, nullable=True)
    vat_amount = Column(Float, nullable=True)
    currency = Column(String(10), default="RUB")
    
    line_items = Column(JSONB, nullable=True)
    raw_fields = Column(JSONB, nullable=True)
    raw_ocr_text = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    document = relationship("Document", back_populates="extracted_data")

    def to_1c_payload(self) -> Dict[str, Any]:
        return {
            "document_type": self.document.document_type.value if self.document.document_type else None,
            "recognition_confidence": self.confidence_score,
            "source_type": self.document.source_type.value,
            "original_filename": self.document.original_filename,
            "data": {
                "supplier_name": self.supplier_name,
                "supplier_inn": self.supplier_inn,
                "supplier_kpp": self.supplier_kpp,
                "buyer_name": self.buyer_name,
                "buyer_inn": self.buyer_inn,
                "buyer_kpp": self.buyer_kpp,
                "document_number": self.document_number,
                "document_date": self.document_date,
                "total_amount": self.total_amount,
                "vat_amount": self.vat_amount,
                "currency": self.currency,
                "line_items": self.line_items or [],
            }
        }


class ProcessingLog(Base):
    __tablename__ = "processing_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    
    stage = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)
    message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    document = relationship("Document", back_populates="processing_logs")
