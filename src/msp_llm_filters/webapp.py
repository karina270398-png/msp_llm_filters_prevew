from typing import Any, Dict
import os

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.requests import Request
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from .nl_converter import convert_nl_to_filters
from .llm_client import nl_to_filters_via_ollama
from .server import api_search, Settings, SearchRequest, SearchFilters, normalize_date


HTML_INDEX = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MCP Courts — NL Search</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    form { margin-bottom: 20px; }
    input[type=text] { width: 80%; padding: 10px; font-size: 16px; }
    button { padding: 10px 16px; font-size: 16px; }
    .meta { color: #666; font-size: 14px; margin-bottom: 8px; }
    .case { border: 1px solid #ddd; padding: 12px; border-radius: 6px; margin-bottom: 10px; }
    .case h3 { margin: 0 0 6px 0; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(240px, 1fr)); gap: 8px 16px; }
    @media (max-width: 800px) { .grid { grid-template-columns: 1fr; } input[type=text]{ width: 100%; } }
    code { background: #f6f8fa; padding: 2px 4px; border-radius: 4px; }
    .row { margin: 6px 0; }
  </style>
</head>
<body>
<h1>MCP Courts — поиск по естественному языку</h1>
<form method="post" action="/search">
  <div class="row">
    <input type="text" name="q" placeholder="Например: Покажи цены иска пяти дел от 20 марта 2024 года в Арбитражном суде Челябинской области" required>
  </div>
  <div class="row">
    <label><input type="checkbox" name="use_llm"> Использовать локальную LLM (Ollama)</label>
  </div>
  <button type="submit">Искать</button>
</form>
<p class="meta">API: <code>{api_url}</code></p>
</body>
</html>
"""


def _render_results_page(api_url: str, q: str, parsed: Dict[str, Any], res: Dict[str, Any]) -> str:
    items = res.get("items", [])
    total = res.get("total")
    page = res.get("page")
    page_size = res.get("page_size")
    rows = []
    for it in items:
        rows.append(f"""
        <div class=\"case\">
          <h3>{it.get('title') or it.get('id')}</h3>
          <div class=\"grid\">
            <div><b>Дата начала:</b> {it.get('date') or '—'}</div>
            <div><b>Цена иска:</b> {it.get('sum') or '—'} {it.get('currency') or ''}</div>
            <div><b>Статус:</b> {it.get('status') if it.get('status') is not None else '—'}</div>
            <div><b>Ссылка КАД:</b> {f'<a href="{it.get("kad_arbitr_link")}" target="_blank">перейти</a>' if it.get('kad_arbitr_link') else '—'}</div>
            <div><b>Типы документов:</b> {', '.join(it.get('document_types') or []) or '—'}</div>
            <div><b>Последний документ:</b> {it.get('last_document_date') or '—'}</div>
            <div style=\"grid-column:1/-1\"><b>Участники (кратко):</b> {', '.join(it.get('participants_short') or []) or '—'}</div>
          </div>
        </div>
        """)
    items_html = "\n".join(rows) or "<p>Ничего не найдено.</p>"
    return f"""
<!doctype html>
<html lang=\"ru\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>MCP Courts — NL Search</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; }}
    form {{ margin-bottom: 20px; }}
    input[type=text] {{ width: 80%; padding: 10px; font-size: 16px; }}
    button {{ padding: 10px 16px; font-size: 16px; }}
    .meta {{ color: #666; font-size: 14px; margin-bottom: 8px; }}
    .case {{ border: 1px solid #ddd; padding: 12px; border-radius: 6px; margin-bottom: 10px; }}
    .case h3 {{ margin: 0 0 6px 0; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(240px, 1fr)); gap: 8px 16px; }}
    @media (max-width: 800px) {{ .grid {{ grid-template-columns: 1fr; }} input[type=text]{{ width: 100%; }} }}
    code {{ background: #f6f8fa; padding: 2px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
<h1>MCP Courts — поиск по естественному языку</h1>
<form method=\"post\" action=\"/search\"> 
  <input type=\"text\" name=\"q\" value=\"{q}\" required>
  <button type=\"submit\">Искать</button>
</form>
<p class=\"meta\">API: <code>{api_url}</code></p>
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
    # Попробуем через LLM, иначе rule-based
    parsed = None
    if use_llm and os.getenv("OLLAMA_BASE_URL"):
        try:
            parsed = nl_to_filters_via_ollama(q)
        except Exception:
            parsed = None
    if not parsed:
        parsed = convert_nl_to_filters(q)
    # Всегда длинный ответ: включим документы по умолчанию
    parsed["filters"]["need_document"] = True

    # page_size ограничим по настройкам
    settings = Settings()
    page_size = min(int(parsed.get("page_size", settings.default_page_size)), settings.max_page_size)

    req = SearchRequest(
        filters=SearchFilters(**parsed["filters"]),
        page=int(parsed.get("page", 1)),
        page_size=page_size,
    )
    res = await api_search(settings, req)
    return HTMLResponse(_render_results_page(settings.api_base_url or "—", q, parsed, res.model_dump()))


routes = [
    Route("/", index, methods=["GET"]),
    Route("/search", search, methods=["POST"]),
]

app = Starlette(debug=True, routes=routes)
