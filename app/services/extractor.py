"""
AIB OCR Subsystem — Entity Extractor
Извлечение структурированных данных из OCR-текста

Стратегия: шаблонная экстракция через регулярные выражения
  - Специализированные паттерны для каждого поля
  - Разные правила для каждого типа документа
  - Нормализация извлечённых значений

Основано на анализе реальных российских бухгалтерских документов.
Источники: ФНС, типовые шаблоны 1С, открытые датасеты накладных.
"""
import re
from typing import Dict, Any, Optional, List, Tuple
from loguru import logger

from app.schemas.enums import DocumentType


# ── Регулярные выражения ──────────────────────────────────────────────────────

class RussianDocumentPatterns:
    """
    Паттерны для извлечения данных из российских первичных документов.
    Улучшены для обхода ошибок OCR (греческие буквы, лишние пробелы, переносы).
    """
    
    # ИНН: игнорируем любые пробелы, двоеточия и лишний текст до цифр
    INN = re.compile(
        r'(?:инн|ИНН|Tax ID)[^\d]*([0-9]{10,12})',
        re.IGNORECASE
    )
    
    # КПП: OCR часто путает русские КПП с греческими ΚΠΠ или латинскими KPP
    KPP = re.compile(
        r'(?:[КKΚ][ПPΠ][ПPΠ]|КПК|Reg Code)[^\d]*([0-9]{9})',
        re.IGNORECASE
    )
    
    INN_KPP_COMBINED = re.compile(
        r'([0-9]{10,12})[/\\]([0-9]{9})'
    )
    
    # Номер документа: останавливаемся до слова "от"
    DOC_NUMBER = re.compile(
        r'(?:№|N|номер|INV-|Invoice No)\s*([А-Яа-яA-Za-z0-9\-./]+)',
        re.IGNORECASE
    )
    
    # Дата (DD.MM.YYYY)
    DATE = re.compile(
        r'(?:дата|от|Date)[:\s]*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})',
        re.IGNORECASE
    )
    
    DATE_STANDALONE = re.compile(
        r'\b(\d{2}\.\d{2}\.\d{4})\b'
    )
    
    # Итоговая сумма: заставляем искать числа с копейками [.,][0-9]{2} чтобы избежать процентов вроде (20%)
    TOTAL_AMOUNT = re.compile(
        r'(?:всего к оплате|итого к оплате|итого(?: с ндс)?|сумма|Total Amount Due|Total|Subtotal).*?([0-9\s]+[.,][0-9]{2})',
        re.IGNORECASE
    )
    
    # Сумма НДС
    VAT_AMOUNT = re.compile(
        r'(?:в том числе нДС|сумма нДС|нДС итого|нДС|VAT Amount).*?([0-9\s]+[.,][0-9]{2})',
        re.IGNORECASE
    )
    
    VAT_RATE = re.compile(
        r'(?:ставка нДС|нДС|VAT)[:\s]*(\d+%?)',
        re.IGNORECASE
    )
    
    # Поставщик/Продавец: берем всё до конца строки
    SUPPLIER_NAME = re.compile(
        r'(?:поставщик|продавец|грузоотправитель|Vendor|Supplier)\s*[:\.]?\s*((?:ООО|ЗАО|ОАО|ПАО|АО|ИП|ФГУП)[^\n]+)',
        re.IGNORECASE
    )
    
    # Покупатель: берем всё до конца строки
    BUYER_NAME = re.compile(
        r'(?:покупатель|получатель|грузополучатель|Customer|Buyer)\s*[:\.]?\s*((?:ООО|ЗАО|ОАО|ПАО|АО|ИП|ФГУП)[^\n]+)',
        re.IGNORECASE
    )
    
    ORG_NAME = re.compile(
        r'((?:ООО|ЗАО|ОАО|ПАО|АО|ИП)\s+[«"]?[А-Яа-яA-Za-z0-9\s\-]+[»"]?)',
        re.IGNORECASE
    )


PATTERNS = RussianDocumentPatterns()


class EntityExtractor:
    """
    Извлекает структурированные данные из OCR-текста.
    
    Работает в связке с классификатором: 
    разные стратегии для разных типов документов.
    """

    def extract(
        self, 
        text: str, 
        doc_type: DocumentType,
        ocr_blocks: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Извлекает все поля документа.
        
        Args:
            text: Полный OCR-текст документа
            doc_type: Тип документа (из классификатора)
            ocr_blocks: Блоки с координатами (для позиционного извлечения)
            
        Returns:
            Dict с извлечёнными полями
        """
        result = {}
        
        # Основные поля — общие для всех типов
        result.update(self._extract_document_number(text))
        result.update(self._extract_document_date(text))
        result.update(self._extract_inn_kpp_pairs(text))
        result.update(self._extract_amounts(text))
        result.update(self._extract_org_names(text))
        
        # Специфичные для типа документа
        if doc_type == DocumentType.INVOICE:
            result.update(self._extract_invoice_specific(text))
        elif doc_type == DocumentType.TORG12:
            result.update(self._extract_torg12_specific(text))
        elif doc_type == DocumentType.UPD:
            result.update(self._extract_upd_specific(text))
        
        # Нормализация
        result = self._normalize_fields(result)
        
        logger.info(f"Экстрактор: извлечено {sum(1 for v in result.values() if v)} полей из {len(result)}")
        return result

    def _extract_document_number(self, text: str) -> Dict:
        """Извлечение номера документа"""
        match = PATTERNS.DOC_NUMBER.search(text)
        if match:
            number = match.group(1).strip().rstrip('.,')
            # Игнорируем предлоги, которые случайно попали как номер
            if number.lower() not in ['от', 'of']:
                return {"document_number": number}
        return {"document_number": None}

    def _extract_document_date(self, text: str) -> Dict:
        """Извлечение даты документа"""
        # Сначала ищем с ключевым словом
        match = PATTERNS.DATE.search(text)
        if match:
            date_str = self._normalize_date(match.group(1))
            return {"document_date": date_str}
        
        # Затем standalone дата
        match = PATTERNS.DATE_STANDALONE.search(text)
        if match:
            date_str = self._normalize_date(match.group(1))
            return {"document_date": date_str}
        
        return {"document_date": None}

    def _extract_inn_kpp_pairs(self, text: str) -> Dict:
        """
        Извлечение ИНН и КПП для поставщика и покупателя.
        
        Логика: ищем по контексту, безопасно разделяя зоны продавца и покупателя.
        """
        result = {
            "supplier_inn": None, "supplier_kpp": None,
            "buyer_inn": None, "buyer_kpp": None,
        }
        
        text_lower = text.lower()
        
        # Ищем позиции ключевых слов для продавца и покупателя
        s_idx = max(text_lower.find("продав"), text_lower.find("постав"), text_lower.find("vendor"))
        b_idx = max(text_lower.find("покуп"), text_lower.find("получат"), text_lower.find("customer"))
        
        # Безопасное разделение зон (без математического деления пополам)
        if s_idx >= 0 and b_idx >= 0:
            if s_idx < b_idx:
                supplier_zone = text[s_idx:b_idx]
                buyer_zone = text[b_idx:]
            else:
                buyer_zone = text[b_idx:s_idx]
                supplier_zone = text[s_idx:]
        else:
            supplier_zone = text
            buyer_zone = text
        
        # Извлекаем ИНН из зон
        supplier_inn_match = PATTERNS.INN.search(supplier_zone)
        if supplier_inn_match:
            result["supplier_inn"] = supplier_inn_match.group(1)
            
        buyer_inn_match = PATTERNS.INN.search(buyer_zone)
        if buyer_inn_match:
            result["buyer_inn"] = buyer_inn_match.group(1)
        
        # Извлекаем КПП из зон
        supplier_kpp_match = PATTERNS.KPP.search(supplier_zone)
        if supplier_kpp_match:
            result["supplier_kpp"] = supplier_kpp_match.group(1)
            
        buyer_kpp_match = PATTERNS.KPP.search(buyer_zone)
        if buyer_kpp_match:
            result["buyer_kpp"] = buyer_kpp_match.group(1)
            
        # Fallback на комбинированный паттерн, если что-то не нашли
        if not result["supplier_inn"]:
            comb = PATTERNS.INN_KPP_COMBINED.search(supplier_zone)
            if comb:
                result["supplier_inn"] = comb.group(1)
                result["supplier_kpp"] = comb.group(2)
                
        if not result["buyer_inn"]:
            comb = PATTERNS.INN_KPP_COMBINED.search(buyer_zone)
            if comb:
                result["buyer_inn"] = comb.group(1)
                result["buyer_kpp"] = comb.group(2)
        
        return result

    def _extract_amounts(self, text: str) -> Dict:
        """Извлечение денежных сумм"""
        result = {"total_amount": None, "vat_amount": None}
        
        total_match = PATTERNS.TOTAL_AMOUNT.search(text)
        if total_match:
            amount_str = total_match.group(1)
            result["total_amount"] = self._parse_amount(amount_str)
        
        vat_match = PATTERNS.VAT_AMOUNT.search(text)
        if vat_match:
            amount_str = vat_match.group(1)
            result["vat_amount"] = self._parse_amount(amount_str)
        
        return result

    def _extract_org_names(self, text: str) -> Dict:
        """Извлечение названий организаций"""
        result = {"supplier_name": None, "buyer_name": None}
        
        supplier_match = PATTERNS.SUPPLIER_NAME.search(text)
        if supplier_match:
            result["supplier_name"] = supplier_match.group(1).strip()
        
        buyer_match = PATTERNS.BUYER_NAME.search(text)
        if buyer_match:
            result["buyer_name"] = buyer_match.group(1).strip()
        
        # Если не нашли через специфичные паттерны — используем общий
        if not result["supplier_name"] or not result["buyer_name"]:
            org_matches = PATTERNS.ORG_NAME.findall(text)
            if len(org_matches) >= 1 and not result["supplier_name"]:
                result["supplier_name"] = org_matches[0].strip()
            if len(org_matches) >= 2 and not result["buyer_name"]:
                result["buyer_name"] = org_matches[1].strip()
        
        return result

    def _extract_invoice_specific(self, text: str) -> Dict:
        """Специфичные поля для счет-фактуры"""
        result = {}
        # Дополнительные поля счет-фактуры
        vat_rate_match = PATTERNS.VAT_RATE.search(text)
        if vat_rate_match:
            result["vat_rate"] = vat_rate_match.group(1)
        return result

    def _extract_torg12_specific(self, text: str) -> Dict:
        """Специфичные поля для ТОРГ-12"""
        result = {}
        # Номер доверенности, основание и т.д.
        return result

    def _extract_upd_specific(self, text: str) -> Dict:
        """Специфичные поля для УПД"""
        result = {}
        # Функция УПД (1 или 2)
        if re.search(r'функция.*?[«"]?(1|2)[»"]?', text, re.IGNORECASE):
            match = re.search(r'функция.*?[«"]?([12])[»"]?', text, re.IGNORECASE)
            if match:
                result["upd_function"] = match.group(1)
        return result

    def _normalize_date(self, date_str: str) -> str:
        """Нормализует дату в формат YYYY-MM-DD"""
        date_str = date_str.strip()
        # Заменяем разделители
        normalized = re.sub(r'[./\-]', '.', date_str)
        parts = normalized.split('.')
        
        if len(parts) == 3:
            day, month, year = parts
            if len(year) == 2:
                year = "20" + year
            try:
                return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
            except ValueError:
                pass
        
        return date_str

    def _parse_amount(self, amount_str: str) -> Optional[float]:
        """Парсит денежную сумму в float"""
        # Убираем пробелы и нецифровые символы кроме ,/.
        cleaned = re.sub(r'[^\d.,]', '', amount_str.strip())
        if not cleaned:
            return None
        # Заменяем запятую на точку
        cleaned = cleaned.replace(',', '.')
        # Убираем лишние точки (разделитель тысяч)
        parts = cleaned.split('.')
        if len(parts) > 2:
            cleaned = ''.join(parts[:-1]) + '.' + parts[-1]
        
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _normalize_fields(self, fields: Dict) -> Dict:
        """Нормализация и очистка всех полей"""
        for key, value in fields.items():
            if isinstance(value, str):
                fields[key] = value.strip()
                if not fields[key] or fields[key].lower() in ['от', 'of']:
                    fields[key] = None
        return fields