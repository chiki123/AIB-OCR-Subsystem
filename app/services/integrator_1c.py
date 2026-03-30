"""
AIB OCR Subsystem — 1С Integration Service
Отправка данных в 1С:Предприятие через HTTP-сервис

Паттерны:
  - Circuit Breaker: защита от каскадных сбоев
  - Retry с экспоненциальной задержкой (через tenacity)
  - Подробное логирование для аудита

Протокол: HTTP POST с Basic Auth → 1С HTTP-сервис
Документация 1С: https://v8.1c.ru/platforma/http-servisy/
"""
import time
import json
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Any, Optional, Tuple
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from loguru import logger

from app.core.config import settings


# ── Circuit Breaker States ────────────────────────────────────────────────────

class CircuitState(str, Enum):
    CLOSED = "closed"      # Нормальная работа
    OPEN = "open"          # Блокировка (слишком много ошибок)
    HALF_OPEN = "half_open"  # Тестовый запрос после паузы


class CircuitBreaker:
    """
    Circuit Breaker для защиты от недоступности 1С-сервера.
    
    Принцип:
      CLOSED → OPEN: при N последовательных ошибках
      OPEN → HALF_OPEN: через timeout секунд
      HALF_OPEN → CLOSED: при успешном запросе
      HALF_OPEN → OPEN: при неудачном запросе
    """
    
    def __init__(self, threshold: int = 3, timeout: int = 60):
        self.threshold = threshold
        self.timeout = timeout
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.last_failure_time: Optional[datetime] = None
    
    def call(self, func, *args, **kwargs):
        """Выполняет функцию через Circuit Breaker"""
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit Breaker: переход в HALF_OPEN — тестируем 1С")
            else:
                remaining = self._remaining_timeout()
                raise CircuitOpenError(
                    f"1С недоступен (Circuit Breaker OPEN). "
                    f"Повтор через {remaining:.0f} сек."
                )
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _should_attempt_reset(self) -> bool:
        if self.last_failure_time is None:
            return True
        elapsed = (datetime.now() - self.last_failure_time).total_seconds()
        return elapsed >= self.timeout
    
    def _remaining_timeout(self) -> float:
        if self.last_failure_time is None:
            return 0
        elapsed = (datetime.now() - self.last_failure_time).total_seconds()
        return max(0, self.timeout - elapsed)
    
    def _on_success(self):
        self.failure_count = 0
        if self.state == CircuitState.HALF_OPEN:
            logger.info("Circuit Breaker: 1С восстановлен → CLOSED")
        self.state = CircuitState.CLOSED
    
    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        if self.failure_count >= self.threshold:
            if self.state != CircuitState.OPEN:
                logger.warning(
                    f"Circuit Breaker: {self.failure_count} ошибок → OPEN. "
                    f"1С заблокирован на {self.timeout} сек."
                )
            self.state = CircuitState.OPEN
        elif self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            logger.warning("Circuit Breaker: тест провалился → OPEN")


class CircuitOpenError(Exception):
    """Circuit Breaker разомкнут — запрос заблокирован"""
    pass


# ── Singleton Circuit Breaker ─────────────────────────────────────────────────
_circuit_breaker = CircuitBreaker(
    threshold=settings.C1_CIRCUIT_BREAKER_THRESHOLD,
    timeout=settings.C1_CIRCUIT_BREAKER_TIMEOUT,
)


# ── 1С Integrator ─────────────────────────────────────────────────────────────

class Integrator1C:
    """
    Отправляет извлечённые данные в 1С:Предприятие.
    
    Конечная точка в 1С: HTTP-сервис типа "ПоступлениеТоваровУслуг"
    или собственный HTTP-сервис для приёма данных.
    
    Пример URL: http://1c-server/accounting/hs/docai/documents/create
    """
    
    def __init__(self):
        self.base_url = settings.C1_BASE_URL
        self.auth = (settings.C1_USERNAME, settings.C1_PASSWORD)
        self.timeout = settings.C1_TIMEOUT_SECONDS

    @retry(
        stop=stop_after_attempt(settings.C1_MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
        reraise=True,
    )
    def send_document(
        self, 
        document_id: str,
        payload: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Отправляет документ в 1С.
        
        Args:
            document_id: UUID документа (для логирования)
            payload: JSON с извлечёнными данными
            
        Returns:
            Tuple[bool, Dict]: (успех, ответ 1С)
        """
        def _do_request():
            return self._post_to_1c(document_id, payload)
        
        try:
            return _circuit_breaker.call(_do_request)
        except CircuitOpenError as e:
            logger.warning(f"1С интеграция пропущена: {e}")
            return False, {"error": str(e), "circuit_open": True}

    def _post_to_1c(
        self,
        document_id: str,
        payload: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """Выполняет HTTP POST запрос к 1С"""
        
        url = f"{self.base_url}/documents/create"
        
        # Добавляем метаданные к payload
        request_body = {
            "task_id": document_id,
            **payload,
            "_meta": {
                "sent_at": datetime.now().isoformat(),
                "source_system": "AIB OCR Subsystem v1.0",
            }
        }
        
        logger.info(f"1С → POST {url} (document_id={document_id})")
        
        with httpx.Client(
            auth=self.auth,
            timeout=self.timeout,
            verify=False,  # On-premise — самоподписанный сертификат
        ) as client:
            response = client.post(
                url,
                json=request_body,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Accept": "application/json",
                    "X-Source": "AIB-OCR",
                }
            )
        
        if response.status_code in (200, 201):
            try:
                response_data = response.json()
            except Exception:
                response_data = {"raw": response.text}
            
            logger.success(
                f"1С ← {response.status_code} (document_id={document_id}): "
                f"{response_data}"
            )
            return True, response_data
        
        else:
            error_msg = f"1С вернул статус {response.status_code}: {response.text[:200]}"
            logger.error(f"1С ошибка (document_id={document_id}): {error_msg}")
            raise httpx.HTTPStatusError(
                error_msg,
                request=response.request,
                response=response,
            )

    def health_check(self) -> Dict[str, Any]:
        """Проверяет доступность 1С-сервера"""
        url = f"{self.base_url}/health"
        
        try:
            start = time.time()
            with httpx.Client(auth=self.auth, timeout=5, verify=False) as client:
                response = client.get(url)
            latency_ms = (time.time() - start) * 1000
            
            return {
                "available": response.status_code < 400,
                "status_code": response.status_code,
                "latency_ms": round(latency_ms, 1),
                "circuit_state": _circuit_breaker.state.value,
            }
        except Exception as e:
            return {
                "available": False,
                "error": str(e),
                "circuit_state": _circuit_breaker.state.value,
            }
