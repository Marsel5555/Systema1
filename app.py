import io
import re
import urllib.parse
from typing import List
from fastapi import FastAPI, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
import pandas as pd

app = FastAPI(title="AutoProcure Cloud Spec Scanner")

class SpecItem(BaseModel):
    id: int
    name: str
    quantity: str
    unit: str
    search_queries: List[dict]

SPEC_ITEMS: List[SpecItem] = []
STATUS_MESSAGE: str = ""

def build_supplier_links(item_name: str) -> List[dict]:
    query_clean = re.sub(r"[^a-zA-Zа-яА-Я0-9\s\-\./]", " ", item_name).strip()
    query_clean = re.sub(r"\s+", " ", query_clean)
    encoded = urllib.parse.quote(query_clean)
    return [
        {
            "channel": "Supl.biz (Оптовые базы)",
            "title": f"Поставщики: {query_clean[:35]}...",
            "url": f"https://supl.biz/search/?q={encoded}",
            "badge": "B2B Платформа"
        },
        {
            "channel": "Пульс Цен (Прайс-листы)",
            "title": "Каталог заводов и дилеров",
            "url": f"https://pulscen.ru/search/price?q={encoded}",
            "badge": "Складские прайсы"
        },
        {
            "channel": "Яндекс Поиск (Опт и склады)",
            "title": "Купить оптом у поставщика",
            "url": f"https://yandex.ru/search/?text={encoded}+купить+оптом+производитель+склад",
            "badge": "Прямой поиск"
        }
    ]

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AutoProcure Cloud — Автопоиск поставщиков по спецификации</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>body { font-family: 'Inter', sans-serif; }</style>
</head>
<body class="bg-slate-50 text-slate-800 min-h-screen">
    <div class="max-w-6xl mx-auto p-6">
        <header class="mb-8 flex flex-col md:flex-row md:items-center justify-between pb-5 border-b border-slate-200 gap-4">
            <div>
                <div class="flex items-center gap-3">
                    <span class="text-3xl">🚀</span>
                    <h1 class="text-2xl font-bold text-slate-900 tracking-tight">AutoProcure Cloud MVP</h1>
                    <span class="bg-emerald-100 text-emerald-800 text-xs font-semibold px-2.5 py-0.5 rounded-full">Универсальный парсер активен</span>
                </div>
                <p class="text-sm text-slate-500 mt-1">Загрузка спецификации &rarr; Умное распознавание номенклатуры &rarr; Автопоиск поставщиков</p>
            </div>
            {% if spec_items %}
            <a href="/clear" class="text-xs text-rose-600 hover:text-rose-800 bg-rose-50 border border-rose-200 px-3 py-1.5 rounded-lg transition self-start">
                Очистить спецификацию
            </a>
            {% endif %}
        </header>

        {% if status_msg %}
        <div class="mb-6 p-4 bg-blue-50 border border-blue-200 text-blue-800 rounded-xl text-xs font-medium">
            {{ status_msg }}
        </div>
        {% endif %}

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
            <div class="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm flex flex-col justify-between">
                <div>
                    <h2 class="font-bold text-slate-900 mb-1 flex items-center gap-2">
                        <span>📊</span> Загрузить файл спецификации
                    </h2>
                    <p class="text-xs text-slate-500 mb-4">Поддерживаются любые файлы <code>.xlsx</code>, <code>.xls</code>, <code>.csv</code>. Сервис автоматически пропустит шапку и найдет колонки с товаром и количеством.</p>
                    
                    <form action="/upload-file" method="post" enctype="multipart/form-data">
                        <div class="border-2 border-dashed border-slate-200 rounded-xl p-6 text-center hover:border-blue-400 transition mb-4 bg-slate-50">
                            <input type="file" name="file" accept=".xlsx,.xls,.csv" required class="text-xs text-slate-600 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100">
                        </div>
                        <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2.5 rounded-xl text-xs transition">
                            Распознать файл и найти поставщиков
                        </button>
                    </form>
                </div>
            </div>

            <div class="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm flex flex-col justify-between">
                <div>
                    <h2 class="font-bold text-slate-900 mb-1 flex items-center gap-2">
                        <span>📝</span> Или вставить текстом
                    </h2>
                    <p class="text-xs text-slate-500 mb-4">Формат: одна строка на позицию или <code>Товар | Кол-во | Ед</code>:</p>
                    
                    <form action="/upload-text" method="post">
                        <textarea name="raw_text" rows="4" class="w-full text-xs font-mono p-3 border border-slate-300 rounded-xl mb-3 focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="Кабель ВВГнг-LS 3х2.5 | 150 | м&#10;Автоматический выключатель 16А ВА47-29 | 20 | шт&#10;Труба ПНД 25мм техническая | 100 | м"></textarea>
                        
                        <button type="submit" class="w-full bg-slate-900 hover:bg-black text-white font-medium py-2.5 rounded-xl text-xs transition">
                            Обработать список
                        </button>
                    </form>
                </div>
            </div>
        </div>

        <div class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
            <div class="p-5 border-b border-slate-100 flex justify-between items-center bg-slate-50">
                <div>
                    <h3 class="font-bold text-slate-800 text-base">Матрица поиска поставщиков по номенклатуре</h3>
                    <p class="text-xs text-slate-500">Прямые ссылки в B2B-реестры и складские каталоги</p>
                </div>
                {% if spec_items %}
                <span class="bg-blue-100 text-blue-800 text-xs font-bold px-3 py-1 rounded-lg">
                    Позиций в обработке: {{ spec_items|length }}
                </span>
                {% endif %}
            </div>

            {% if spec_items %}
            <div class="divide-y divide-slate-100">
                {% for item in spec_items %}
                <div class="p-5 hover:bg-slate-50 transition">
                    <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-3">
                        <div class="flex items-start gap-3">
                            <span class="bg-slate-200 text-slate-700 font-bold text-xs px-2.5 py-1 rounded-md">#{{ item.id }}</span>
                            <div>
                                <h4 class="font-semibold text-slate-900 text-sm">{{ item.name }}</h4>
                                <div class="text-xs text-slate-500 mt-0.5">
                                    Объем закупки: <span class="font-medium text-slate-800">{{ item.quantity }} {{ item.unit }}</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-3">
                        {% for q in item.search_queries %}
                        <a href="{{ q.url }}" target="_blank" class="p-3 bg-white border border-slate-200 rounded-xl hover:border-blue-500 hover:shadow-sm transition flex flex-col justify-between group">
                            <div>
                                <span class="text-[10px] font-bold uppercase tracking-wider text-slate-500 bg-slate-100 px-2 py-0.5 rounded">{{ q.badge }}</span>
                                <p class="text-xs font-medium text-slate-800 mt-2 group-hover:text-blue-600 transition">{{ q.channel }}</p>
                            </div>
                            <span class="text-[11px] text-blue-600 mt-2 inline-flex items-center gap-1 font-medium">
                                Открыть базу &rarr;
                            </span>
                        </a>
                        {% endfor %}
                    </div>
                </div>
                {% endfor %}
            </div>
            {% else %}
            <div class="py-16 text-center">
                <span class="text-4xl">📋</span>
                <p class="text-sm font-semibold text-slate-700 mt-3">Спецификация еще не загружена</p>
                <p class="text-xs text-slate-400 mt-1 max-w-sm mx-auto">Загрузите файл Excel со спецификацией или вставьте список номенклатуры выше.</p>
            </div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    from jinja2 import Template
    tmpl = Template(HTML_TEMPLATE)
    return tmpl.render(
        spec_items=SPEC_ITEMS,
        status_msg=STATUS_MESSAGE
    )

@app.post("/upload-file")
async def upload_file(file: UploadFile = File(...)):
    global STATUS_MESSAGE
    contents = await file.read()
    filename = file.filename.lower()
    
    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(contents))
        else:
            # Читаем сначала «сырой» файл без заголовков, чтобы просканировать шапку
            df_raw = pd.read_excel(io.BytesIO(contents), header=None)
            
            # 1. Поиск реальной строки заголовков (ищем ключевые слова шапки)
            header_idx = 0
            for idx, row in df_raw.head(20).iterrows():
                row_str = " ".join([str(val).lower() for val in row.values if pd.notna(val)])
                if any(k in row_str for k in ["наименование", "товар", "оборудование", "прибор", "марка", "номенклатура", "продукт", "описание", "тип"]):
                    header_idx = idx
                    break
            
            # Перечитываем файл, начиная с найденной строки заголовков
            df = pd.read_excel(io.BytesIO(contents), header=header_idx)

        # 2. Интеллектуальный поиск колонки с названием товара
        name_col = None
        qty_col = None
        unit_col = None
        
        for col in df.columns:
            c_low = str(col).lower()
            if any(k in c_low for k in ["наименование", "товар", "оборудование", "прибор", "марка", "номенклатура", "модель", "item", "name"]):
                name_col = col
                break
        
        # Если явного заголовка нет — выбираем столбец с наибольшей средней длиной текста
        if not name_col:
            text_lens = {}
            for col in df.columns:
                avg_len = df[col].astype(str).str.len().mean()
                text_lens[col] = avg_len
            name_col = max(text_lens, key=text_lens.get)
            
        for col in df.columns:
            c_low = str(col).lower()
            if any(k in c_low for k in ["кол-во", "колво", "количество", "qty", "объем"]):
                qty_col = col
                break

        for col in df.columns:
            c_low = str(col).lower()
            if any(k in c_low for k in ["ед.", "ед. изм", "единица", "измерения", "unit"]):
                unit_col = col
                break

        # 3. Извлечение позиций и фильтрация служебных строк
        added_count = 0
        for _, row in df.iterrows():
            raw_name = str(row[name_col]).strip()
            
            # Пропускаем пустые ячейки, NaN, технические разделители и чисто числа
            if not raw_name or raw_name.lower() in ["nan", "none", "", "null"] or raw_name.isdigit():
                continue
            if len(raw_name) < 3:
                continue
            # Игнорируем повтор шапки или заголовки разделов
            if raw_name.lower() in ["наименование", "наименование товара", "номенклатура", "итого"]:
                continue
                
            qty_val = str(row[qty_col]).strip() if qty_col and pd.notna(row[qty_col]) else "1"
            qty_val = qty_val.split(".")[0] if "." in qty_val and qty_val.split(".")[1] == "0" else qty_val
            if qty_val.lower() == "nan" or not qty_val:
                qty_val = "1"
                
            unit_val = str(row[unit_col]).strip() if unit_col and pd.notna(row[unit_col]) else "шт"
            if unit_val.lower() == "nan" or not unit_val:
                unit_val = "шт"
            
            SPEC_ITEMS.append(SpecItem(
                id=len(SPEC_ITEMS) + 1,
                name=raw_name,
                quantity=qty_val,
                unit=unit_val,
                search_queries=build_supplier_links(raw_name)
            ))
            added_count += 1
            
        STATUS_MESSAGE = f"Файл {file.filename} успешно обработан! Распознано и добавлено позиций: {added_count}."
    except Exception as e:
        STATUS_MESSAGE = f"Ошибка обработки файла: {str(e)}"
        
    return RedirectResponse(url="/", status_code=303)

@app.post("/upload-text")
def upload_text(raw_text: str = Form(...)):
    global STATUS_MESSAGE
    lines = raw_text.strip().split("
")
    added = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            name = parts[0]
            qty = parts[1] if len(parts) > 1 else "1"
            unit = parts[2] if len(parts) > 2 else "шт"
        else:
            name = line
            qty = "1"
            unit = "шт"
            
        SPEC_ITEMS.append(SpecItem(
            id=len(SPEC_ITEMS) + 1,
            name=name,
            quantity=qty,
            unit=unit,
            search_queries=build_supplier_links(name)
        ))
        added += 1
        
    STATUS_MESSAGE = f"Успешно добавлено {added} позиций из текста."
    return RedirectResponse(url="/", status_code=303)

@app.get("/clear")
def clear_spec():
    global STATUS_MESSAGE
    SPEC_ITEMS.clear()
    STATUS_MESSAGE = "Спецификация очищена."
    return RedirectResponse(url="/", status_code=303)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=7860, reload=False)
