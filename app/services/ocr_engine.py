"""
AIB OCR Subsystem — OCR Engine
Обертка над PaddleOCR с паттерном Singleton

КРИТИЧЕСКАЯ ИЗВЕСТНАЯ ПРОБЛЕМА PaddleOCR:
  PaddleOCR падает при повторных вызовах из-за удержания состояния.
  РЕШЕНИЕ: Singleton на уровне Celery Worker процесса.
  Каждый worker создает OCR инстанс один раз при старте.

Источник: https://eklavvya.hashnode.dev/building-an-event-driven-ocr-service-challenges-and-solutions
"""
import threading
from typing import Optional, List, Dict, Any, Tuple
import numpy as np
from loguru import logger

from app.core.config import settings


# ── OCR Singleton ────────────────────────────────────────────────────────────
_ocr_instance: Optional[Any] = None
_ocr_lock = threading.Lock()


def get_ocr_engine():
    """
    Thread-safe Singleton для PaddleOCR.
    
    PaddleOCR не должен создаваться повторно в одном процессе.
    Первый вызов инициализирует модель (~3-5 сек), последующие быстрые.
    """
    global _ocr_instance
    
    if _ocr_instance is None:
        with _ocr_lock:
            if _ocr_instance is None:  # Double-checked locking
                logger.info("Инициализация PaddleOCR... (первый запуск занимает 3-5 сек)")
                try:
                    from paddleocr import PaddleOCR
                    _ocr_instance = PaddleOCR(
                        use_angle_cls=settings.PADDLE_USE_ANGLE_CLS,
                        lang=settings.PADDLE_LANG,
                        use_gpu=settings.PADDLE_USE_GPU,
                        cpu_threads=settings.PADDLE_CPU_THREADS,
                        show_log=settings.PADDLE_SHOW_LOG,
                        enable_mkldnn=True,      # MKL-DNN ускорение CPU
                        det_db_score_mode="slow",  # Более точный режим детекции
                        rec_batch_num=6,        # Батч для ускорения
                    )
                    logger.success("PaddleOCR успешно инициализирован")
                except Exception as e:
                    logger.error(f"Ошибка инициализации PaddleOCR: {e}")
                    raise
    
    return _ocr_instance


# ── Structure Engine (для таблиц) ────────────────────────────────────────────
_structure_instance: Optional[Any] = None
_structure_lock = threading.Lock()


def get_structure_engine():
    """Singleton для PP-StructureV3 — распознавание таблиц"""
    global _structure_instance
    
    if _structure_instance is None:
        with _structure_lock:
            if _structure_instance is None:
                logger.info("Инициализация PP-Structure (таблицы)...")
                try:
                    from paddleocr import PPStructure
                    _structure_instance = PPStructure(
                        table=True,
                        ocr=True,
                        lang='en',
                        use_gpu=settings.PADDLE_USE_GPU,
                        show_log=False,
                    )
                    logger.success("PP-Structure инициализирован")
                except Exception as e:
                    logger.warning(f"PP-Structure недоступен: {e}. Таблицы будут обрабатываться через базовый OCR")
    
    return _structure_instance


# ── OCR Engine Class ──────────────────────────────────────────────────────────

class OCREngine:
    """
    Высокоуровневая обертка над PaddleOCR.
    
    Предоставляет:
    - Распознавание текста из изображения
    - Распознавание таблиц (PP-Structure)
    - Извлечение полного текста как строки
    - Извлечение структурированных блоков с координатами
    """

    def recognize(self, image: np.ndarray) -> Dict[str, Any]:
        """
        Распознаёт текст на изображении.
        
        Args:
            image: BGR numpy array (после предобработки)
            
        Returns:
            Dict с полями:
              - full_text: весь текст как одна строка
              - blocks: список блоков [{text, confidence, bbox}]
              - avg_confidence: средняя уверенность
        """
        ocr = get_ocr_engine()
        
        try:
            # PaddleOCR возвращает: [[[bbox, (text, confidence)], ...], ...]
            result = ocr.ocr(image, cls=True)
        except Exception as e:
            logger.error(f"OCR ошибка: {e}")
            # Пробуем без угловой классификации
            result = ocr.ocr(image, cls=False)
        
        if not result or result[0] is None:
            logger.warning("OCR: пустой результат")
            return {"full_text": "", "blocks": [], "avg_confidence": 0.0}
        
        blocks = []
        confidences = []
        
        for page_result in result:
            if not page_result:
                continue
            for line in page_result:
                if not line or len(line) < 2:
                    continue
                
                bbox = line[0]   # Координаты [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
                text_data = line[1]
                
                if not text_data or len(text_data) < 2:
                    continue
                
                text = text_data[0]
                confidence = float(text_data[1])
                
                if text and text.strip():
                    blocks.append({
                        "text": text.strip(),
                        "confidence": confidence,
                        "bbox": bbox,
                    })
                    confidences.append(confidence)
        
        # Строим полный текст с сохранением порядка (сортировка по Y-координате)
        sorted_blocks = sorted(blocks, key=lambda b: b["bbox"][0][1])  # Сортировка по Y
        full_text = "\n".join(b["text"] for b in sorted_blocks)
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        
        logger.debug(
            f"OCR: {len(blocks)} блоков, "
            f"средняя уверенность: {avg_confidence:.2f}, "
            f"текст: {len(full_text)} символов"
        )
        
        return {
            "full_text": full_text,
            "blocks": sorted_blocks,
            "avg_confidence": avg_confidence,
        }

    def recognize_with_structure(self, image: np.ndarray) -> Dict[str, Any]:
        """
        Распознавание с анализом структуры (таблицы, заголовки).
        Использует PP-StructureV3.
        """
        structure = get_structure_engine()
        
        if structure is None:
            # Fallback к базовому OCR
            logger.debug("PP-Structure недоступен, используем базовый OCR")
            return self.recognize(image)
        
        try:
            result = structure(image)
            
            tables = []
            text_regions = []
            
            for region in result:
                region_type = region.get("type", "text")
                
                if region_type == "table":
                    # Извлекаем HTML таблицы для последующего парсинга
                    tables.append({
                        "html": region.get("res", {}).get("html", ""),
                        "bbox": region.get("bbox", []),
                    })
                elif region_type in ("text", "title"):
                    res = region.get("res", [])
                    if isinstance(res, list):
                        for line in res:
                            if isinstance(line, (list, tuple)) and len(line) >= 2:
                                text_regions.append({
                                    "text": line[1][0] if isinstance(line[1], (list, tuple)) else str(line[1]),
                                    "confidence": float(line[1][1]) if isinstance(line[1], (list, tuple)) else 0.8,
                                    "bbox": line[0],
                                })
            
            full_text = "\n".join(r["text"] for r in text_regions)
            avg_conf = sum(r["confidence"] for r in text_regions) / len(text_regions) if text_regions else 0.0
            
            return {
                "full_text": full_text,
                "blocks": text_regions,
                "tables": tables,
                "avg_confidence": avg_conf,
            }
        
        except Exception as e:
            logger.error(f"PP-Structure ошибка: {e}, fallback к базовому OCR")
            return self.recognize(image)

    def recognize_bytes(self, image_bytes: bytes) -> Dict[str, Any]:
        """Удобный метод для распознавания из bytes"""
        import cv2
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Не удалось декодировать изображение")
        return self.recognize_with_structure(img)