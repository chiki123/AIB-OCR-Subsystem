"""
AIB OCR Subsystem — Document Classifier
Классификатор типа документа: Счет-фактура / УПД / ТОРГ-12

Стратегия: двухступенчатая классификация
  1. Анализ ключевых слов в тексте (быстро, без ML)
  2. Если не определено — структурный анализ макета
"""
import re
from typing import Tuple, Dict, List
from loguru import logger

from app.schemas.enums import DocumentType


# ── Ключевые слова для каждого типа документа ────────────────────────────────
# Источник: официальные формы ФНС и типовые шаблоны 1С
CLASSIFICATION_RULES: Dict[DocumentType, Dict] = {
    DocumentType.INVOICE: {
        "required_keywords": [
            r"счёт[-\s]?фактур",
            r"счет[-\s]?фактур",
        ],
        "supporting_keywords": [
            r"продавец",
            r"покупатель",
            r"ставка\s+ндс",
            r"сумма\s+налога",
            r"налоговый\s+агент",
        ],
        "negative_keywords": [
            r"универсальный\s+передаточный",
            r"функция",
        ],
        "weight": 10,
    },
    DocumentType.UPD: {
        "required_keywords": [
            r"универсальный\s+передаточный",
            r"\bупд\b",
        ],
        "supporting_keywords": [
            r"функция",
            r"статус\s+документа",
            r"передаточный\s+документ",
            r"счёт[-\s]?фактур",
        ],
        "negative_keywords": [],
        "weight": 10,
    },
    DocumentType.TORG12: {
        "required_keywords": [
            r"торг[-\s]?12",
            r"товарная\s+накладная",
        ],
        "supporting_keywords": [
            r"грузоотправитель",
            r"грузополучатель",
            r"поставщик",
            r"по\s+доверенности",
            r"отпуск\s+груза",
            r"груза\s+принял",
        ],
        "negative_keywords": [
            r"счёт[-\s]?фактур",
        ],
        "weight": 10,
    },
}


class DocumentClassifier:
    """
    Классифицирует документ по типу на основе OCR-текста.
    
    Использует взвешенный анализ ключевых слов без ML-модели.
    Это оптимально для структурированных бухгалтерских документов
    с предсказуемым набором терминов.
    """

    def classify(self, text: str) -> Tuple[DocumentType, float]:
        """
        Определяет тип документа.
        
        Args:
            text: Текст, полученный из OCR
            
        Returns:
            Tuple[DocumentType, float]: тип документа и уверенность (0.0-1.0)
        """
        if not text or len(text.strip()) < 10:
            logger.warning("Классификатор: текст слишком короткий или пустой")
            return DocumentType.UNKNOWN, 0.0

        text_lower = text.lower()
        scores: Dict[DocumentType, float] = {}

        for doc_type, rules in CLASSIFICATION_RULES.items():
            score = 0.0
            
            # Обязательные ключевые слова (высокий вес)
            required_found = 0
            for pattern in rules["required_keywords"]:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    required_found += 1
            
            if required_found == 0:
                # Без обязательного ключевого слова — не этот тип
                scores[doc_type] = 0.0
                continue
            
            # Базовый балл за обязательные слова
            score += required_found * rules["weight"]
            
            # Дополнительные ключевые слова (средний вес)
            for pattern in rules["supporting_keywords"]:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    score += 2.0
            
            # Штраф за негативные ключевые слова
            for pattern in rules["negative_keywords"]:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    score -= 5.0
            
            scores[doc_type] = max(0.0, score)

        if not scores or max(scores.values()) == 0:
            logger.warning("Классификатор: не удалось определить тип документа")
            return DocumentType.UNKNOWN, 0.0

        # Определяем победителя
        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]
        
        # Нормализуем уверенность (0.5-0.99)
        max_possible = 10 + 2 * len(CLASSIFICATION_RULES[best_type]["supporting_keywords"])
        confidence = min(0.99, max(0.5, best_score / max_possible))
        
        # Проверка на неопределённость (два типа с близкими баллами)
        sorted_scores = sorted(scores.values(), reverse=True)
        if len(sorted_scores) >= 2 and sorted_scores[0] > 0 and sorted_scores[1] > 0:
            ratio = sorted_scores[1] / sorted_scores[0]
            if ratio > 0.8:  # Слишком близко — снижаем уверенность
                confidence *= 0.7

        logger.info(
            f"Классификатор: тип={best_type.value}, "
            f"уверенность={confidence:.2f}, "
            f"баллы={scores}"
        )
        
        return best_type, confidence

    def get_document_keywords(self, doc_type: DocumentType) -> List[str]:
        """Возвращает список ключевых полей для данного типа документа"""
        field_map = {
            DocumentType.INVOICE: [
                "supplier_name", "supplier_inn", "supplier_kpp",
                "buyer_name", "buyer_inn", "buyer_kpp",
                "document_number", "document_date",
                "total_amount", "vat_amount"
            ],
            DocumentType.UPD: [
                "supplier_name", "supplier_inn", "supplier_kpp",
                "buyer_name", "buyer_inn", "buyer_kpp",
                "document_number", "document_date",
                "total_amount", "vat_amount"
            ],
            DocumentType.TORG12: [
                "supplier_name", "supplier_inn",
                "buyer_name", "buyer_inn",
                "document_number", "document_date",
                "total_amount"
            ],
        }
        return field_map.get(doc_type, [])
