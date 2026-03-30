-- ============================================================
-- AIB OCR Subsystem — PostgreSQL Initialization
-- Выполняется при первом запуске контейнера PostgreSQL
-- ============================================================

-- Настройки для русского языка
SET client_encoding = 'UTF8';

-- Создаём базу данных если не существует (обычно создаётся через env)
-- CREATE DATABASE aib_ocr ENCODING 'UTF8' LC_COLLATE 'ru_RU.UTF-8' LC_CTYPE 'ru_RU.UTF-8';

-- Расширения PostgreSQL
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- Генерация UUID
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- Нечёткий поиск по строкам (будущее)
CREATE EXTENSION IF NOT EXISTS "btree_gin";   -- GIN индексы для JSONB

-- Комментарий к базе данных
COMMENT ON DATABASE aib_ocr IS 
  'AIB OCR Subsystem — база данных для хранения документов и результатов распознавания';
