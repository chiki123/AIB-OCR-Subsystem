"""
AIB OCR Subsystem — Hot Folder Watcher
Наблюдатель за горячей папкой сканера

Мониторит директорию scanner_inbox/ и автоматически
ставит в очередь все появившиеся файлы.

Используется: watchdog (inotify на Linux)
Запуск: python -m app.services.hot_folder_watcher
        или через Docker Compose сервис 'watcher'

Поток:
  scanner_inbox/doc.pdf → обнаружен →
  сохранён в storage/ → задача в Redis →
  Celery Worker → Core AI Engine
"""
import time
import uuid
import shutil
from pathlib import Path
from datetime import datetime

import httpx
from loguru import logger
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

from app.core.config import settings


class DocumentFileHandler(FileSystemEventHandler):
    """
    Обработчик событий файловой системы.
    Вызывается watchdog при появлении нового файла.
    """

    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.processing: set = set()  # Файлы в процессе обработки

    def on_created(self, event: FileCreatedEvent):
        """Новый файл появился в папке"""
        if event.is_directory:
            return

        file_path = Path(event.src_path)

        # Проверяем расширение
        ext = file_path.suffix.lower().lstrip(".")
        if ext not in settings.allowed_extensions_list:
            logger.debug(f"Пропускаем файл с неподдерживаемым расширением: {file_path.name}")
            return

        # Пропускаем временные файлы (в процессе записи)
        if file_path.name.startswith(".") or file_path.name.endswith(".tmp"):
            return

        # Дедупликация
        if str(file_path) in self.processing:
            return

        self.processing.add(str(file_path))

        # Небольшая задержка: ждём окончания записи файла сканером
        time.sleep(1.5)

        try:
            self._process_file(file_path)
        except Exception as e:
            logger.error(f"Ошибка обработки файла {file_path.name}: {e}")
        finally:
            self.processing.discard(str(file_path))

    def _process_file(self, file_path: Path):
        """Отправляет файл в API для обработки"""
        if not file_path.exists():
            logger.warning(f"Файл исчез до обработки: {file_path}")
            return

        file_size = file_path.stat().st_size
        if file_size == 0:
            logger.warning(f"Пустой файл: {file_path.name}")
            return

        logger.info(f"Новый файл в Hot Folder: {file_path.name} ({file_size // 1024} КБ)")

        # Отправляем в API
        try:
            with open(file_path, "rb") as f:
                response = httpx.post(
                    f"{self.api_url}/api/v1/documents/upload",
                    files={"file": (file_path.name, f, _get_mime(file_path))},
                    timeout=30,
                    params={"source_type": "hot_folder"},
                )

            if response.status_code in (200, 202):
                data = response.json()
                logger.success(
                    f"Hot Folder: {file_path.name} → task_id={data.get('task_id')}, "
                    f"document_id={data.get('document_id')}"
                )

                # Перемещаем файл в processed/
                processed_dir = Path(settings.PROCESSED_DIR) / "from_scanner" / datetime.now().strftime("%Y-%m")
                processed_dir.mkdir(parents=True, exist_ok=True)
                new_path = processed_dir / file_path.name

                # Если файл с таким именем уже есть — добавляем timestamp
                if new_path.exists():
                    stem = file_path.stem
                    suffix = file_path.suffix
                    new_path = processed_dir / f"{stem}_{int(time.time())}{suffix}"

                shutil.move(str(file_path), str(new_path))
                logger.debug(f"Файл перемещён в: {new_path}")

            else:
                logger.error(
                    f"API вернул ошибку для {file_path.name}: "
                    f"{response.status_code} {response.text[:200]}"
                )

        except httpx.ConnectError:
            logger.error(f"API недоступен! Файл {file_path.name} не обработан.")
        except Exception as e:
            logger.error(f"Ошибка отправки файла {file_path.name}: {e}")


def _get_mime(file_path: Path) -> str:
    """Определяет MIME тип по расширению"""
    mime_map = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".bmp": "image/bmp",
    }
    return mime_map.get(file_path.suffix.lower(), "application/octet-stream")


class HotFolderWatcher:
    """
    Запускает наблюдатель за директорией.
    
    Использует watchdog на базе inotify (Linux) — 
    мгновенное обнаружение без polling.
    """

    def __init__(
        self,
        watch_dir: str = None,
        api_url: str = "http://api:8000",
    ):
        self.watch_dir = Path(watch_dir or settings.SCANNER_INBOX_DIR)
        self.api_url = api_url
        self.observer = Observer()

    def start(self):
        """Запускает наблюдение"""
        # Создаём директорию если не существует
        self.watch_dir.mkdir(parents=True, exist_ok=True)

        handler = DocumentFileHandler(api_url=self.api_url)

        self.observer.schedule(
            handler,
            str(self.watch_dir),
            recursive=False,  # Только корневая папка, без подпапок
        )

        self.observer.start()
        logger.success(
            f"Hot Folder Watcher запущен. "
            f"Мониторинг: {self.watch_dir} "
            f"API: {self.api_url}"
        )

        try:
            while True:
                time.sleep(5)
                if not self.observer.is_alive():
                    logger.error("Observer упал, перезапускаем...")
                    self.observer.start()
        except KeyboardInterrupt:
            logger.info("Остановка Hot Folder Watcher...")
            self.observer.stop()

        self.observer.join()
        logger.info("Hot Folder Watcher остановлен")


if __name__ == "__main__":
    import sys
    from loguru import logger as log

    log.remove()
    log.add(sys.stdout, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")
    log.add(settings.LOG_FILE, rotation="50 MB", level="DEBUG")

    watcher = HotFolderWatcher(
        api_url="http://api:8000",
    )
    watcher.start()
