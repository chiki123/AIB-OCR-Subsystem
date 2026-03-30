import re

# 1. Fix OCR Engine
with open('app/services/ocr_engine.py', 'r', encoding='utf-8') as f:
    data = f.read()
data = re.sub(r'show_log=[^,]+,?', '', data)
data = re.sub(r'det_db_score_mode=[^,]+,?', '', data)
with open('app/services/ocr_engine.py', 'w', encoding='utf-8') as f:
    f.write(data)

# 2. Fix Documents API
with open('app/api/v1/endpoints/documents.py', 'r', encoding='utf-8') as f:
    data = f.read()
if 'selectinload' not in data:
    data = data.replace('from sqlalchemy import select, func', 'from sqlalchemy import select, func\nfrom sqlalchemy.orm import selectinload')
    data = data.replace('select(Document)', 'select(Document).options(selectinload(Document.extracted_data))')
    with open('app/api/v1/endpoints/documents.py', 'w', encoding='utf-8') as f:
        f.write(data)

# 3. Fix Tasks API
with open('app/api/v1/endpoints/tasks.py', 'r', encoding='utf-8') as f:
    data = f.read()
if 'selectinload' not in data:
    data = data.replace('from sqlalchemy import select', 'from sqlalchemy import select\nfrom sqlalchemy.orm import selectinload')
    data = data.replace('select(Document)', 'select(Document).options(selectinload(Document.processing_logs))')
    with open('app/api/v1/endpoints/tasks.py', 'w', encoding='utf-8') as f:
        f.write(data)

print('✅ تم إصلاح جميع الأخطاء بنجاح تام!')
