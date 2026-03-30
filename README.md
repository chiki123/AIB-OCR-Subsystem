# AIB OCR Subsystem — Intelligent Document Processing
# Подсистема интеллектуального распознавания первичных документов

**Версия:** 1.0.0  
**Клиент:** ООО «АИБ» (Екатеринбург)  
**Архитектор:** Рашид Чеки

---

## Архитектура системы

```
┌─────────────────────────────────────────────────────────────────────┐
│                        INPUT LAYER                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ File Upload  │  │ Hot Folder   │  │    Mobile    │              │
│  │  Adapter     │  │   Watcher    │  │   Adapter    │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
└─────────┼─────────────────┼─────────────────┼────────────────────-─┘
          │                 │                 │
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     NGINX (Reverse Proxy)                            │
│              Rate Limiting / SSL / Load Balancing                    │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    FastAPI Application                               │
│  POST /api/v1/documents/upload  →  returns task_id immediately       │
│  GET  /api/v1/tasks/{id}/status →  poll task status                 │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Redis Message Broker                              │
│                  Task Queue + Result Backend                         │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   Celery Workers                                     │
│                                                                      │
│   ┌──────────────────────────────────────────────────────────────┐  │
│   │                 CORE AI ENGINE PIPELINE                       │  │
│   │                                                               │  │
│   │  1. DocumentClassifier  (Счет-фактура / УПД / ТОРГ-12)       │  │
│   │  2. ImagePreprocessor   (OpenCV: deskew, denoise, binarize)  │  │
│   │  3. RegionDetector      (PP-StructureV3: tables detection)   │  │
│   │  4. OCREngine           (PaddleOCR 3.x: PP-OCRv5)           │  │
│   │  5. EntityExtractor     (Regex + Templates per doc type)     │  │
│   │  6. DataValidator       (ИНН/КПП/date/amount validation)     │  │
│   │  7. JSONSerializer      (structured output)                  │  │
│   └───────────────────────────────┬──────────────────────────────┘  │
└───────────────────────────────────┼─────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
             ┌─────────┐    ┌─────────────┐  ┌──────────┐
             │PostgreSQL│    │ 1С HTTP     │  │  File    │
             │  (meta) │    │  Service    │  │ Storage  │
             └─────────┘    └─────────────┘  └──────────┘
```

## Быстрый старт

```bash
# 1. Клонируем / распаковываем проект
cd aib_ocr

# 2. Копируем env файл
cp .env.example .env
# Редактируем .env под вашу конфигурацию

# 3. Запускаем все сервисы
docker-compose up -d

# 4. Применяем миграции БД
docker-compose exec api alembic upgrade head

# 5. Проверяем статус
curl http://localhost/api/v1/health
```

## Структура проекта

```
aib_ocr/
├── app/
│   ├── api/v1/endpoints/     # FastAPI роутеры
│   ├── core/                 # Конфиг, безопасность, логирование
│   ├── db/                   # SQLAlchemy + Alembic
│   ├── models/               # DB модели
│   ├── schemas/              # Pydantic схемы
│   ├── services/             # Core AI Engine
│   │   ├── classifier.py     # Классификатор документов
│   │   ├── preprocessor.py   # OpenCV предобработка
│   │   ├── ocr_engine.py     # PaddleOCR обертка
│   │   ├── extractor.py      # Извлечение сущностей
│   │   ├── validator.py      # Валидация данных
│   │   └── integrator_1c.py  # Интеграция с 1С
│   ├── workers/              # Celery задачи
│   └── utils/                # Утилиты
├── tests/                    # pytest тесты
├── nginx/                    # Nginx конфигурация
├── scripts/                  # Вспомогательные скрипты
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

## API Endpoints

| Метод | URL | Описание |
|-------|-----|----------|
| `GET` | `/api/v1/health` | Проверка состояния системы |
| `POST` | `/api/v1/documents/upload` | Загрузка документа |
| `GET` | `/api/v1/tasks/{task_id}/status` | Статус обработки |
| `GET` | `/api/v1/documents/{doc_id}` | Результат обработки |
| `POST` | `/api/v1/documents/{doc_id}/send-to-1c` | Отправка в 1С вручную |
| `GET` | `/api/v1/documents/` | Список документов |

## Поддерживаемые документы (MVP)

- **Счет-фактура** — НДС документ, обязателен для вычета
- **УПД** — Универсальный передаточный документ  
- **ТОРГ-12** — Товарная накладная

## Требования к серверу

- **CPU:** 4+ ядра (OCR интенсивно использует CPU)
- **RAM:** 8+ GB (PaddleOCR ~500MB/worker)
- **Disk:** 50+ GB (хранение файлов)
- **OS:** Ubuntu 22.04 LTS
