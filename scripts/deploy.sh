#!/bin/bash
# ============================================================
# AIB OCR Subsystem — Production Deployment Script
# ООО «АИБ» · On-Premise Server
# ============================================================
# Запуск: sudo bash scripts/deploy.sh

set -euo pipefail

# ── Цвета ─────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'; BOLD='\033[1m'

log()     { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
section() { echo -e "\n${BLUE}${BOLD}══ $1 ══${NC}\n"; }

# ── Конфигурация ──────────────────────────────────────────
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
ENV_FILE="$PROJECT_DIR/.env"

section "AIB OCR — Deployment начат"
log "Проект: $PROJECT_DIR"
log "Дата: $(date)"

# ── Шаг 1: Проверка системы ───────────────────────────────
section "1. Проверка зависимостей"

check_command() {
  if ! command -v "$1" &>/dev/null; then
    error "$1 не установлен. Установите: $2"
  fi
  log "✓ $1 доступен"
}

check_command docker   "https://docs.docker.com/get-docker/"
check_command docker-compose "https://docs.docker.com/compose/install/"

# Проверяем .env файл
if [ ! -f "$ENV_FILE" ]; then
  warn ".env не найден — копируем из .env.example"
  cp "$PROJECT_DIR/.env.example" "$ENV_FILE"
  error "Заполните .env файл перед деплоем! Особенно: POSTGRES_PASSWORD, APP_SECRET_KEY, JWT_SECRET_KEY"
fi

log "✓ .env файл найден"

# ── Шаг 2: Проверка безопасности .env ────────────────────
section "2. Проверка конфигурации"

check_env_not_default() {
  local key="$1"; local dangerous_value="$2"
  local value
  value=$(grep "^${key}=" "$ENV_FILE" | cut -d'=' -f2-)
  if [ "$value" = "$dangerous_value" ] || [ -z "$value" ]; then
    error "Измените ${key} в .env! Текущее значение небезопасно."
  fi
  log "✓ ${key} настроен"
}

check_env_not_default "POSTGRES_PASSWORD" "CHANGE_ME_STRONG_PASSWORD"
check_env_not_default "APP_SECRET_KEY"    "CHANGE_ME_USE_RANDOM_64_CHARS"
check_env_not_default "JWT_SECRET_KEY"    "CHANGE_ME_JWT_SECRET_64_CHARS"

# ── Шаг 3: SSL сертификаты ────────────────────────────────
section "3. SSL Сертификаты"

SSL_DIR="$PROJECT_DIR/nginx/ssl"
mkdir -p "$SSL_DIR"

if [ ! -f "$SSL_DIR/aib_ocr.crt" ]; then
  warn "SSL сертификат не найден — генерируем самоподписанный (On-Premise)"
  openssl req -x509 -nodes -days 3650 \
    -newkey rsa:4096 \
    -keyout "$SSL_DIR/aib_ocr.key" \
    -out    "$SSL_DIR/aib_ocr.crt" \
    -subj "/C=RU/ST=Sverdlovsk/L=Yekaterinburg/O=AIB/CN=aib-ocr.local" \
    2>/dev/null
  log "✓ SSL сертификат сгенерирован (самоподписанный, 10 лет)"
else
  log "✓ SSL сертификат найден"
fi

# ── Шаг 4: Создание директорий ────────────────────────────
section "4. Подготовка файловой системы"

dirs=(
  "$PROJECT_DIR/storage/uploads"
  "$PROJECT_DIR/storage/processed"
  "$PROJECT_DIR/scanner_inbox"
  "$PROJECT_DIR/logs"
)
for dir in "${dirs[@]}"; do
  mkdir -p "$dir"
  log "✓ Директория: $dir"
done

# ── Шаг 5: Сборка Docker образов ─────────────────────────
section "5. Сборка Docker образов"

cd "$PROJECT_DIR"
log "Сборка образа (может занять 5-10 минут при первом запуске)..."
docker-compose -f "$COMPOSE_FILE" build --no-cache
log "✓ Образы собраны"

# ── Шаг 6: Запуск инфраструктуры ─────────────────────────
section "6. Запуск сервисов"

log "Запуск PostgreSQL и Redis..."
docker-compose -f "$COMPOSE_FILE" up -d postgres redis

log "Ожидание готовности PostgreSQL (до 60 сек)..."
for i in $(seq 1 30); do
  if docker-compose -f "$COMPOSE_FILE" exec -T postgres \
      pg_isready -U "$(grep POSTGRES_USER "$ENV_FILE" | cut -d= -f2)" &>/dev/null; then
    log "✓ PostgreSQL готов"
    break
  fi
  sleep 2
  if [ $i -eq 30 ]; then error "PostgreSQL не запустился"; fi
done

log "Применение миграций базы данных..."
docker-compose -f "$COMPOSE_FILE" run --rm api python -m alembic upgrade head
log "✓ Миграции применены"

log "Запуск всех сервисов..."
docker-compose -f "$COMPOSE_FILE" up -d
log "✓ Все сервисы запущены"

# ── Шаг 7: Проверка здоровья ─────────────────────────────
section "7. Проверка работоспособности"

log "Ожидание готовности API (до 60 сек)..."
for i in $(seq 1 30); do
  if curl -sf http://localhost/api/v1/health &>/dev/null; then
    log "✓ API отвечает"
    break
  fi
  sleep 2
  if [ $i -eq 30 ]; then
    warn "API не ответил за 60 секунд. Проверьте логи: docker-compose logs api"
  fi
done

# ── Итог ──────────────────────────────────────────────────
section "✅ Деплой завершён!"

echo -e "
${BOLD}Доступ к сервисам:${NC}
  🌐 Веб-интерфейс:   https://localhost/
  📖 API Документация: https://localhost/api/docs
  🌺 Flower Monitor:   http://localhost:5555
  ❤️  Health Check:    https://localhost/api/v1/health

${BOLD}Полезные команды:${NC}
  docker-compose logs -f api      # Логи API
  docker-compose logs -f worker   # Логи воркера
  docker-compose ps               # Статус сервисов
  docker-compose restart worker   # Перезапуск воркера
  docker-compose down             # Остановить всё
"
