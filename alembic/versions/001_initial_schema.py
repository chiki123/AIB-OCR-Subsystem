"""create_initial_tables

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-03-18 00:00:00
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Table: documents ─────────────────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id",                UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source_type",       sa.Enum("file_upload", "hot_folder", "image_upload", "mobile", name="source_type_enum"), nullable=False),
        sa.Column("document_type",     sa.Enum("invoice", "upd", "torg12", "unknown", name="document_type_enum"), nullable=True),
        sa.Column("original_filename", sa.String(500),    nullable=False),
        sa.Column("file_path",         sa.Text(),         nullable=False),
        sa.Column("file_size_bytes",   sa.Integer(),      nullable=False),
        sa.Column("mime_type",         sa.String(100),    nullable=False),
        sa.Column("status",            sa.Enum("pending", "processing", "success", "failed", "retry", name="processing_status_enum"), nullable=False, server_default="pending"),
        sa.Column("sync_status",       sa.Enum("pending", "sent", "failed", "skipped", name="sync_status_enum"), nullable=False, server_default="pending"),
        sa.Column("celery_task_id",    sa.String(255),    nullable=True),
        sa.Column("created_at",        sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at",        sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at",      sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_documents_status",         "documents", ["status"])
    op.create_index("ix_documents_celery_task_id", "documents", ["celery_task_id"])
    op.create_index("ix_documents_created_at",     "documents", ["created_at"])
    op.create_index("ix_documents_document_type",  "documents", ["document_type"])
    op.create_index("ix_documents_sync_status",    "documents", ["sync_status"])

    # ── Table: extracted_data ─────────────────────────────────────────────────
    op.create_table(
        "extracted_data",
        sa.Column("id",               UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("document_id",      UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("confidence_score", sa.Float(),         nullable=True),
        sa.Column("supplier_name",    sa.String(500),     nullable=True),
        sa.Column("supplier_inn",     sa.String(12),      nullable=True),
        sa.Column("supplier_kpp",     sa.String(9),       nullable=True),
        sa.Column("buyer_name",       sa.String(500),     nullable=True),
        sa.Column("buyer_inn",        sa.String(12),      nullable=True),
        sa.Column("buyer_kpp",        sa.String(9),       nullable=True),
        sa.Column("document_number",  sa.String(100),     nullable=True),
        sa.Column("document_date",    sa.String(20),      nullable=True),
        sa.Column("total_amount",     sa.Float(),         nullable=True),
        sa.Column("vat_amount",       sa.Float(),         nullable=True),
        sa.Column("currency",         sa.String(10),      server_default="RUB"),
        sa.Column("line_items",       JSONB(),            nullable=True),
        sa.Column("raw_fields",       JSONB(),            nullable=True),
        sa.Column("raw_ocr_text",     sa.Text(),          nullable=True),
        sa.Column("created_at",       sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("ix_extracted_data_supplier_inn", "extracted_data", ["supplier_inn"])
    op.create_index("ix_extracted_data_document_id",  "extracted_data", ["document_id"])

    # ── Table: processing_logs ────────────────────────────────────────────────
    op.create_table(
        "processing_logs",
        sa.Column("id",          UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage",       sa.String(50),  nullable=False),
        sa.Column("status",      sa.String(20),  nullable=False),
        sa.Column("message",     sa.Text(),      nullable=True),
        sa.Column("duration_ms", sa.Integer(),   nullable=True),
        sa.Column("created_at",  sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("ix_processing_logs_document_id", "processing_logs", ["document_id"])
    op.create_index("ix_processing_logs_stage",       "processing_logs", ["stage"])


def downgrade() -> None:
    op.drop_table("processing_logs")
    op.drop_table("extracted_data")
    op.drop_table("documents")
    op.execute("DROP TYPE IF EXISTS sync_status_enum")
    op.execute("DROP TYPE IF EXISTS processing_status_enum")
    op.execute("DROP TYPE IF EXISTS document_type_enum")
    op.execute("DROP TYPE IF EXISTS source_type_enum")
