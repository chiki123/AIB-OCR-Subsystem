"""
AIB OCR Subsystem — Enums / Перечисления
"""
from enum import Enum


class DocumentType(str, Enum):
    """Поддерживаемые типы документов (MVP)"""
    INVOICE = "invoice"          # Счет-фактура
    UPD = "upd"                  # Универсальный передаточный документ
    TORG12 = "torg12"            # Товарная накладная ТОРГ-12
    UNKNOWN = "unknown"          # Не удалось классифицировать


class SourceType(str, Enum):
    """Каналы ввода документов"""
    FILE_UPLOAD = "file_upload"    # Прямая загрузка файла через API
    HOT_FOLDER = "hot_folder"      # Горячая папка сканера
    IMAGE_UPLOAD = "image_upload"  # Загрузка изображения
    MOBILE = "mobile"              # Мобильное приложение


class ProcessingStatus(str, Enum):
    """Статусы обработки документа"""
    PENDING = "pending"          # Принято, ожидает обработки
    PROCESSING = "processing"    # Обрабатывается
    SUCCESS = "success"          # Успешно обработано
    FAILED = "failed"            # Ошибка обработки
    RETRY = "retry"              # Повторная попытка


class SyncStatus(str, Enum):
    """Статусы синхронизации с 1С"""
    PENDING = "pending"          # Ожидает отправки
    SENT = "sent"                # Успешно отправлено в 1С
    FAILED = "failed"            # Ошибка отправки
    SKIPPED = "skipped"          # Пропущено (низкая уверенность)


class PipelineStage(str, Enum):
    """Этапы пайплайна обработки"""
    CLASSIFIER = "classifier"
    PREPROCESSOR = "preprocessor"
    OCR = "ocr"
    EXTRACTOR = "extractor"
    VALIDATOR = "validator"
    INTEGRATOR = "integrator"
