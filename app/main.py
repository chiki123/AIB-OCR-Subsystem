"""
AIB OCR Subsystem — FastAPI Application
Точка входа приложения
"""
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.core.config import settings
from app.utils.logging import setup_logging
from app.db.base import create_tables
from app.api.v1.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info(f"Запуск {settings.APP_TITLE} v{settings.APP_VERSION} [{settings.APP_ENV}]")
    await create_tables()
    logger.success("База данных готова")
    yield
    logger.info("Завершение работы приложения")


app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    description="""
## AIB OCR Subsystem

Подсистема распознавания первичных бухгалтерских документов.

### Поддерживаемые документы (MVP)
- `invoice` — Счет-фактура
- `upd`     — Универсальный передаточный документ
- `torg12`  — Товарная накладная ТОРГ-12
    """,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"])

app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])


@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    t = time.time()
    response = await call_next(request)
    response.headers["X-Process-Time-Ms"] = f"{(time.time()-t)*1000:.1f}"
    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    response = await call_next(request)
    level = "warning" if response.status_code >= 400 else "debug"
    getattr(logger, level)(f"{request.method} {request.url.path} → {response.status_code}")
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Необработанная ошибка [{request.url.path}]: {exc}", exc_info=True)
    return JSONResponse(status_code=500,
        content={"detail": "Внутренняя ошибка. Обратитесь к администратору."})


app.include_router(api_router, prefix="/api/v1")

# Веб-интерфейс (статичные файлы)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
