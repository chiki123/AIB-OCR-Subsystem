"""
AIB OCR Subsystem — Core Configuration
Центральная конфигурация приложения через Pydantic Settings
"""
import os
from functools import lru_cache
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


# Корень проекта (папка где лежит этот файл ../../)
PROJECT_ROOT = Path(__file__).parent.parent.parent


class Settings(BaseSettings):
    """Все настройки из .env файла"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────
    APP_ENV: str = "development"
    APP_SECRET_KEY: str = "local-dev-secret"
    APP_DEBUG: bool = True
    APP_TITLE: str = "AIB OCR Subsystem"
    APP_VERSION: str = "1.0.0"

    # ── Server ───────────────────────────────────────────
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000
    API_WORKERS: int = 1

    # ── Database ─────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://aib_user:localdevpass123@localhost:5432/aib_ocr"
    DATABASE_URL_SYNC: str = "postgresql://aib_user:localdevpass123@localhost:5432/aib_ocr"
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # ── Redis ────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Celery ───────────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    CELERY_TASK_SOFT_TIME_LIMIT: int = 60
    CELERY_TASK_TIME_LIMIT: int = 120
    CELERY_MAX_RETRIES: int = 3
    CELERY_RETRY_BACKOFF: int = 10

    # ── File Storage ─────────────────────────────────────
    # Используем относительные пути — работают на любой ОС
    UPLOAD_DIR: str = "./storage/uploads"
    PROCESSED_DIR: str = "./storage/processed"
    SCANNER_INBOX_DIR: str = "./scanner_inbox"
    MAX_UPLOAD_SIZE_MB: int = 50
    ALLOWED_EXTENSIONS: str = "pdf,jpg,jpeg,png,tiff,tif,bmp"

    @property
    def allowed_extensions_list(self) -> List[str]:
        return [e.lower().strip() for e in self.ALLOWED_EXTENSIONS.split(",")]

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def upload_dir_abs(self) -> Path:
        """Абсолютный путь к папке загрузок"""
        p = Path(self.UPLOAD_DIR)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def processed_dir_abs(self) -> Path:
        p = Path(self.PROCESSED_DIR)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def scanner_inbox_abs(self) -> Path:
        p = Path(self.SCANNER_INBOX_DIR)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def log_file_abs(self) -> str:
        p = Path(self.LOG_FILE)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return str(p)

    # ── PaddleOCR ────────────────────────────────────────
    PADDLE_USE_GPU: bool = False
    PADDLE_CPU_THREADS: int = 2
    PADDLE_LANG: str = "ru"
    PADDLE_USE_ANGLE_CLS: bool = True
    PADDLE_SHOW_LOG: bool = False

    # ── 1С Integration ───────────────────────────────────
    C1_BASE_URL: str = "http://localhost:8080/accounting/hs/docai"
    C1_USERNAME: str = "docai_service"
    C1_PASSWORD: str = "changeme"
    C1_TIMEOUT_SECONDS: int = 5
    C1_MAX_RETRIES: int = 1
    C1_CIRCUIT_BREAKER_THRESHOLD: int = 3
    C1_CIRCUIT_BREAKER_TIMEOUT: int = 30

    # ── Security ─────────────────────────────────────────
    JWT_SECRET_KEY: str = "local-dev-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    ALLOWED_HOSTS: str = "localhost,127.0.0.1,0.0.0.0"

    @property
    def allowed_hosts_list(self) -> List[str]:
        return [h.strip() for h in self.ALLOWED_HOSTS.split(",")]

    # ── Logging ──────────────────────────────────────────
    LOG_LEVEL: str = "DEBUG"
    LOG_FORMAT: str = "text"
    LOG_FILE: str = "./logs/aib_ocr.log"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()