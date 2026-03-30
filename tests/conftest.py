
"""
AIB OCR Subsystem — Test Fixtures (Local Version)
Использует SQLite in-memory — не нужен PostgreSQL для тестов
"""
import asyncio
import pytest
import pytest_asyncio
from typing import AsyncGenerator
from unittest.mock import patch, MagicMock

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from httpx import AsyncClient, ASGITransport

# SQLite для тестов (не нужен Docker!)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
    )
    from app.db.base import Base
    import app.models.document  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def test_db(test_engine) -> AsyncGenerator[AsyncSession, None]:
    TestSession = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with TestSession() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def async_client(test_db) -> AsyncGenerator[AsyncClient, None]:
    from app.main import app
    from app.db.base import get_db

    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    with patch("app.api.v1.endpoints.documents.process_document_task") as mock_task:
        mock_result = MagicMock()
        mock_result.id = "test-task-id-local"
        mock_task.apply_async.return_value = mock_result

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client

    app.dependency_overrides.clear()


@pytest.fixture
def sample_invoice_text() -> str:
    return """
    СЧЕТ-ФАКТУРА № А-1042 от 15.03.2026
    Продавец: ООО Ромашка
    ИНН/КПП Продавца: 7736207543/773601001
    Покупатель: ООО Василёк
    ИНН/КПП Покупателя: 7707083893/770701001
    Итого: 158 400,00
    В том числе НДС (20%): 26 400,00
    """


@pytest.fixture
def sample_torg12_text() -> str:
    return """
    ТОВАРНАЯ НАКЛАДНАЯ ТОРГ-12 № 890 от 12.03.2026
    Грузоотправитель: ООО Поставщик ИНН 7712345000
    Грузополучатель:  ООО Получатель ИНН 7707000001
    Итого: 10 000,00
    Отпуск груза разрешил: Иванов
    """