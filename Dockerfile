# ============================================================
# AIB OCR Subsystem — Dockerfile (Multi-stage)
# ============================================================

# ── Stage 1: Base Python ─────────────────────────────────
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System dependencies for OpenCV and PaddleOCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgl1 \
    poppler-utils \
    ghostscript \
    curl \
    wget \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Stage 2: Dependencies ────────────────────────────────
FROM base AS dependencies

COPY requirements.txt .

# الإصلاح الجديد: زيادة وقت الإنترنت إلى 1000، وإلغاء تثبيت مكتبات الشاشات المزعجة فقط
RUN pip install --upgrade pip && \
    pip install --default-timeout=1000 -r requirements.txt && \
    pip uninstall -y opencv-python opencv-contrib-python

# ── Stage 3: Production ──────────────────────────────────
FROM dependencies AS production

# Create non-root user
RUN groupadd -r aibuser && useradd -r -g aibuser aibuser

# Create directories
RUN mkdir -p /app/storage/uploads \
             /app/storage/processed \
             /app/logs \
             /app/scanner_inbox && \
    chown -R aibuser:aibuser /app

COPY --chown=aibuser:aibuser . .

USER aibuser

EXPOSE 8000

# Entrypoint based on SERVICE_TYPE env var
COPY --chown=aibuser:aibuser scripts/entrypoint.sh /entrypoint.sh
# Change user temporarily to root to change permissions, then back
USER root
RUN chmod +x /entrypoint.sh
USER aibuser

ENTRYPOINT ["/entrypoint.sh"]
CMD ["api"]