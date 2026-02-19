import asyncio
import os
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone


def normalize_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # предполагаем миллисекунды unix epoch
        try:
            ts = float(value) / 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except Exception:
            return str(value)
    return str(value)

from dotenv import load_dotenv
import httpx
from pydantic import BaseModel, Field, ValidationError

try:
    # Современный API SDK
    from mcp.server.fastmcp import FastMCP
    from mcp.server.stdio import stdio_server
except ImportError as e:  # pragma: no cover
    raise RuntimeError("mcp package is required. Install with: pip install mcp") from e


# ---- Config ----
class Settings(BaseModel):
    api_base_url: str = Field(default_factory=lambda: os.getenv("API_BASE_URL", ""))
    api_key: str = Field(default_factory=lambda: os.getenv("API_KEY", ""))
    request_timeout_seconds: int = Field(default_factory=lambda: int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")))
    default_page_size: int = Field(default_factory=lambda: int(os.getenv("DEFAULT_PAGE_SIZE", "20")))
    max_page_size: int = Field(default_factory=lambda: int(os.getenv("MAX_PAGE_SIZE", "100")))
    courts_url: str = Field(default_factory=lambda: os.getenv("COURTS_URL", "http://10.0.61.119:8092/api_ext/v1/dictionary/arbitration/courts"))
    dispute_categories_url: str = Field(default_factory=lambda: os.getenv("DISPUTE_CATEGORIES_URL", "http://10.0.61.119:8092/api_ext/v1/dictionary/arbitration/dispute-categories"))
    document_types_url: str = Field(default_factory=lambda: os.getenv("DOCUMENT_TYPES_URL", "http://10.0.61.119:8092/api_ext/v1/dictionary/arbitration/document-types"))

    @property
    def has_api(self) -> bool:
        return bool(self.api_base_url)


# ---- Schemas ----
class SearchFilters(BaseModel):
    # Поля соответствуют документации batch-cases
    sort: Optional[str] = Field(None, description="date_start | sum")
    order: Optional[str] = Field(None, description="ASC | DESC")
    need_document: Optional[bool] = None
    role: Optional[str] = Field(None, description="RESPONDENT | PLAINTIFF | ...")
    status: Optional[str] = Field(None, description="0 | 1")
    dispute: Optional[int] = None
    doc_type: Optional[str] = None
    court: Optional[str] = None
    case_num: Optional[str] = None
    participant: Optional[str] = None
    start_date_from: Optional[str] = Field(None, description="YYYY-MM-DD")
    start_date_to: Optional[str] = Field(None, description="YYYY-MM-DD")
    sum_from: Optional[int] = None
    sum_to: Optional[int] = None
    updated_at_from: Optional[str] = Field(None, description="YYYY-MM-DD")
    updated_at_to: Optional[str] = Field(None, description="YYYY-MM-DD")


class SearchRequest(BaseModel):
    filters: SearchFilters = Field(default_factory=SearchFilters)
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    sort: Optional[str] = Field(None, description="пример: date_desc | date_asc | relevance")


class CaseSummary(BaseModel):
    id: str
    title: str  # обычно first_number
    court: Optional[str] = None
    date: Optional[str] = None  # date_start
    sum: Optional[float] = None
    currency: Optional[str] = None
    status: Optional[int] = None
    kad_arbitr_link: Optional[str] = None
    last_document_date: Optional[str] = None
    document_types: Optional[List[str]] = None
    participants_short: Optional[List[str]] = None
    documents: Optional[List[Dict[str, Any]]] = None
    snippet: Optional[str] = None


class SearchResponse(BaseModel):
    items: List[CaseSummary]
    page: int
    page_size: int
    total: Optional[int] = None
    next_page: Optional[int] = None


class CaseDetail(BaseModel):
    id: str
    title: str
    court: Optional[str] = None
    date: Optional[str] = None
    participants: Optional[List[str]] = None
    documents: Optional[List[Dict[str, Any]]] = None


# ---- Adapter to external API (placeholder) ----
async def api_search(settings: Settings, req: SearchRequest) -> SearchResponse:
    """Адаптер под batch-cases. Если API_BASE_URL не задан, возвращаем мок."""
    page_size = min(req.page_size or settings.default_page_size, settings.max_page_size)

    if not settings.has_api:
        # Mocked data
        items = [
            CaseSummary(
                id=f"CASE-{i + (req.page-1)*page_size}",
                title=f"Дело №{i + 1} (мок)",
                court=req.filters.court or "Арбитражный суд (мок)",
                date="2024-01-0{}".format((i % 9) + 1),
                snippet=(req.filters.participant or "") + " " + (req.filters.role or "")
            )
            for i in range(page_size)
        ]
        return SearchResponse(items=items, page=req.page, page_size=page_size, total=1000, next_page=req.page + 1)

    # Маппинг пагинации: page/page_size -> offset/limit
    limit = page_size
    offset = (req.page - 1) * page_size

    # Query параметры: key, limit, offset
    params = {
        "key": settings.api_key,
        "limit": str(limit),
        "offset": str(offset),
    }

    # Тело запроса — фильтры как есть по документации
    body: Dict[str, Any] = req.filters.model_dump(exclude_none=True)

    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        r = await client.post(settings.api_base_url, params=params, json=body)
        r.raise_for_status()
        data = r.json()

    # Ожидаем структуру по схеме: { data: [...], total, limit, offset }
    raw_items: List[Dict[str, Any]] = data.get("data", []) or []

    def make_snippet(it: Dict[str, Any]) -> str:
        parts: List[str] = []
        if it.get("sum") is not None:
            parts.append(f"сумма: {it.get('sum')}")
        if it.get("currency"):
            parts.append(f"валюта: {it.get('currency')}")
        if it.get("status") is not None:
            parts.append(f"статус: {it.get('status')}")
        if it.get("dispute") is not None:
            parts.append(f"спор: {it.get('dispute')}")
        return ", ".join(parts)

    def aggregate_participants_short(it: Dict[str, Any]) -> List[str]:
        names: List[str] = []
        for role_key in [
            "plaintiffs",
            "respondents",
            "third_parties",
            "interested_persons",
            "creditors",
            "creditors_current_payments",
            "debtors",
            "applicants",
            "others",
        ]:
            for p in it.get(role_key) or []:
                name = p.get("name") or p.get("norm_name")
                if name:
                    names.append(name)
        # ограничим превью, но оставим возможность посмотреть полностью через documents/деталь
        return names[:10] if names else []

    items = []
    for it in raw_items:
        if not (it.get("case_id") or it.get("first_number")):
            continue
        items.append(
            CaseSummary(
                id=str(it.get("case_id") or it.get("first_number") or ""),
                title=str(it.get("first_number") or it.get("case_id") or "Дело"),
                court=None,  # явного поля нет
                date=normalize_date(it.get("date_start")),
                sum=it.get("sum"),
                currency=it.get("currency"),
                status=it.get("status"),
                kad_arbitr_link=it.get("kad_arbitr_link"),
                last_document_date=normalize_date(it.get("last_document_date")),
                document_types=it.get("document_types"),
                participants_short=(aggregate_participants_short(it) or None),
                documents=it.get("documents") if body.get("need_document") else None,
                snippet=make_snippet(it),
            )
        )

    total = data.get("total")
    next_page: Optional[int] = None
    if isinstance(total, int) and (offset + limit) < total:
        next_page = req.page + 1

    return SearchResponse(
        items=items,
        page=req.page,
        page_size=page_size,
        total=total,
        next_page=next_page,
    )

async def api_get_case(settings: Settings, case_id: str) -> CaseDetail:
    # Реализуем через batch-cases с фильтром case_num и limit=1
    if not settings.has_api:
        return CaseDetail(
            id=case_id,
            title=f"Дело {case_id} (мок)",
            court="Арбитражный суд (мок)",
            date="2024-02-01",
            participants=["Истец (мок)", "Ответчик (мок)"],
            documents=[{"id": "doc-1", "title": "Решение (мок)", "url": "https://example.com/doc"}],
        )

    params = {
        "key": settings.api_key,
        "limit": "1",
        "offset": "0",
    }
    body = {"case_num": case_id, "need_document": True}

    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        r = await client.post(settings.api_base_url, params=params, json=body)
        r.raise_for_status()
        data = r.json()

    arr = data.get("data") or []
    if not arr:
        # Не найдено
        return CaseDetail(id=case_id, title=str(case_id))

    it = arr[0]
    # Участники: соберем имена по ролям, если есть
    participants: List[str] = []
    for role_key in [
        "plaintiffs",
        "respondents",
        "third_parties",
        "interested_persons",
        "creditors",
        "creditors_current_payments",
        "debtors",
        "applicants",
        "others",
    ]:
        for p in it.get(role_key) or []:
            name = p.get("name") or p.get("norm_name")
            if name:
                participants.append(name)

    documents = it.get("documents")

    return CaseDetail(
        id=str(it.get("case_id") or case_id),
        title=str(it.get("first_number") or it.get("case_id") or case_id),
        court=None,
        date=it.get("date_start"),
        participants=participants or None,
        documents=documents,
    )


# ---- Dictionaries ----
async def api_list_courts(settings: Settings) -> List[Dict[str, Any]]:
    params = {"key": settings.api_key} if settings.api_key else {}
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        r = await client.get(settings.courts_url, params=params)
        r.raise_for_status()
        data = r.json()
    # Ожидается массив
    return data if isinstance(data, list) else data.get("data") or []


async def api_list_dispute_categories(settings: Settings) -> List[Dict[str, Any]]:
    params = {"key": settings.api_key} if settings.api_key else {}
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        r = await client.get(settings.dispute_categories_url, params=params)
        r.raise_for_status()
        data = r.json()
    return data if isinstance(data, list) else data.get("data") or []


async def api_list_document_types(settings: Settings) -> List[Dict[str, Any]]:
    params = {"key": settings.api_key} if settings.api_key else {}
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        r = await client.get(settings.document_types_url, params=params)
        r.raise_for_status()
        data = r.json()
    return data if isinstance(data, list) else data.get("data") or []


# ---- MCP server ----
load_dotenv()
settings = Settings()
app = FastMCP("mcp-llm-courts")


@app.tool(name="ping", description="Проверка доступности MCP и связности с внешним API")
async def ping() -> dict:
    return {
        "ok": True,
        "api_configured": settings.has_api,
        "api_base_url": settings.api_base_url or None,
    }


@app.tool(
    name="search_cases",
    description=(
        "Поиск дел по фильтрам (с пагинацией). Всегда возвращает развернутые данные: "
        "title(first_number), date_start, sum, currency, status, kad_arbitr_link, "
        "document_types, last_document_date, participants_short, при need_document=true — documents. "
        "LLM: маппируй естественные запросы на фильтры: ‘цена иска’->sum, одна дата -> start_date_from=start_date_to, "
        "‘пять дел’->page_size=5, ‘Арбитражный суд …’->court, сортировка по сумме -> sort=sum."
    ),
)
async def search_cases(payload: Dict[str, Any]) -> dict:
    try:
        req = SearchRequest(**payload)
        # enforce max page size from settings
        if req.page_size > settings.max_page_size:
            req.page_size = settings.max_page_size
    except ValidationError as e:
        return {"error": "validation_error", "details": e.errors()}

    res = await api_search(settings, req)
    return res.model_dump()


@app.tool(
    name="get_case_by_id",
    description="Получить детальную карточку дела по идентификатору. Аргументы: {case_id}",
)
async def get_case_by_id(payload: Dict[str, Any]) -> dict:
    case_id = payload.get("case_id")
    if not case_id:
        return {"error": "validation_error", "details": [{"loc": ["case_id"], "msg": "required"}]}

    res = await api_get_case(settings, case_id)
    return res.model_dump()


@app.tool(
    name="list_courts",
    description="Справочник: Арбитражные суды. Возвращает список судов для нормализации поля court",
)
async def list_courts(params: Dict[str, Any] | None = None) -> dict:
    data = await api_list_courts(settings)
    return {"items": data}


@app.tool(
    name="list_dispute_categories",
    description="Справочник: Категории арбитражных споров (dispute 0..11)",
)
async def list_dispute_categories(params: Dict[str, Any] | None = None) -> dict:
    data = await api_list_dispute_categories(settings)
    return {"items": data}


@app.tool(
    name="list_document_types",
    description="Справочник: Типы документов арбитражных дел (doc_type)",
)
async def list_document_types(params: Dict[str, Any] | None = None) -> dict:
    data = await api_list_document_types(settings)
    return {"items": data}


async def _run_stdio() -> None:
    async with stdio_server() as (read, write):
        await app.run(read, write)


def main_entry() -> None:
    asyncio.run(_run_stdio())


if __name__ == "__main__":
    main_entry()
