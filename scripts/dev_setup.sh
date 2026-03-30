#!/bin/bash
# ============================================================
# AIB OCR Subsystem — Local Development Setup
# Быстрый старт без Docker (для разработки и отладки)
# ============================================================
set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}▶${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC}  $1"; }

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

log "Настройка окружения разработчика AIB OCR"

# ── Python venv ───────────────────────────────────────────
if [ ! -d ".venv" ]; then
  log "Создание виртуального окружения Python..."
  python3 -m venv .venv
fi
source .venv/bin/activate
log "✓ Виртуальное окружение активировано"

# ── Зависимости ───────────────────────────────────────────
log "Установка зависимостей..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
log "✓ Зависимости установлены"

# ── .env ──────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  warn ".env не найден — используем пример для разработки"
  cp .env.example .env
  # Перезаписываем URL на локальные
  sed -i 's|postgresql+asyncpg://.*|postgresql+asyncpg://aib_user:devpass@localhost:5432/aib_ocr|' .env
  sed -i 's|DATABASE_URL_SYNC=.*|DATABASE_URL_SYNC=postgresql://aib_user:devpass@localhost:5432/aib_ocr|' .env
  sed -i 's|REDIS_URL=.*|REDIS_URL=redis://localhost:6379/0|' .env
  sed -i 's|APP_ENV=.*|APP_ENV=development|' .env
  sed -i 's|APP_DEBUG=.*|APP_DEBUG=true|' .env
fi

# ── Директории ────────────────────────────────────────────
mkdir -p storage/uploads storage/processed scanner_inbox logs

# ── Инфраструктура через Docker (только Postgres + Redis) ─
log "Запуск PostgreSQL и Redis через Docker..."
docker-compose up -d postgres redis
sleep 3
log "✓ PostgreSQL и Redis запущены"

# ── Миграции ──────────────────────────────────────────────
log "Применение миграций..."
alembic upgrade head
log "✓ База данных готова"

# ── Вывод команд для запуска ──────────────────────────────
echo ""
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ Окружение готово!${NC}"
echo ""
echo "Запустите в отдельных терминалах:"
echo ""
echo "  # Терминал 1 — FastAPI:"
echo "  source .venv/bin/activate"
echo "  uvicorn app.main:app --reload --port 8000"
echo ""
echo "  # Терминал 2 — Celery Worker:"
echo "  source .venv/bin/activate"
echo "  celery -A app.workers.celery_app worker --loglevel=info --concurrency=1"
echo ""
echo "  # Терминал 3 — Hot Folder Watcher:"
echo "  source .venv/bin/activate"
echo "  python -m app.services.hot_folder_watcher"
echo ""
echo "  # Тесты:"
echo "  pytest tests/ -v"
echo ""
echo -e "  🌐 Веб-интерфейс: http://localhost:8000"
echo -e "  📖 API Docs:      http://localhost:8000/api/docs"
echo -e "${GREEN}════════════════════════════════════════${NC}"
