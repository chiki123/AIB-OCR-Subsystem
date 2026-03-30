"""
AIB OCR Subsystem — Data Validator
Валидация извлечённых данных

Проверяет:
  - ИНН (контрольные суммы по алгоритму ФНС)
  - КПП (формат)
  - Даты (корректность)
  - Суммы (положительность, соответствие НДС)
  - Наличие обязательных полей
"""
import re
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
from loguru import logger

from app.schemas.enums import DocumentType


class ValidationResult:
    """Результат валидации"""
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.is_valid: bool = True
    
    def add_error(self, message: str):
        self.errors.append(message)
        self.is_valid = False
    
    def add_warning(self, message: str):
        self.warnings.append(message)
    
    def confidence_penalty(self) -> float:
        """Штраф к уверенности за ошибки"""
        return len(self.errors) * 0.05 + len(self.warnings) * 0.02


class DataValidator:
    """
    Валидатор данных, извлечённых из первичных документов.
    
    Алгоритм проверки ИНН взят из официальной документации ФНС.
    """

    # Обязательные поля для каждого типа документа
    REQUIRED_FIELDS = {
        DocumentType.INVOICE: [
            "supplier_inn", "buyer_inn", "document_number", 
            "document_date", "total_amount"
        ],
        DocumentType.UPD: [
            "supplier_inn", "document_number", "document_date", "total_amount"
        ],
        DocumentType.TORG12: [
            "supplier_inn", "document_number", "document_date", "total_amount"
        ],
    }

    def validate(
        self, 
        fields: Dict[str, Any], 
        doc_type: DocumentType,
        initial_confidence: float
    ) -> Tuple[ValidationResult, float]:
        """
        Валидирует извлечённые поля.
        
        Returns:
            Tuple[ValidationResult, float]: результат и скорректированная уверенность
        """
        result = ValidationResult()
        
        # 1. Проверка обязательных полей
        self._check_required_fields(fields, doc_type, result)
        
        # 2. Валидация ИНН
        self._validate_inn(fields.get("supplier_inn"), "поставщика", result)
        if doc_type != DocumentType.TORG12:
            self._validate_inn(fields.get("buyer_inn"), "покупателя", result)
        
        # 3. Валидация КПП
        self._validate_kpp(fields.get("supplier_kpp"), "поставщика", result)
        
        # 4. Валидация даты
        self._validate_date(fields.get("document_date"), result)
        
        # 5. Валидация сумм
        self._validate_amounts(
            fields.get("total_amount"),
            fields.get("vat_amount"),
            result
        )
        
        # Корректируем уверенность
        penalty = result.confidence_penalty()
        adjusted_confidence = max(0.1, initial_confidence - penalty)
        
        logger.info(
            f"Валидатор: ошибок={len(result.errors)}, "
            f"предупреждений={len(result.warnings)}, "
            f"уверенность {initial_confidence:.2f} → {adjusted_confidence:.2f}"
        )
        
        return result, adjusted_confidence

    def _check_required_fields(
        self, 
        fields: Dict, 
        doc_type: DocumentType,
        result: ValidationResult
    ):
        """Проверяет наличие обязательных полей"""
        required = self.REQUIRED_FIELDS.get(doc_type, [])
        for field in required:
            if not fields.get(field):
                result.add_warning(f"Отсутствует обязательное поле: {field}")

    def _validate_inn(
        self, 
        inn: Optional[str], 
        context: str, 
        result: ValidationResult
    ):
        """
        Валидация ИНН по алгоритму ФНС.
        
        Алгоритм проверки контрольной суммы:
        https://www.nalog.gov.ru/rn77/taxation/reference_work/inn/
        """
        if not inn:
            return
        
        inn = inn.strip()
        
        if not re.match(r'^\d{10}$|^\d{12}$', inn):
            result.add_error(f"ИНН {context}: некорректный формат '{inn}' (ожидается 10 или 12 цифр)")
            return
        
        digits = [int(d) for d in inn]
        
        if len(inn) == 10:
            # Коэффициенты для 10-значного ИНН
            coeffs = [2, 4, 10, 3, 5, 9, 4, 6, 8]
            control = sum(c * d for c, d in zip(coeffs, digits[:9])) % 11 % 10
            if control != digits[9]:
                result.add_error(f"ИНН {context}: ошибка контрольной суммы для '{inn}'")
        
        elif len(inn) == 12:
            # Коэффициенты для 12-значного ИНН (ИП/физлицо)
            coeffs1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
            coeffs2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
            control1 = sum(c * d for c, d in zip(coeffs1, digits[:10])) % 11 % 10
            control2 = sum(c * d for c, d in zip(coeffs2, digits[:11])) % 11 % 10
            if control1 != digits[10] or control2 != digits[11]:
                result.add_error(f"ИНН {context}: ошибка контрольной суммы для '{inn}'")

    def _validate_kpp(
        self, 
        kpp: Optional[str], 
        context: str, 
        result: ValidationResult
    ):
        """Валидация КПП (9 цифр)"""
        if not kpp:
            return
        kpp = kpp.strip()
        if not re.match(r'^\d{9}$', kpp):
            result.add_warning(f"КПП {context}: некорректный формат '{kpp}' (ожидается 9 цифр)")

    def _validate_date(self, date_str: Optional[str], result: ValidationResult):
        """Валидация даты документа"""
        if not date_str:
            return
        
        date_str = date_str.strip()
        
        # Пробуем распарсить
        formats = ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"]
        parsed = None
        for fmt in formats:
            try:
                parsed = datetime.strptime(date_str, fmt)
                break
            except ValueError:
                continue
        
        if not parsed:
            result.add_warning(f"Дата: не удалось распарсить '{date_str}'")
            return
        
        # Проверяем разумность даты (не в будущем, не слишком старая)
        now = datetime.now()
        if parsed > now:
            result.add_warning(f"Дата документа в будущем: {date_str}")
        elif (now - parsed).days > 365 * 5:
            result.add_warning(f"Дата документа слишком старая: {date_str}")

    def _validate_amounts(
        self, 
        total: Optional[float], 
        vat: Optional[float], 
        result: ValidationResult
    ):
        """Валидация денежных сумм"""
        if total is not None:
            if total < 0:
                result.add_error(f"Итоговая сумма отрицательная: {total}")
            elif total == 0:
                result.add_warning("Итоговая сумма равна нулю")
            elif total > 1_000_000_000:  # 1 млрд — подозрительно
                result.add_warning(f"Итоговая сумма очень большая: {total}")
        
        if vat is not None and total is not None:
            if vat > total:
                result.add_error(f"НДС ({vat}) больше итоговой суммы ({total})")
            elif total > 0:
                vat_ratio = vat / total
                # НДС должен быть примерно 20% или 10% от суммы без НДС
                # Т.е. ~16.67% или ~9.09% от суммы с НДС
                expected_ratios = [0.2 / 1.2, 0.1 / 1.1, 0.0]  # 20%, 10%, 0%
                if not any(abs(vat_ratio - r) < 0.03 for r in expected_ratios):
                    result.add_warning(
                        f"Нестандартное соотношение НДС/итог: "
                        f"{vat:.2f}/{total:.2f} = {vat_ratio:.1%}"
                    )
