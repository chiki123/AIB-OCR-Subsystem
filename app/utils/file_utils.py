"""
AIB OCR Subsystem — File Utilities
Вспомогательные функции для работы с файлами и хранилищем
"""
import hashlib
import mimetypes
import struct
from pathlib import Path
from typing import Optional

from loguru import logger


# ── Magic bytes для определения типа файла ───────────────────────────────────
# Проверяем реальный тип файла, а не только расширение (безопасность!)
MAGIC_SIGNATURES = {
    b"\x25\x50\x44\x46": "application/pdf",           # PDF  (%PDF)
    b"\xff\xd8\xff":      "image/jpeg",                # JPEG
    b"\x89\x50\x4e\x47": "image/png",                 # PNG  (.PNG)
    b"\x49\x49\x2a\x00": "image/tiff",                # TIFF (little-endian)
    b"\x4d\x4d\x00\x2a": "image/tiff",                # TIFF (big-endian)
    b"\x42\x4d":          "image/bmp",                 # BMP  (BM)
}

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/bmp",
    "image/webp",
}


def detect_mime_type(file_bytes: bytes) -> Optional[str]:
    """
    Определяет MIME-тип файла по его заголовку (magic bytes).
    Не доверяет расширению или Content-Type от клиента.
    
    Это важно для безопасности: злоумышленник может переименовать
    вредоносный файл в .pdf и загрузить его.
    """
    header = file_bytes[:8]

    for signature, mime_type in MAGIC_SIGNATURES.items():
        if header.startswith(signature):
            return mime_type

    return None


def is_valid_file_type(file_bytes: bytes) -> bool:
    """Проверяет, что файл имеет допустимый тип"""
    mime = detect_mime_type(file_bytes)
    return mime in ALLOWED_MIME_TYPES


def compute_file_hash(file_bytes: bytes) -> str:
    """Вычисляет SHA-256 хеш файла для дедупликации"""
    return hashlib.sha256(file_bytes).hexdigest()


def get_file_extension_from_mime(mime_type: str) -> str:
    """Возвращает расширение файла по MIME-типу"""
    extension_map = {
        "application/pdf": ".pdf",
        "image/jpeg":      ".jpg",
        "image/png":       ".png",
        "image/tiff":      ".tiff",
        "image/bmp":       ".bmp",
        "image/webp":      ".webp",
    }
    return extension_map.get(mime_type, ".bin")


def sanitize_filename(filename: str) -> str:
    """
    Очищает имя файла от опасных символов.
    Предотвращает Path Traversal атаки.
    """
    # Берём только имя файла без пути
    safe_name = Path(filename).name

    # Заменяем опасные символы
    dangerous_chars = ['/', '\\', '..', '\x00', '<', '>', ':', '"', '|', '?', '*']
    for char in dangerous_chars:
        safe_name = safe_name.replace(char, '_')

    # Ограничиваем длину
    if len(safe_name) > 255:
        stem = Path(safe_name).stem[:200]
        suffix = Path(safe_name).suffix
        safe_name = stem + suffix

    return safe_name or "unnamed_document"


def ensure_storage_dirs(*dirs: str) -> None:
    """Создаёт директории хранилища если не существуют"""
    for dir_path in dirs:
        path = Path(dir_path)
        path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Директория готова: {path}")


def cleanup_temp_files(directory: str, max_age_hours: int = 24) -> int:
    """
    Удаляет временные файлы старше max_age_hours часов.
    Возвращает количество удалённых файлов.
    """
    import time
    directory_path = Path(directory)
    if not directory_path.exists():
        return 0

    deleted = 0
    max_age_seconds = max_age_hours * 3600
    now = time.time()

    for file_path in directory_path.rglob("*"):
        if file_path.is_file():
            file_age = now - file_path.stat().st_mtime
            if file_age > max_age_seconds:
                try:
                    file_path.unlink()
                    deleted += 1
                except Exception as e:
                    logger.warning(f"Не удалось удалить {file_path}: {e}")

    if deleted:
        logger.info(f"cleanup_temp_files: удалено {deleted} файлов из {directory}")

    return deleted


def human_readable_size(size_bytes: int) -> str:
    """Возвращает размер файла в читаемом формате"""
    for unit in ["Б", "КБ", "МБ", "ГБ"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} ТБ"
