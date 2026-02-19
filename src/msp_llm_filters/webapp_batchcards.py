from typing import Any, Dict
import os
import json

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.requests import Request
from starlette.routing import Route

import httpx

from .nl_converter_batchcards import convert_nl_to_batchcards
from .llm_client_batchcards import nl_to_batchcards_via_ollama
from .server_batchcards import Settings, BatchCardsRequest, api_search_batchcards

HTML_INDEX = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BatchCards — NL Search</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    form { margin-bottom: 20px; }
    input[type=text] { width: 80%; padding: 10px; font-size: 16px; }
    button { padding: 10px 16px; font-size: 16px; }
    .meta { color: #666; font-size: 14px; margin-bottom: 8px; }
    .item { border: 1px solid #ddd; padding: 12px; border-radius: 6px; margin-bottom: 10px; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(240px, 1fr)); gap: 8px 16px; }
    @media (max-width: 800px) { .grid { grid-template-columns: 1fr; } input[type=text]{ width: 100%; } }
    code { background: #f6f8fa; padding: 2px 4px; border-radius: 4px; }
  </style>
</head>
<body>
<h1>BatchCards — поиск контрагентов по естественному языку</h1>
<form method="post" action="/search">
  <div>
    <input type="text" name="q" placeholder="Например: 200 компаний в регионе 77, выручка от 1 000 до 5 000, только действующие" required>
  </div>
  <div>
    <label><input type="checkbox" name="use_llm"> Использовать локальную LLM (Ollama)</label>
  </div>
  <button type="submit">Искать</button>
</form>
<p class="meta">API: <code>{api_url}</code></p>
</body>
</html>
"""


def _render_results_page(api_url: str, q: str, parsed: Dict[str, Any], res: Dict[str, Any], parser_used: str, use_llm_checked: bool) -> str:
    items = res.get("items", [])
    total = res.get("total")
    page = res.get("page")
    page_size = res.get("page_size")
    rows = []
    for it in items:
        # Поддержка вложенной структуры по примеру ответа (main_block, address_block, ...)
        mb = it.get("main_block") or {}
        ab = it.get("address_block") or {}
        mp = it.get("msp_block") or {}
        fp = (it.get("finance_plain_block") or {})
        fin_rows = fp.get("fin_data") or []

        # Вычисляем выручку по коду 2110, если есть
        latest_income = None
        try:
            for rec in fin_rows:
                if str(rec.get("code")) == "2110":
                    sums = rec.get("sum_by_year_map") or {}
                    if isinstance(sums, dict) and sums:
                        latest_income = sums.get(sorted(sums.keys())[-1])
                    break
        except Exception:
            latest_income = None

        # Основные атрибуты
        name = mb.get("name") or mb.get("full_name") or it.get("name") or it.get("full_name") or it.get("ogrn") or "Запись"
        inn = mb.get("inn") or it.get("inn")
        ogrn = mb.get("ogrn") or it.get("ogrn")
        okved = mb.get("activity_kind") or it.get("activity_kind") or it.get("okved") or it.get("okved_main")
        okved_dsc = mb.get("activity_kind_dsc")
        status = (mb.get("status") or {}).get("status_rus_short") or (mb.get("status") or {}).get("status_egr")
        est_date = mb.get("establishment_date")

        # Топовые поля: manager, income, net_income (если приходят)
        manager = it.get("manager")
        if not manager:
            mm = (it.get("managers_block", {}) or {}).get("managers") or []
            if mm:
                manager = mm[0].get("name")
        income_top = it.get("income")
        net_income_top = it.get("net_income")

        region = ab.get("region") or ab.get("region_code") or it.get("region") or it.get("region_code")
        addr = ab.get("value")

        emails_list = [e.get("value") for e in (it.get("contacts_block", {}).get("emails") or []) if e.get("value")]
        phones_list = [p.get("value") for p in (it.get("contacts_block", {}).get("phones") or []) if p.get("value")]
        websites_list = [w.get("value") for w in (it.get("contacts_block", {}).get("websites") or []) if w.get("value")]

        msp = mp.get("msp")
        msp_cat = mp.get("category") or mp.get("category_name")

        # Собираем только непустые поля
        grid = []
        def add(label: str, value: Any, full_row: bool = False):
            if value is None:
                return
            if isinstance(value, str) and value.strip() == "":
                return
            style = " style=\"grid-column:1/-1\"" if full_row else ""
            grid.append(f"<div{style}><b>{label}:</b> {value}</div>")

        add("ИНН", inn)
        add("ОГРН", ogrn)
        add("Статус", status)
        add("Дата регистрации", est_date)
        add("Регион", region)
        add("Адрес", addr, full_row=True)
        add("ОКВЭД", okved)
        add("Описание ОКВЭД", okved_dsc)
        add("Менеджер/руководитель", manager)
        add("Выручка (поле income)", income_top)
        add("Чистая прибыль (поле net_income)", net_income_top)
        add("Выручка (посл. год, код 2110)", latest_income)
        if msp and msp_cat:
            add("МСП", f"{msp} ({msp_cat})")
        elif msp:
            add("МСП", msp)
        if emails_list:
            add("Почты", ", ".join(emails_list), full_row=True)
        if phones_list:
            add("Телефоны", ", ".join(phones_list), full_row=True)
        if websites_list:
            add("Сайты", ", ".join(websites_list), full_row=True)

        grid_html = "\n".join(grid) or "<div class=\"meta\">Нет дополнительных полей</div>"
        raw_json = json.dumps(it, ensure_ascii=False, indent=2)

        rows.append(f"""
        <div class=\"item\">
          <div><b>{name}</b></div>
          <div class=\"grid\">{grid_html}</div>
          <details style=\"margin-top:8px;\"><summary>Raw JSON</summary><pre>{raw_json}</pre></details>
        </div>
        """)
    items_html = "\n".join(rows) or "<p>Ничего не найдено.</p>"
    return f"""
<!doctype html>
<html lang=\"ru\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>BatchCards — NL Search</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; }}
    form {{ margin-bottom: 20px; }}
    input[type=text] {{ width: 80%; padding: 10px; font-size: 16px; }}
    button {{ padding: 10px 16px; font-size: 16px; }}
    .meta {{ color: #666; font-size: 14px; margin-bottom: 8px; }}
    .item {{ border: 1px solid #ddd; padding: 12px; border-radius: 6px; margin-bottom: 10px; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(240px, 1fr)); gap: 8px 16px; }}
    @media (max-width: 800px) {{ .grid {{ grid-template-columns: 1fr; }} input[type=text]{{ width: 100%; }} }}
    code {{ background: #f6f8fa; padding: 2px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
<h1>BatchCards — поиск контрагентов по естественному языку</h1>
<form method=\"post\" action=\"/search\"> 
  <input type=\"text\" name=\"q\" value=\"{q}\" required>
  <label><input type=\"checkbox\" name=\"use_llm\" {('checked' if use_llm_checked else '')}> Использовать локальную LLM (Ollama)</label>
  <button type=\"submit\">Искать</button>
</form>
<p class=\"meta\">API: <code>{api_url}</code></p>
<p class=\"meta\">Парсер: <b>{parser_used}</b></p>
<p class=\"meta\">Разбор запроса → <code>{parsed}</code></p>
<p class=\"meta\">Результаты (page={page}, page_size={page_size}, total={total}):</p>
{items_html}
</body>
</html>
"""


async def index(request: Request) -> HTMLResponse:
    settings = Settings()
    return HTMLResponse(HTML_INDEX.replace("{api_url}", settings.api_base_url or "—"))


async def search(request: Request) -> HTMLResponse:
    form = await request.form()
    q = str(form.get("q", "")).strip()
    if not q:
        return RedirectResponse("/", status_code=302)

    use_llm = bool(form.get("use_llm"))

    parsed = None
    parser_used = "rule-based"
    if use_llm and os.getenv("OLLAMA_BASE_URL"):
        try:
            parsed = nl_to_batchcards_via_ollama(q)
            if parsed:
                parser_used = "llm"
        except Exception:
            parsed = None
    if not parsed:
        parsed = convert_nl_to_batchcards(q)
        parser_used = "rule-based"

    settings = Settings()
    page_size = min(int(parsed.get("page_size", settings.default_page_size)), settings.max_page_size)

    req = BatchCardsRequest(
        filters=parsed.get("filters", {}),
        page=int(parsed.get("page", 1)),
        page_size=page_size,
    )
    try:
        res = await api_search_batchcards(settings, req)
        return HTMLResponse(_render_results_page(settings.api_base_url or "—", q, parsed, res.model_dump(), parser_used, use_llm))
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else 'HTTPError'
        text = None
        try:
            text = e.response.text
        except Exception:
            text = str(e)
        html = f"""
<!doctype html>
<html lang=\"ru\"><head><meta charset=\"utf-8\"><title>Ошибка запроса</title>
<style>body{{font-family:Arial,sans-serif;margin:20px}} pre{{background:#f6f8fa;padding:8px;border-radius:6px;white-space:pre-wrap}}</style>
</head><body>
<h2>Ошибка запроса к API (HTTP {status})</h2>
<p>URL: <code>{settings.api_base_url}</code></p>
<p>Параметры: <code>limit={req.page_size}, offset={(req.page-1)*req.page_size}</code></p>
<p>Тело (filters):</p>
<pre>{json.dumps(req.filters, ensure_ascii=False, indent=2)}</pre>
<p>Ответ сервера:</p>
<pre>{(text or '').strip()[:4000]}</pre>
<p>Попробуйте:
<ul>
  <li>Проверить доступность эндпоинта (curl) и что для него не нужен ключ/заголовок авторизации;</li>
  <li>Если нужна авторизация через заголовок — задайте переменные окружения <code>API_AUTH_BEARER</code> или пару <code>API_AUTH_HEADER_NAME/API_AUTH_HEADER_VALUE</code> в .env и перезапустите сервер.</li>
</ul>
</p>
<form method=\"post\" action=\"/search\"> 
  <input type=\"text\" name=\"q\" value=\"{q}\" required>
  <button type=\"submit\">Назад к поиску</button>
</form>
</body></html>
"""
        return HTMLResponse(html, status_code=502)
    except Exception as e:
        return HTMLResponse(f"<pre>{str(e)}</pre>", status_code=500)


routes = [
    Route("/", index, methods=["GET"]),
    Route("/search", search, methods=["POST"]),
]

app = Starlette(debug=True, routes=routes)