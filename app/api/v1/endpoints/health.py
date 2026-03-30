"""
AIB OCR Subsystem — Health Check Endpoint
GET /health — проверка состояния всех сервисов системы
"""
import time
from datetime import datetime

import redis.asyncio as aioredis
from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.db.base import async_engine
from app.schemas.document import HealthResponse, ServiceStatus

router = APIRouter()


@router.get(
    "",
    response_model=HealthResponse,
    summary="Состояние системы",
    description="Проверяет доступность PostgreSQL, Redis, PaddleOCR и 1С",
)
async def health_check():
    """Детальная проверка всех компонентов системы"""
    services = []
    overall_healthy = True

    # ── PostgreSQL ───────────────────────────────────────────────────────
    try:
        t = time.time()
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        latency = (time.time() - t) * 1000
        services.append(ServiceStatus(
            name="postgresql",
            status="healthy",
            latency_ms=round(latency, 1),
        ))
    except Exception as e:
        services.append(ServiceStatus(name="postgresql", status="unhealthy", details=str(e)))
        overall_healthy = False

    # ── Redis ────────────────────────────────────────────────────────────
    try:
        t = time.time()
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.aclose()
        latency = (time.time() - t) * 1000
        services.append(ServiceStatus(
            name="redis",
            status="healthy",
            latency_ms=round(latency, 1),
        ))
    except Exception as e:
        services.append(ServiceStatus(name="redis", status="unhealthy", details=str(e)))
        overall_healthy = False

    # ── Celery Workers ───────────────────────────────────────────────────
    try:
        from app.workers.celery_app import celery_app
        inspect = celery_app.control.inspect(timeout=2.0)
        active_workers = inspect.ping()
        worker_count = len(active_workers) if active_workers else 0
        services.append(ServiceStatus(
            name="celery_workers",
            status="healthy" if worker_count > 0 else "degraded",
            details=f"Активных воркеров: {worker_count}",
        ))
        if worker_count == 0:
            overall_healthy = False
    except Exception as e:
        services.append(ServiceStatus(name="celery_workers", status="unhealthy", details=str(e)))
        overall_healthy = False

    # ── PaddleOCR ────────────────────────────────────────────────────────
    try:
        from app.services.ocr_engine import _ocr_instance
        ocr_status = "healthy" if _ocr_instance is not None else "not_initialized"
        services.append(ServiceStatus(
            name="paddleocr",
            status=ocr_status,
            details="Модель загружена" if _ocr_instance else "Инициализируется при первом запросе",
        ))
    except Exception as e:
        services.append(ServiceStatus(name="paddleocr", status="unknown", details=str(e)))

    # ── 1С Integration ───────────────────────────────────────────────────
    try:
        from app.services.integrator_1c import Integrator1C
        integrator = Integrator1C()
        c1_status = integrator.health_check()
        services.append(ServiceStatus(
            name="1c_integration",
            status="healthy" if c1_status.get("available") else "unhealthy",
            latency_ms=c1_status.get("latency_ms"),
            details=f"Circuit: {c1_status.get('circuit_state', 'unknown')}",
        ))
    except Exception as e:
        services.append(ServiceStatus(name="1c_integration", status="unknown", details=str(e)))

    # Итоговый статус
    statuses = {s.status for s in services}
    if "unhealthy" in statuses:
        overall_status = "unhealthy"
    elif "degraded" in statuses:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    return HealthResponse(
        status=overall_status,
        version=settings.APP_VERSION,
        services=services,
        timestamp=datetime.utcnow(),
    )
