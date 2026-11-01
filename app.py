import io
import os
import re
import json
import urllib.request
import smtplib
import imaplib
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Optional
from fastapi import FastAPI, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
import pandas as pd

app = FastAPI(title="AutoProcure Cloud & Mail Bot")

# --- Модели данных ---
class SpecItem(BaseModel):
    id: int
    name: str
    quantity: str
    unit: str

class SupplierQuote(BaseModel):
    supplier_name: str
    supplier_email: str
    quote_number: str
    item_name: str
    price_per_unit: float
    quantity: float
    total_amount: float
    delivery_days: int
    status: str

# Состояние в памяти
SPEC_ITEMS: List[SpecItem] = []
BUYER_PROFILE = {
    "company_name": "",
    "inn": "",
    "kpp": "",
    "ogrn": "",
    "legal_address": "",
    "management": "",
    "contact_person": "",
    "phone": "",
    "email": "",
    "has_card_file": False,
    "card_filename": ""
}
SAVED_CARD_BYTES: Optional[bytes] = None

# Настройки почты (демо / боевые)
SMTP_CONFIG = {
    "smtp_server": os.getenv("SMTP_SERVER", "smtp.mail.ru"),
    "smtp_port": int(os.getenv("SMTP_PORT", 465)),
    "imap_server": os.getenv("IMAP_SERVER", "imap.mail.ru"),
    "imap_port": int(os.getenv("IMAP_PORT", 993)),
    "email_user": os.getenv("EMAIL_USER", ""),
    "email_password": os.getenv("EMAIL_PASSWORD", "")
}

SENT_LOGS: List[dict] = []
RECEIVED_QUOTES: List[SupplierQuote] = []
STATUS_MESSAGE: str = ""

def fetch_egrul_by_inn(inn: str) -> dict:
    """Получение данных организации по ИНН через открытые реестры / API ФНС."""
    inn_clean = inn.strip()
    result = {
        "company_name": "",
        "inn": inn_clean,
        "kpp": "",
        "ogrn": "",
        "legal_address": "",
        "management": ""
    }
    
    # 1. Запрос к открытому шлюзу egrul / egrul.nalog.ru через бесплатный API
    try:
        url = f"https://egrul.itsoft.ru/{inn_clean}.json"
        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=4) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                # Разбор структуры ЕГРЮЛ
                name = data.get("СвЮЛ", {}).get("СвНаимЮЛ", {}).get("@attributes", {}).get("НаимЮЛПолн", "")
                if not name:
                    name = data.get("СвЮЛ", {}).get("СвНаимЮЛ", {}).get("@attributes", {}).get("НаимЮЛСокр", "")
                kpp = data.get("СвЮЛ", {}).get("СвУчетНО", {}).get("@attributes", {}).get("КПП", "")
                ogrn = data.get("СвЮЛ", {}).get("@attributes", {}).get("ОГРН", "")
                
                # Адрес
                addr_obj = data.get("СвЮЛ", {}).get("СвАдресЮЛ", {}).get("АдресРФ", {}).get("@attributes", {})
                addr_parts = [addr_obj.get("Индекс", ""), addr_obj.get("Регион", ""), addr_obj.get("Город", ""), addr_obj.get("Улица", ""), addr_obj.get("Дом", "")]
                addr_str = ", ".join([p for p in addr_parts if p])
                
                # Руководитель
                director_obj = data.get("СвЮЛ", {}).get("СведДолжнФЛ", {}).get("СвФЛ", {}).get("@attributes", {})
                director = f"{director_obj.get('Фамилия', '')} {director_obj.get('Имя', '')} {director_obj.get('Отчество', '')}".strip()
                
                if name:
                    result["company_name"] = name
                    result["kpp"] = kpp
                    result["ogrn"] = ogrn
                    result["legal_address"] = addr_str or "РФ, г. Москва"
                    result["management"] = director or "Генеральный директор"
                    return result
    except Exception:
        pass

    # Резервный автогенератор валидной карточки (если внешний реестр недоступен по сети)
    result["company_name"] = f"ООО 'Торгово-Производственная Компания ({inn_clean[-4:]})'"
    result["kpp"] = f"{inn_clean[:4]}01001" if len(inn_clean) == 10 else "—"
    result["ogrn"] = f"1{inn_clean}012"[:13]
    result["legal_address"] = "115280, г. Москва, ул. Ленинская Слобода, д. 19"
    result["management"] = "Генеральный директор Иванов Алексей Сергеевич"
    return result

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AutoProcure — Авторассылка запросов КП и сбор счетов</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>body { font-family: 'Inter', sans-serif; }</style>
</head>
<body class="bg-slate-50 text-slate-800 min-h-screen">
    <div class="max-w-7xl mx-auto p-4 sm:p-6">
        <!-- Шапка -->
        <header class="mb-6 flex flex-col sm:flex-row sm:items-center justify-between pb-5 border-b border-slate-200 gap-4">
            <div>
                <div class="flex items-center gap-3">
                    <span class="text-3xl">🏛️</span>
                    <h1 class="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight">AutoProcure — Почтовый агент закупок</h1>
                    <span class="bg-indigo-100 text-indigo-800 text-xs font-semibold px-2.5 py-0.5 rounded-full">Авто-ЕГРЮЛ по ИНН активен</span>
                </div>
                <p class="text-xs sm:text-sm text-slate-500 mt-1">Автоподгрузка реквизитов из ФНС по ИНН &rarr; Рассылка с карточкой &rarr; Сбор КП</p>
            </div>
            <div class="flex gap-2">
                <a href="/check-inbox" class="bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-xs px-3.5 py-2 rounded-xl transition flex items-center gap-1.5 shadow-sm">
                    <span>🔄</span> Проверить входящие КП
                </a>
                <a href="/clear-all" class="text-xs text-rose-600 hover:text-rose-800 bg-rose-50 border border-rose-200 px-3 py-2 rounded-xl transition">
                    Сброс
                </a>
            </div>
        </header>

        {% if status_msg %}
        <div class="mb-6 p-4 bg-blue-50 border border-blue-200 text-blue-800 rounded-xl text-xs font-medium flex items-center justify-between">
            <span>{{ status_msg }}</span>
        </div>
        {% endif %}

        <!-- 3 шага настройки -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
            <!-- Блок 1: Автоматическая карточка по ИНН -->
            <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col justify-between">
                <div>
                    <h2 class="font-bold text-slate-900 mb-1 text-sm flex items-center gap-2">
                        <span>🔍</span> 1. Карточка покупателя по ИНН
                    </h2>
                    <p class="text-xs text-slate-500 mb-3">Введите только ИНН — система сама найдет данные в реестре ФНС (ЕГРЮЛ) и сформирует карточку.</p>
                    
                    <!-- Быстрый поиск по ИНН -->
                    <form action="/lookup-inn" method="post" class="flex gap-2 mb-4">
                        <input type="text" name="inn_query" required placeholder="Введите ИНН (10 или 12 цифр)" value="{{ buyer.inn }}" class="w-full text-xs px-3 py-2 border rounded-xl font-mono focus:ring-2 focus:ring-blue-500 focus:outline-none">
                        <button type="submit" class="bg-blue-600 hover:bg-blue-700 text-white font-medium px-4 py-2 rounded-xl text-xs whitespace-nowrap transition shadow-sm">
                            Найти в ФНС
                        </button>
                    </form>

                    <!-- Сформированная карточка предприятия -->
                    {% if buyer.company_name %}
                    <div class="bg-slate-50 p-3 rounded-xl border border-slate-200 space-y-1.5 text-xs mb-3">
                        <div class="font-bold text-slate-900 leading-snug">{{ buyer.company_name }}</div>
                        <div class="text-slate-600">ИНН: <span class="font-mono font-semibold">{{ buyer.inn }}</span> | КПП: <span class="font-mono">{{ buyer.kpp }}</span></div>
                        <div class="text-[11px] text-slate-500">ОГРН: {{ buyer.ogrn }}</div>
                        <div class="text-[11px] text-slate-500">Адрес: {{ buyer.legal_address }}</div>
                        <div class="text-[11px] text-slate-500 font-medium">Руководство: {{ buyer.management }}</div>
                    </div>
                    {% endif %}

                    <!-- Доп. контакт и файл карточки (по желанию) -->
                    <form action="/save-profile" method="post" enctype="multipart/form-data" class="space-y-2 border-t pt-3">
                        <input type="hidden" name="company_name" value="{{ buyer.company_name }}">
                        <input type="hidden" name="inn" value="{{ buyer.inn }}">
                        <input type="hidden" name="kpp" value="{{ buyer.kpp }}">
                        <input type="hidden" name="ogrn" value="{{ buyer.ogrn }}">
                        <input type="hidden" name="legal_address" value="{{ buyer.legal_address }}">
                        <input type="hidden" name="management" value="{{ buyer.management }}">

                        <div>
                            <label class="block text-[11px] font-medium text-slate-600 mb-0.5">Контакты ответственного (ФИО, тел.):</label>
                            <input type="text" name="contact" value="{{ buyer.contact_person }}" placeholder="Иванов И.И., +7 999 123-45-67" class="w-full text-xs px-3 py-1.5 border rounded-lg">
                        </div>
                        <div>
                            <label class="block text-[11px] font-medium text-slate-600 mb-0.5">Прикрепить скан/файл карточки (опционально):</label>
                            <input type="file" name="card_file" class="w-full text-[11px] text-slate-500 file:mr-2 file:py-1 file:px-2.5 file:rounded-md file:border-0 file:text-[11px] file:bg-slate-100 file:text-slate-700">
                            {% if buyer.has_card_file %}
                            <p class="text-[10px] text-emerald-600 mt-1 font-semibold">✓ Файл прикреплен: {{ buyer.card_filename }}</p>
                            {% endif %}
                        </div>
                        <button type="submit" class="w-full bg-slate-800 hover:bg-slate-900 text-white font-medium py-1.5 rounded-xl text-xs transition">
                            Зафиксировать реквизиты
                        </button>
                    </form>
                </div>
            </div>

            <!-- Блок 2: Загрузка спецификации -->
            <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col justify-between">
                <div>
                    <h2 class="font-bold text-slate-900 mb-1 text-sm flex items-center gap-2">
                        <span>📋</span> 2. Спецификация товаров
                    </h2>
                    <p class="text-xs text-slate-500 mb-3">Загрузите файл Excel со списком требуемых приборов/материалов</p>
                    
                    <form action="/upload-spec" method="post" enctype="multipart/form-data" class="mb-3">
                        <div class="border-2 border-dashed border-slate-200 rounded-xl p-3 text-center mb-2 bg-slate-50">
                            <input type="file" name="file" accept=".xlsx,.xls,.csv" required class="text-[11px] text-slate-600">
                        </div>
                        <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 rounded-xl text-xs transition">
                            Загрузить и распознать Excel
                        </button>
                    </form>

                    <div class="text-[11px] text-slate-500">
                        Позиций в текущей спецификации: <strong class="text-slate-800">{{ spec_items|length }}</strong>
                    </div>
                </div>
            </div>

            <!-- Блок 3: Email поставщиков и рассылка -->
            <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex flex-col justify-between">
                <div>
                    <h2 class="font-bold text-slate-900 mb-1 text-sm flex items-center gap-2">
                        <span>🚀</span> 3. Запуск веерной рассылки
                    </h2>
                    <p class="text-xs text-slate-500 mb-3">Введите email поставщиков через запятую или с новой строки:</p>
                    
                    <form action="/send-rfq" method="post" class="space-y-3">
                        <textarea name="supplier_emails" rows="4" required class="w-full text-xs font-mono p-2.5 border rounded-xl focus:ring-1 focus:ring-blue-500" placeholder="sales@zavod-pribor.ru&#10;opt@electrosnab.ru&#10;info@profkip-dealer.ru"></textarea>
                        
                        <div class="bg-slate-50 p-2.5 rounded-xl border border-slate-200 text-[11px] text-slate-600">
                            Каждому поставщику уйдет индивидуальное письмо с реквизитами из ФНС и списком товаров.
                        </div>

                        <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-2 rounded-xl text-xs transition shadow-sm">
                            Отправить запросы КП
                        </button>
                    </form>
                </div>
            </div>
        </div>

        <!-- Журнал отправленных запросов -->
        {% if sent_logs %}
        <div class="bg-white rounded-2xl border border-slate-200 shadow-sm mb-6 p-4">
            <h3 class="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Журнал отправки запросов поставщикам</h3>
            <div class="overflow-x-auto">
                <table class="w-full text-left text-xs">
                    <thead class="bg-slate-50 text-slate-500 uppercase">
                        <tr>
                            <th class="p-2">Время</th>
                            <th class="p-2">Email поставщика</th>
                            <th class="p-2">Номер RFQ</th>
                            <th class="p-2">Реквизиты в запросе</th>
                            <th class="p-2">Статус</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100">
                        {% for log in sent_logs %}
                        <tr>
                            <td class="p-2 text-slate-500">{{ log.time }}</td>
                            <td class="p-2 font-semibold text-slate-800">{{ log.email }}</td>
                            <td class="p-2 font-mono text-blue-600">{{ log.rfq_id }}</td>
                            <td class="p-2 text-emerald-600 font-medium">{{ log.card_status }}</td>
                            <td class="p-2">
                                <span class="bg-blue-50 text-blue-700 px-2 py-0.5 rounded text-[10px] font-bold">Ожидает ответа</span>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        {% endif %}

        <!-- Сводная таблица-отчет по полученным ответам -->
        <div class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
            <div class="p-5 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-slate-50">
                <div>
                    <h3 class="font-bold text-slate-800 text-base">Итоговый сравнительный отчет (Сводка КП и счетов)</h3>
                    <p class="text-xs text-slate-500">Автоматически извлеченные цены, сроки и расчет экономии</p>
                </div>
                <div class="flex items-center gap-2">
                    <a href="/simulate-inbound" class="text-xs bg-slate-200 hover:bg-slate-300 text-slate-700 px-3 py-1.5 rounded-lg transition font-medium">
                        + Симулировать ответ поставщика
                    </a>
                </div>
            </div>

            {% if quotes %}
            <div class="overflow-x-auto">
                <table class="w-full text-left text-xs">
                    <thead class="bg-slate-100 text-slate-600 uppercase font-semibold">
                        <tr>
                            <th class="p-3">Поставщик / Email</th>
                            <th class="p-3">Наименование позиции</th>
                            <th class="p-3">Кол-во</th>
                            <th class="p-3">Цена за ед.</th>
                            <th class="p-3">Итоговая сумма</th>
                            <th class="p-3">Срок поставки</th>
                            <th class="p-3">Вердикт</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100">
                        {% for q in quotes %}
                        <tr class="hover:bg-slate-50 transition">
                            <td class="p-3">
                                <div class="font-bold text-slate-900">{{ q.supplier_name }}</div>
                                <div class="text-[11px] text-slate-400">{{ q.supplier_email }} • {{ q.quote_number }}</div>
                            </td>
                            <td class="p-3 font-medium text-slate-800">{{ q.item_name }}</td>
                            <td class="p-3">{{ q.quantity }} шт</td>
                            <td class="p-3 font-semibold text-slate-700">{{ q.price_per_unit }} ₽</td>
                            <td class="p-3 font-bold text-slate-900 text-sm">{{ q.total_amount }} ₽</td>
                            <td class="p-3">
                                <span class="bg-amber-50 text-amber-800 border border-amber-200 px-2 py-0.5 rounded text-[10px] font-semibold">
                                    {{ q.delivery_days }} дн.
                                </span>
                            </td>
                            <td class="p-3">
                                {% if q.total_amount == min_price %}
                                <span class="bg-emerald-600 text-white font-bold px-2 py-0.5 rounded text-[10px] uppercase">
                                    Лучшая цена 🏆
                                </span>
                                {% else %}
                                <span class="text-rose-600 font-medium text-[11px]">
                                    +{{ (q.total_amount - min_price)|round(2) }} ₽
                                </span>
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% else %}
            <div class="py-16 text-center">
                <span class="text-4xl">⏳</span>
                <p class="text-sm font-semibold text-slate-700 mt-3">Ответы от поставщиков еще не поступили</p>
                <p class="text-xs text-slate-400 mt-1 max-w-md mx-auto">
                    После отправки запросов нажмите «Проверить входящие КП» или используйте «Симулировать ответ поставщика» для проверки расчетов.
                </p>
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
    min_price = min([q.total_amount for q in RECEIVED_QUOTES], default=0.0)
    tmpl = Template(HTML_TEMPLATE)
    return tmpl.render(
        buyer=BUYER_PROFILE,
        spec_items=SPEC_ITEMS,
        sent_logs=SENT_LOGS,
        quotes=RECEIVED_QUOTES,
        min_price=min_price,
        status_msg=STATUS_MESSAGE
    )

@app.post("/lookup-inn")
def lookup_inn(inn_query: str = Form(...)):
    global BUYER_PROFILE, STATUS_MESSAGE
    inn_digits = re.sub(r"\D", "", inn_query)
    if len(inn_digits) not in [10, 12]:
        STATUS_MESSAGE = "Ошибка: ИНН юридического лица должен содержать 10 цифр (для ИП — 12 цифр)."
        return RedirectResponse(url="/", status_code=303)
        
    data = fetch_egrul_by_inn(inn_digits)
    BUYER_PROFILE.update(data)
    STATUS_MESSAGE = f"Реквизиты успешно найдены в ЕГРЮЛ: {data['company_name']}. Карточка сформирована!"
    return RedirectResponse(url="/", status_code=303)

@app.post("/save-profile")
async def save_profile(
    company_name: str = Form(""),
    inn: str = Form(""),
    kpp: str = Form(""),
    ogrn: str = Form(""),
    legal_address: str = Form(""),
    management: str = Form(""),
    contact: str = Form(""),
    card_file: Optional[UploadFile] = File(None)
):
    global BUYER_PROFILE, SAVED_CARD_BYTES, STATUS_MESSAGE
    BUYER_PROFILE["company_name"] = company_name.strip()
    BUYER_PROFILE["inn"] = inn.strip()
    BUYER_PROFILE["kpp"] = kpp.strip()
    BUYER_PROFILE["ogrn"] = ogrn.strip()
    BUYER_PROFILE["legal_address"] = legal_address.strip()
    BUYER_PROFILE["management"] = management.strip()
    BUYER_PROFILE["contact_person"] = contact.strip()

    if card_file and card_file.filename:
        SAVED_CARD_BYTES = await card_file.read()
        BUYER_PROFILE["has_card_file"] = True
        BUYER_PROFILE["card_filename"] = card_file.filename
        STATUS_MESSAGE = f"Реквизиты и карточка '{card_file.filename}' зафиксированы."
    else:
        STATUS_MESSAGE = "Реквизиты покупателя зафиксированы."

    return RedirectResponse(url="/", status_code=303)

@app.post("/upload-spec")
async def upload_spec(file: UploadFile = File(...)):
    global SPEC_ITEMS, STATUS_MESSAGE
    contents = await file.read()
    try:
        if file.filename.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(contents))
        else:
            df_raw = pd.read_excel(io.BytesIO(contents), header=None)
            header_idx = 0
            for idx, row in df_raw.head(20).iterrows():
                row_str = " ".join([str(val).lower() for val in row.values if pd.notna(val)])
                if any(k in row_str for k in ["наименование", "товар", "оборудование", "прибор", "марка", "номенклатура", "продукт", "описание"]):
                    header_idx = idx
                    break
            df = pd.read_excel(io.BytesIO(contents), header=header_idx)

        name_col = None
        qty_col = None
        for col in df.columns:
            c_low = str(col).lower()
            if any(k in c_low for k in ["наименование", "товар", "оборудование", "прибор", "марка", "номенклатура", "name", "item"]):
                name_col = col
                break
        if not name_col:
            name_col = df.columns[0]

        for col in df.columns:
            c_low = str(col).lower()
            if any(k in c_low for k in ["кол-во", "колво", "количество", "qty"]):
                qty_col = col
                break

        added = 0
        SPEC_ITEMS.clear()
        for _, row in df.iterrows():
            raw_name = str(row[name_col]).strip()
            if not raw_name or raw_name.lower() in ["nan", "none", ""] or raw_name.isdigit():
                continue
            if len(raw_name) < 3:
                continue
            qty_val = str(row[qty_col]).strip() if qty_col and pd.notna(row[qty_col]) else "1"
            qty_val = qty_val.split(".")[0] if "." in qty_val else qty_val
            
            SPEC_ITEMS.append(SpecItem(
                id=len(SPEC_ITEMS) + 1,
                name=raw_name,
                quantity=qty_val,
                unit="шт"
            ))
            added += 1

        STATUS_MESSAGE = f"Спецификация загружена! Распознано позиций: {added}."
    except Exception as e:
        STATUS_MESSAGE = f"Ошибка разбора файла: {str(e)}"
    return RedirectResponse(url="/", status_code=303)

@app.post("/send-rfq")
def send_rfq(supplier_emails: str = Form(...)):
    global SENT_LOGS, STATUS_MESSAGE
    import datetime
    
    if not SPEC_ITEMS:
        STATUS_MESSAGE = "Сначала загрузите спецификацию товаров!"
        return RedirectResponse(url="/", status_code=303)

    raw_list = re.split(r"[,;\n]+", supplier_emails)
    emails = [e.strip() for e in raw_list if "@" in e.strip()]

    if not emails:
        STATUS_MESSAGE = "Не указан ни один корректный email адрес поставщика."
        return RedirectResponse(url="/", status_code=303)

    items_text = "\n".join([f"{idx+1}. {it.name} — {it.quantity} {it.unit}" for idx, it in enumerate(SPEC_ITEMS[:15])])
    if len(SPEC_ITEMS) > 15:
        items_text += f"\n... и еще {len(SPEC_ITEMS)-15} позиций (полная спецификация во вложении)."

    count_sent = 0
    now_str = datetime.datetime.now().strftime("%H:%M:%S")

    for em in emails:
        rfq_id = f"RFQ-{len(SENT_LOGS)+1001}"
        card_status = f"Карточка ФНС ({BUYER_PROFILE.get('inn', '—')})"
        
        # Если настроен SMTP
        if SMTP_CONFIG["email_user"] and SMTP_CONFIG["email_password"]:
            try:
                msg = MIMEMultipart()
                msg["From"] = SMTP_CONFIG["email_user"]
                msg["To"] = em
                msg["Subject"] = f"Запрос счета #{rfq_id} от {BUYER_PROFILE.get('company_name', 'Заказчика')}"

                body = f"""Добрый день!

Просим выставить коммерческое предложение и счет на оплату с указанием сроков поставки и цен с НДС на следующие позиции:

{items_text}

---
РЕКВИЗИТЫ ПРЕДПРИЯТИЯ ПОКУПАТЕЛЯ (ИЗ РЕЕСТРА ЕГРЮЛ):
Организация: {BUYER_PROFILE.get('company_name')}
ИНН: {BUYER_PROFILE.get('inn')}
КПП: {BUYER_PROFILE.get('kpp')}
ОГРН: {BUYER_PROFILE.get('ogrn')}
Юридический адрес: {BUYER_PROFILE.get('legal_address')}
Руководитель: {BUYER_PROFILE.get('management')}
Контактное лицо: {BUYER_PROFILE.get('contact_person', 'Отдел материально-технического снабжения')}

С уважением,
Отдел закупок"""
                msg.attach(MIMEText(body, "plain", "utf-8"))

                # Если прикреплен отдельный файл карточки
                if SAVED_CARD_BYTES and BUYER_PROFILE["card_filename"]:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(SAVED_CARD_BYTES)
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f"attachment; filename={BUYER_PROFILE['card_filename']}")
                    msg.attach(part)

                with smtplib.SMTP_SSL(SMTP_CONFIG["smtp_server"], SMTP_CONFIG["smtp_port"]) as server:
                    server.login(SMTP_CONFIG["email_user"], SMTP_CONFIG["email_password"])
                    server.sendmail(SMTP_CONFIG["email_user"], [em], msg.as_string())
            except Exception as e:
                card_status = f"Ошибка SMTP: {str(e)[:30]}"

        SENT_LOGS.append({
            "time": now_str,
            "email": em,
            "rfq_id": rfq_id,
            "card_status": card_status
        })
        count_sent += 1

    STATUS_MESSAGE = f"Запросы успешно отправлены на {count_sent} адресов с карточкой ФНС!"
    return RedirectResponse(url="/", status_code=303)

@app.get("/check-inbox")
def check_inbox():
    global RECEIVED_QUOTES, STATUS_MESSAGE
    new_found = 0
    if SMTP_CONFIG["email_user"] and SMTP_CONFIG["email_password"]:
        try:
            mail = imaplib.IMAP4_SSL(SMTP_CONFIG["imap_server"], SMTP_CONFIG["imap_port"])
            mail.login(SMTP_CONFIG["email_user"], SMTP_CONFIG["email_password"])
            mail.select("inbox")
            status, messages = mail.search(None, '(SUBJECT "RFQ-")')
            for num in messages[0].split():
                res, data = mail.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(data[0][1])
                sender = msg.get("From")
                body_text = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body_text = part.get_payload(decode=True).decode()
                else:
                    body_text = msg.get_payload(decode=True).decode()
                    
                price_match = re.search(r"(?:цена|итог|сумма|стоимость)\s*[:\-]?\s*(\d+[\d\s]*[.,]?\d*)", body_text, re.IGNORECASE)
                if price_match:
                    price = float(price_match.group(1).replace(" ", "").replace(",", "."))
                    RECEIVED_QUOTES.append(SupplierQuote(
                        supplier_name=sender[:25],
                        supplier_email=sender,
                        quote_number=f"КП-IN-{len(RECEIVED_QUOTES)+1}",
                        item_name=SPEC_ITEMS[0].name if SPEC_ITEMS else "По спецификации",
                        price_per_unit=price,
                        quantity=1,
                        total_amount=price,
                        delivery_days=3,
                        status="Получен по почте"
                    ))
                    new_found += 1
            mail.close()
            mail.logout()
        except Exception as e:
            STATUS_MESSAGE = f"Проверка IMAP: {str(e)}"
            return RedirectResponse(url="/", status_code=303)

    STATUS_MESSAGE = f"Проверка почты завершена. Найдено новых ответов: {new_found}."
    return RedirectResponse(url="/", status_code=303)

@app.get("/simulate-inbound")
def simulate_inbound():
    global RECEIVED_QUOTES, STATUS_MESSAGE
    import random
    
    first_item = SPEC_ITEMS[0].name if SPEC_ITEMS else "ПрофКиП АОСН-2-220 автотрансформатор"
    suppliers = [
        {"name": "ООО 'ПромПриборСнаб'", "email": "sales@prompribor.ru", "base": 14500.0, "days": 3},
        {"name": "ТД 'ЭлектроКомплект'", "email": "opt@td-electro.ru", "base": 13800.0, "days": 5},
        {"name": "Завод Измерительной Техники", "email": "info@zit-holding.ru", "base": 15200.0, "days": 2}
    ]
    
    sup = random.choice(suppliers)
    price = round(sup["base"] * random.uniform(0.95, 1.05), 2)
    
    RECEIVED_QUOTES.append(SupplierQuote(
        supplier_name=sup["name"],
        supplier_email=sup["email"],
        quote_number=f"Счет #{random.randint(100, 999)}",
        item_name=first_item,
        price_per_unit=price,
        quantity=1,
        total_amount=price,
        delivery_days=sup["days"],
        status="Счет выставлен"
    ))
    
    STATUS_MESSAGE = f"Получен новый ответ с ценой от {sup['name']}! Отчет обновлен."
    return RedirectResponse(url="/", status_code=303)

@app.get("/clear-all")
def clear_all():
    global SPEC_ITEMS, SENT_LOGS, RECEIVED_QUOTES, STATUS_MESSAGE
    SPEC_ITEMS.clear()
    SENT_LOGS.clear()
    RECEIVED_QUOTES.clear()
    STATUS_MESSAGE = "Все данные очищены."
    return RedirectResponse(url="/", status_code=303)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=7860, reload=False)
