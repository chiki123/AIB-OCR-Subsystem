# ============================================================
# AIB OCR Subsystem — Makefile
# Удобные команды для разработки и эксплуатации
# ============================================================

.PHONY: help build up down logs test migrate shell clean

# Цвета
BLUE  = \033[1;34m
GREEN = \033[1;32m
NC    = \033[0m

help: ## Показать список команд
	@echo ""
	@echo "$(BLUE)AIB OCR Subsystem — Доступные команды:$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""

# ── Docker ────────────────────────────────────────────────────────────────────
build: ## Собрать Docker образы
	docker-compose build

up: ## Запустить все сервисы
	docker-compose up -d
	@echo "$(GREEN)✓ Сервисы запущены$(NC)"
	@echo "  Веб-интерфейс:   https://localhost/"
	@echo "  API Docs:        https://localhost/api/docs"
	@echo "  Flower Monitor:  http://localhost:5555"

down: ## Остановить все сервисы
	docker-compose down

restart: ## Перезапустить все сервисы
	docker-compose restart

restart-worker: ## Перезапустить только воркер (после изменений в pipeline)
	docker-compose restart worker

# ── Logs ──────────────────────────────────────────────────────────────────────
logs: ## Логи всех сервисов
	docker-compose logs -f

logs-api: ## Логи FastAPI
	docker-compose logs -f api

logs-worker: ## Логи Celery Worker
	docker-compose logs -f worker

logs-nginx: ## Логи Nginx
	docker-compose logs -f nginx

# ── Database ──────────────────────────────────────────────────────────────────
migrate: ## Применить миграции БД
	docker-compose exec api alembic upgrade head

migrate-create: ## Создать новую миграцию (make migrate-create MSG="add_field")
	docker-compose exec api alembic revision --autogenerate -m "$(MSG)"

migrate-history: ## История миграций
	docker-compose exec api alembic history

migrate-rollback: ## Откатить последнюю миграцию
	docker-compose exec api alembic downgrade -1

db-shell: ## Открыть psql
	docker-compose exec postgres psql -U $${POSTGRES_USER:-aib_user} -d $${POSTGRES_DB:-aib_ocr}

# ── Tests ─────────────────────────────────────────────────────────────────────
test: ## Запустить все тесты
	docker-compose run --rm api pytest tests/ -v --tb=short

test-pipeline: ## Тест пайплайна (без Docker)
	pytest tests/test_pipeline.py tests/test_core_services.py -v

test-cov: ## Тесты с покрытием кода
	docker-compose run --rm api pytest tests/ --cov=app --cov-report=html
	@echo "Отчёт: htmlcov/index.html"

# ── Development ───────────────────────────────────────────────────────────────
dev: ## Локальный запуск (без Docker, для разработки)
	bash scripts/dev_setup.sh

shell: ## Открыть bash в контейнере api
	docker-compose exec api bash

redis-cli: ## Открыть redis-cli
	docker-compose exec redis redis-cli

# ── Health ────────────────────────────────────────────────────────────────────
health: ## Проверка состояния системы
	@curl -s http://localhost/api/v1/health | python3 -m json.tool 2>/dev/null || \
		echo "API недоступен"

status: ## Статус Docker контейнеров
	docker-compose ps

# ── Deploy ────────────────────────────────────────────────────────────────────
deploy: ## Полный деплой в production
	bash scripts/deploy.sh

# ── Clean ─────────────────────────────────────────────────────────────────────
clean: ## Удалить контейнеры и тома (ОСТОРОЖНО: удалит данные БД!)
	@echo "ВНИМАНИЕ: Это удалит все данные!"
	@read -p "Введите 'yes' для подтверждения: " confirm; \
		[ "$$confirm" = "yes" ] && docker-compose down -v || echo "Отменено"

clean-logs: ## Очистить файлы логов
	rm -f logs/*.log
	@echo "Логи очищены"

clean-uploads: ## Очистить загруженные файлы (ОСТОРОЖНО!)
	@read -p "Удалить все файлы из storage/? (yes/no): " confirm; \
		[ "$$confirm" = "yes" ] && rm -rf storage/uploads/* storage/processed/* || echo "Отменено"
