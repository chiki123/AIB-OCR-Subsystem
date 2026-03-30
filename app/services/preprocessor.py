"""
AIB OCR Subsystem — Image Preprocessor
Предобработка изображений с помощью OpenCV

Цепочка обработки:
  1. Конвертация в grayscale
  2. Обнаружение и коррекция наклона (deskewing)
  3. Удаление шума (denoising)
  4. Адаптивная бинаризация
  5. Нормализация DPI до 300

ВАЖНО: качество OCR напрямую зависит от качества предобработки!
"""
import io
import math
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
from PIL import Image
from loguru import logger


class ImagePreprocessor:
    """
    Предобрабатывает изображения для оптимального OCR-распознавания.
    
    Основан на реальных решениях для обработки российских бухгалтерских 
    документов — сканов и фотографий с телефона.
    """
    
    TARGET_DPI = 300
    MIN_CONFIDENCE_FOR_DESKEW = 0.5  # Порог для применения деcкьюинга

    def preprocess(self, image_input: bytes | np.ndarray) -> np.ndarray:
        """
        Основной метод предобработки.
        
        Args:
            image_input: bytes изображения или numpy array
            
        Returns:
            np.ndarray: обработанное изображение (grayscale, готово для OCR)
        """
        # 1. Загружаем в numpy
        if isinstance(image_input, bytes):
            img = self._bytes_to_cv2(image_input)
        else:
            img = image_input.copy()
        
        logger.debug(f"Предобработка: входное изображение {img.shape}")
        
        # 2. Конвертируем в grayscale
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
        
        # 3. Коррекция наклона
        deskewed, angle = self._deskew(gray)
        if abs(angle) > 0.5:
            logger.debug(f"Предобработка: коррекция наклона {angle:.1f}°")
        
        # 4. Удаление шума
        denoised = self._denoise(deskewed)
        
        # 5. Адаптивная бинаризация
        binarized = self._binarize(denoised)
        
        # 6. Удаление рамки/полей сканера
        cleaned = self._remove_border(binarized)
        
        logger.debug(f"Предобработка завершена: выходное изображение {cleaned.shape}")
        return cleaned

    def preprocess_for_paddle(self, image_input: bytes | np.ndarray) -> np.ndarray:
        """
        Предобработка специально для PaddleOCR.
        PaddleOCR лучше работает с BGR изображением, не бинаризованным.
        """
        if isinstance(image_input, bytes):
            img = self._bytes_to_cv2(image_input)
        else:
            img = image_input.copy()
        
        # Только дескьюинг и нормализация — без агрессивной бинаризации
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        deskewed, angle = self._deskew(gray)
        
        # Нормализация яркости
        normalized = self._normalize_brightness(deskewed)
        
        # Конвертируем обратно в BGR для PaddleOCR
        bgr = cv2.cvtColor(normalized, cv2.COLOR_GRAY2BGR)
        
        return bgr

    def _bytes_to_cv2(self, image_bytes: bytes) -> np.ndarray:
        """Конвертирует bytes в numpy array"""
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Не удалось декодировать изображение")
        return img

    def _deskew(self, gray_img: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        Коррекция наклона документа.
        
        Алгоритм: нахождение угла через минимальную прямоугольную обертку
        вокруг белых пикселей после бинаризации.
        
        Источник: стандартный подход для обработки сканов документов.
        """
        # Бинаризация для определения угла
        _, thresh = cv2.threshold(gray_img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        # Находим координаты ненулевых пикселей
        coords = np.column_stack(np.where(thresh > 0))
        
        if len(coords) < 100:
            return gray_img, 0.0
        
        # Минимальная прямоугольная обертка
        rect = cv2.minAreaRect(coords)
        angle = rect[-1]
        
        # Нормализуем угол к диапазону [-45, 45]
        if angle < -45:
            angle = 90 + angle
        elif angle > 45:
            angle = angle - 90
        
        # Применяем коррекцию только для значимых углов
        if abs(angle) < 0.5:
            return gray_img, angle
        
        # Поворот изображения
        (h, w) = gray_img.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            gray_img, M, (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE
        )
        
        return rotated, angle

    def _denoise(self, gray_img: np.ndarray) -> np.ndarray:
        """
        Удаление шума.
        Используем fastNlMeansDenoising — хорош для сканов с зернистостью.
        """
        # Параметры подобраны для бухгалтерских документов
        denoised = cv2.fastNlMeansDenoising(gray_img, h=10, searchWindowSize=21, templateWindowSize=7)
        return denoised

    def _binarize(self, gray_img: np.ndarray) -> np.ndarray:
        """
        Адаптивная бинаризация.
        
        Адаптивный метод лучше справляется с неравномерным освещением —
        частая проблема для фотографий с телефона.
        """
        # Гауссово размытие для сглаживания шума перед бинаризацией
        blurred = cv2.GaussianBlur(gray_img, (3, 3), 0)
        
        # Адаптивная бинаризация по Гауссу
        binary = cv2.adaptiveThreshold(
            blurred,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=11,  # Размер окна (нечётное число)
            C=10           # Константа вычитания
        )
        
        return binary

    def _normalize_brightness(self, gray_img: np.ndarray) -> np.ndarray:
        """Нормализация яркости через CLAHE (адаптивное выравнивание гистограммы)"""
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(gray_img)

    def _remove_border(self, binary_img: np.ndarray) -> np.ndarray:
        """
        Удаление черных рамок сканера по краям изображения.
        Находим bounding box содержимого и обрезаем лишнее.
        """
        # Инвертируем для нахождения содержимого
        inverted = cv2.bitwise_not(binary_img)
        
        # Находим ненулевые пиксели
        coords = cv2.findNonZero(inverted)
        if coords is None:
            return binary_img
        
        x, y, w, h = cv2.boundingRect(coords)
        
        # Добавляем отступ 10px
        padding = 10
        x = max(0, x - padding)
        y = max(0, y - padding)
        w = min(binary_img.shape[1] - x, w + 2 * padding)
        h = min(binary_img.shape[0] - y, h + 2 * padding)
        
        return binary_img[y:y+h, x:x+w]

    @staticmethod
    def pdf_to_images(pdf_bytes: bytes) -> list[np.ndarray]:
        """
        Конвертирует PDF в список изображений.
        Требует: poppler-utils (apt install poppler-utils)
        """
        from pdf2image import convert_from_bytes
        
        pil_images = convert_from_bytes(
            pdf_bytes,
            dpi=300,  # Высокое DPI для качественного OCR
            fmt="jpeg"
        )
        
        result = []
        for pil_img in pil_images:
            # Конвертируем PIL в numpy/BGR
            img_array = np.array(pil_img)
            bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
            result.append(bgr)
        
        logger.debug(f"PDF конвертирован: {len(result)} страниц")
        return result
