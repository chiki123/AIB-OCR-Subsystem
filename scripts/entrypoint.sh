#!/bin/bash
# ============================================================
# AIB OCR Subsystem — Docker Entrypoint (Local/Dev Modified)
# Запускает нужный сервис в зависимости от SERVICE_TYPE
# ============================================================

set -e

SERVICE=${SERVICE_TYPE:-api}

echo "=== AIB OCR Subsystem ==="
echo "Сервис: $SERVICE"
echo "Окружение: ${APP_ENV:-production}"
echo "========================="

# --- الكود الأصلي (معطل للتشغيل المحلي) ---
# Ожидаем доступности PostgreSQL
# wait_for_postgres() {
#     echo "Ожидание PostgreSQL..."
#     for i in $(seq 1 30); do
#         python -c "
# import psycopg2, os
# try:
#     psycopg2.connect(os.environ['DATABASE_URL_SYNC'])
#     print('PostgreSQL готов!')
#     exit(0)
# except:
#     exit(1)
# " && return 0
#         echo "  Попытка $i/30..."
#         sleep 2
#     done
#     echo "ОШИБКА: PostgreSQL недоступен"
#     exit 1
# }

# Ожидаем доступности Redis
# wait_for_redis() {
#     echo "Ожидание Redis..."
#     for i in $(seq 1 20); do
#         python -c "
# import redis, os
# r = redis.from_url(os.environ.get('REDIS_URL', 'redis://redis:6379/0'))
# r.ping()
# print('Redis готов!')
# " 2>/dev/null && return 0
#         echo "  Попытка $i/20..."
#         sleep 2
#     done
#     echo "ОШИБКА: Redis недоступен"
#     exit 1
# }
# ------------------------------------------

case $SERVICE in
    api)
        # --- الكود الأصلي (معطل) ---
        # wait_for_postgres
        # wait_for_redis
        # echo "Применение миграций БД..."
        # alembic upgrade head
        # echo "Запуск FastAPI..."
        # exec uvicorn app.main:app \
        #     --host "${API_HOST:-0.0.0.0}" \
        #     --port "${API_PORT:-8000}" \
        #     --workers "${API_WORKERS:-4}" \
        #     --loop uvloop \
        #     --http h11 \
        #     --access-log \
        #     --log-level info
        # ---------------------------
        
        echo "[DEV] Запуск FastAPI напрямую (пропуск проверок БД)..."
        exec uvicorn app.main:app \
            --host "0.0.0.0" \
            --port "8000" \
            --reload
        ;;

    worker)
        # wait_for_postgres
        # wait_for_redis
        echo "Запуск Celery Worker..."
        exec celery -A app.workers.celery_app worker \
            --loglevel=info \
            --concurrency=2 \
            --queues=ocr_processing,integration \
            --prefetch-multiplier=1 \
            --max-tasks-per-child=100
        ;;

    beat)
        # wait_for_redis
        echo "Запуск Celery Beat..."
        exec celery -A app.workers.celery_app beat \
            --loglevel=info
        ;;

    watcher)
        # wait_for_redis
        echo "Запуск Hot Folder Watcher..."
        exec python -m app.services.hot_folder_watcher
        ;;

    flower)
        # wait_for_redis
        echo "Запуск Flower..."
        exec celery -A app.workers.celery_app flower \
            --port=5555 \
            --basic_auth="${FLOWER_USER:-admin}:${FLOWER_PASSWORD:-changeme}"
        ;;

    migrate)
        # wait_for_postgres
        echo "Применение миграций..."
        exec alembic upgrade head
        ;;

    test)
        echo "Запуск тестов..."
        exec pytest tests/ -v --tb=short
        ;;

    *)
        echo "Неизвестный SERVICE_TYPE: $SERVICE"
        echo "Допустимые значения: api, worker, beat, watcher, flower, migrate, test"
        exit 1
        ;;
esac