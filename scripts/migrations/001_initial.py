"""Initial database schema

Revision ID: 001_initial
Revises: 
Create Date: 2026-03-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ── ENUM types ───────────────────────────────────────────────────────
    op.execute("""
        CREATE TYPE source_type_enum AS ENUM 
        ('file_upload', 'hot_folder', 'image_upload', 'mobile')
    """)
    op.execute("""
        CREATE TYPE document_type_enum AS ENUM 
        ('invoice', 'upd', 'torg12', 'unknown')
    """)
    op.execute("""
        CREATE TYPE processing_status_enum AS ENUM 
        ('pending', 'processing', 'success', 'failed', 'retry')
    """)
    op.execute("""
        CREATE TYPE sync_status_enum AS ENUM 
        ('pending', 'sent', 'failed', 'skipped')
    """)

    # ── documents ────────────────────────────────────────────────────────
    op.create_table(
        'documents',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('source_type', sa.Enum(name='source_type_enum'), nullable=False),
        sa.Column('document_type', sa.Enum(name='document_type_enum'), nullable=True),
        sa.Column('original_filename', sa.String(500), nullable=False),
        sa.Column('file_path', sa.Text, nullable=False),
        sa.Column('file_size_bytes', sa.Integer, nullable=False),
        sa.Column('mime_type', sa.String(100), nullable=False),
        sa.Column('status', sa.Enum(name='processing_status_enum'), nullable=False, server_default='pending'),
        sa.Column('sync_status', sa.Enum(name='sync_status_enum'), nullable=False, server_default='pending'),
        sa.Column('celery_task_id', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_documents_status', 'documents', ['status'])
    op.create_index('ix_documents_celery_task_id', 'documents', ['celery_task_id'])
    op.create_index('ix_documents_created_at', 'documents', ['created_at'])

    # ── extracted_data ───────────────────────────────────────────────────
    op.create_table(
        'extracted_data',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('document_id', UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('confidence_score', sa.Float, nullable=True),
        sa.Column('supplier_name', sa.String(500), nullable=True),
        sa.Column('supplier_inn', sa.String(12), nullable=True),
        sa.Column('supplier_kpp', sa.String(9), nullable=True),
        sa.Column('buyer_name', sa.String(500), nullable=True),
        sa.Column('buyer_inn', sa.String(12), nullable=True),
        sa.Column('buyer_kpp', sa.String(9), nullable=True),
        sa.Column('document_number', sa.String(100), nullable=True),
        sa.Column('document_date', sa.String(20), nullable=True),
        sa.Column('total_amount', sa.Float, nullable=True),
        sa.Column('vat_amount', sa.Float, nullable=True),
        sa.Column('currency', sa.String(10), server_default='RUB'),
        sa.Column('line_items', JSONB, nullable=True),
        sa.Column('raw_fields', JSONB, nullable=True),
        sa.Column('raw_ocr_text', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── processing_logs ──────────────────────────────────────────────────
    op.create_table(
        'processing_logs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('document_id', UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('stage', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('message', sa.Text, nullable=True),
        sa.Column('duration_ms', sa.Integer, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_processing_logs_document_id', 'processing_logs', ['document_id'])


def downgrade() -> None:
    op.drop_table('processing_logs')
    op.drop_table('extracted_data')
    op.drop_table('documents')
    op.execute("DROP TYPE IF EXISTS sync_status_enum")
    op.execute("DROP TYPE IF EXISTS processing_status_enum")
    op.execute("DROP TYPE IF EXISTS document_type_enum")
    op.execute("DROP TYPE IF EXISTS source_type_enum")
