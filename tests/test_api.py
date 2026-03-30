"""
AIB OCR Subsystem — Integration Tests
Тесты API endpoints через httpx TestClient

Запуск: pytest tests/test_api.py -v
"""
import io
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.fixture
async def async_client():
    """Async HTTP клиент для тестирования FastAPI"""
    from app.main import app
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        yield client


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_200(self, async_client):
        response = await async_client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "services" in data
        assert "version" in data


class TestDocumentUpload:
    @pytest.mark.asyncio
    async def test_upload_invalid_extension(self, async_client):
        """Отклонение файла с недопустимым расширением"""
        file_content = b"fake content"
        response = await async_client.post(
            "/api/v1/documents/upload",
            files={"file": ("document.exe", io.BytesIO(file_content), "application/octet-stream")},
        )
        assert response.status_code == 400
        assert "Недопустимый формат" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_upload_pdf_accepted(self, async_client):
        """Корректный PDF принимается системой"""
        # Минимальный валидный PDF
        pdf_header = b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\nxref\n0 1\n0000000000 65535 f\ntrailer\n<< /Size 1 >>\nstartxref\n9\n%%EOF"
        
        with patch("app.api.v1.endpoints.documents.process_document_task") as mock_task:
            mock_task.apply_async.return_value = MagicMock(id="test-task-id-123")
            
            response = await async_client.post(
                "/api/v1/documents/upload",
                files={"file": ("invoice.pdf", io.BytesIO(pdf_header), "application/pdf")},
            )
        
        assert response.status_code == 202
        data = response.json()
        assert "task_id" in data
        assert "document_id" in data
        assert data["status"] == "queued"

    @pytest.mark.asyncio
    async def test_upload_jpeg_accepted(self, async_client):
        """Корректный JPEG принимается системой"""
        # Минимальный JPEG (1x1 pixel)
        jpeg_bytes = bytes([
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46,
            0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,
            0xFF, 0xD9
        ])
        
        with patch("app.api.v1.endpoints.documents.process_document_task") as mock_task:
            mock_task.apply_async.return_value = MagicMock(id="test-task-id-456")
            
            response = await async_client.post(
                "/api/v1/documents/upload",
                files={"file": ("photo.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
            )
        
        assert response.status_code == 202


class TestDocumentsList:
    @pytest.mark.asyncio
    async def test_list_documents_empty(self, async_client):
        """Пустой список документов"""
        response = await async_client.get("/api/v1/documents/")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data

    @pytest.mark.asyncio
    async def test_list_documents_pagination(self, async_client):
        """Проверка пагинации"""
        response = await async_client.get("/api/v1/documents/?page=1&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10


class TestTaskStatus:
    @pytest.mark.asyncio
    async def test_unknown_task_returns_pending(self, async_client):
        """Несуществующий task_id возвращает pending статус"""
        with patch("app.api.v1.endpoints.tasks.AsyncResult") as mock_result:
            mock_instance = MagicMock()
            mock_instance.state = "PENDING"
            mock_instance.result = None
            mock_result.return_value = mock_instance
            
            response = await async_client.get("/api/v1/tasks/nonexistent-task-id/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["task_id"] == "nonexistent-task-id"
