"""
AIB OCR Subsystem — Pipeline Integration Test
Полный тест пайплайна: classify → extract → validate

Запуск: pytest tests/test_pipeline.py -v
(Не требует запущенных Docker-контейнеров)
"""
import pytest
from app.services.classifier  import DocumentClassifier
from app.services.extractor   import EntityExtractor
from app.services.validator   import DataValidator
from app.schemas.enums        import DocumentType


class TestFullPipeline:
    """
    Тестирует полный цикл: текст → классификация → извлечение → валидация
    без реального OCR (используем готовый текст).
    """

    def setup_method(self):
        self.classifier = DocumentClassifier()
        self.extractor  = EntityExtractor()
        self.validator  = DataValidator()

    def _run(self, text: str):
        """Прогоняет текст через полный пайплайн"""
        doc_type, class_conf = self.classifier.classify(text)
        fields = self.extractor.extract(text, doc_type)
        val_result, final_conf = self.validator.validate(fields, doc_type, class_conf)
        return doc_type, fields, val_result, final_conf

    # ── Счет-фактура ───────────────────────────────────────────────────────

    def test_invoice_full_pipeline(self):
        text = """
        СЧЕТ-ФАКТУРА № А-1042 от 15.03.2026
        Продавец: ООО Ромашка
        ИНН Продавца: 7736207543 КПП 773601001
        Покупатель: ООО Василёк
        ИНН Покупателя: 7707083893 КПП 770701001
        Итого: 158 400,00
        В том числе НДС (20%): 26 400,00
        Ставка НДС: 20%
        """
        doc_type, fields, val, conf = self._run(text)

        assert doc_type == DocumentType.INVOICE
        assert fields["document_number"] is not None
        assert fields["document_date"] == "2026-03-15"
        assert fields["total_amount"] == 158400.0
        assert fields["vat_amount"] == 26400.0
        assert conf > 0.0

    def test_invoice_inn_extraction(self):
        text = """
        СЧЕТ-ФАКТУРА № 5 от 01.01.2026
        Продавец: ООО Тест ИНН 7736207543 КПП 773601001
        Покупатель: АО Клиент ИНН 7707083893 КПП 770701001
        Итого: 100,00 В том числе НДС: 16,67
        """
        _, fields, _, _ = self._run(text)
        assert fields.get("supplier_inn") == "7736207543"
        assert fields.get("buyer_inn")    == "7707083893"

    # ── ТОРГ-12 ────────────────────────────────────────────────────────────

    def test_torg12_full_pipeline(self):
        text = """
        ТОВАРНАЯ НАКЛАДНАЯ ТОРГ-12 № 890 от 12.03.2026
        Грузоотправитель: ООО Поставщик ИНН 7712345000 КПП 771301001
        Грузополучатель:  ООО Получатель ИНН 7707000001 КПП 770701001
        Итого: 10 000,00
        Отпуск груза разрешил: Иванов И.И.
        """
        doc_type, fields, val, conf = self._run(text)
        assert doc_type == DocumentType.TORG12
        assert fields["document_date"] == "2026-03-12"
        assert fields["total_amount"] == 10000.0

    # ── УПД ───────────────────────────────────────────────────────────────

    def test_upd_full_pipeline(self):
        text = """
        Универсальный передаточный документ
        Функция 1
        Счет-фактура № 201 от 20.03.2026
        Продавец: ООО АИБ ИНН 6670000001 КПП 667001001
        Покупатель: ООО Клиент ИНН 6671234567 КПП 667101001
        Итого: 50 000,00
        В том числе НДС: 8 333,33
        """
        doc_type, fields, val, conf = self._run(text)
        assert doc_type == DocumentType.UPD
        assert fields["total_amount"] == 50000.0

    # ── Валидация ИНН ──────────────────────────────────────────────────────

    def test_invalid_inn_reduces_confidence(self):
        text = """
        СЧЕТ-ФАКТУРА № 1 от 01.01.2026
        Продавец: ООО Тест ИНН 1234567890
        Покупатель: ООО Клиент
        Итого: 100,00
        """
        _, fields, val_result, final_conf = self._run(text)
        # ИНН 1234567890 не проходит контрольную сумму
        has_inn_error = any("ИНН" in e for e in val_result.errors)
        assert has_inn_error
        # Уверенность снижается при ошибках
        assert final_conf < 0.9

    # ── Дата нормализация ──────────────────────────────────────────────────

    @pytest.mark.parametrize("date_input,expected", [
        ("15.03.2026",  "2026-03-15"),
        ("15/03/2026",  "2026-03-15"),
        ("15-03-2026",  "2026-03-15"),
        ("15.03.26",    "2026-03-15"),
    ])
    def test_date_normalization(self, date_input, expected):
        text = f"СЧЕТ-ФАКТУРА № 1 от {date_input} Продавец: ООО Тест Итого: 100,00"
        _, fields, _, _ = self._run(text)
        assert fields.get("document_date") == expected

    # ── Суммы ─────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("amount_str,expected", [
        ("158 400,00",   158400.0),
        ("158400.00",    158400.0),
        ("1 000 000,50", 1000000.5),
        ("100",          100.0),
    ])
    def test_amount_parsing(self, amount_str, expected):
        from app.services.extractor import EntityExtractor
        ext = EntityExtractor()
        result = ext._parse_amount(amount_str)
        assert result == expected

    # ── Пустой / нечитаемый документ ──────────────────────────────────────

    def test_empty_document(self):
        doc_type, conf = self.classifier.classify("")
        assert doc_type == DocumentType.UNKNOWN
        assert conf == 0.0

    def test_unrecognized_document(self):
        text = "Это произвольный текст без ключевых слов первичных документов"
        doc_type, conf = self.classifier.classify(text)
        assert doc_type == DocumentType.UNKNOWN
