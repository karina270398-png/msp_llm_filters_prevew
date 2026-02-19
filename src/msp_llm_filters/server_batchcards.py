import asyncio
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
import httpx
from pydantic import BaseModel, Field, ValidationError

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.stdio import stdio_server
except ImportError as e:  # pragma: no cover
    raise RuntimeError("mcp package is required. Install with: pip install mcp") from e


class Settings(BaseModel):
    api_base_url: str = Field(default_factory=lambda: os.getenv("API_BASE_URL", ""))
    api_key: str = Field(default_factory=lambda: os.getenv("API_KEY", ""))
    # Optional auth via headers
    api_auth_bearer: str = Field(default_factory=lambda: os.getenv("API_AUTH_BEARER", ""))
    api_auth_header_name: str = Field(default_factory=lambda: os.getenv("API_AUTH_HEADER_NAME", ""))
    api_auth_header_value: str = Field(default_factory=lambda: os.getenv("API_AUTH_HEADER_VALUE", ""))

    request_timeout_seconds: int = Field(default_factory=lambda: int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")))
    default_page_size: int = Field(default_factory=lambda: int(os.getenv("DEFAULT_PAGE_SIZE", "20")))
    max_page_size: int = Field(default_factory=lambda: int(os.getenv("MAX_PAGE_SIZE", "100")))

    @property
    def has_api(self) -> bool:
        return bool(self.api_base_url)


class BatchCardsRequest(BaseModel):
    # Для этого эндпоинта тело запроса — плоский JSON без вложенного "filters"
    # Используем словарь с валидацией только базовых типов; детальная схема задаётся в промпте.
    filters: Dict[str, Any] = Field(default_factory=dict, description="Тело JSON запроса к batchCardsByFilters")
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class SearchResponseGeneric(BaseModel):
    items: List[Dict[str, Any]]
    page: int
    page_size: int
    total: Optional[int] = None
    next_page: Optional[int] = None


async def api_search_batchcards(settings: Settings, req: BatchCardsRequest) -> SearchResponseGeneric:
    page_size = min(req.page_size or settings.default_page_size, settings.max_page_size)

    if not settings.has_api:
        # Мок для локальной отладки без внешнего API
        items = [
            {
                "name": f"Компания {i + 1}",
                "inn": f"77070{i:03d}{req.page}",
                "region_code": "77",
                "income": 10_000_000 + i * 1_000,
                "net_income": 100_000 + i * 100,
                "okved_main": "49.41",
            }
            for i in range(page_size)
        ]
        return SearchResponseGeneric(items=items, page=req.page, page_size=page_size, total=1000, next_page=req.page + 1)

    # If API_BASE_URL already contains a query (e.g., ...?limit=50&offset=0),
    # DO NOT add pagination params; use static values per endpoint contract.
    has_query = "?" in settings.api_base_url
    if has_query:
        limit = 50
        offset = 0
        params: Dict[str, str] = {}
    else:
        limit = page_size
        offset = (req.page - 1) * page_size
        params = {
            "limit": str(limit),
            "offset": str(offset),
        }
        if settings.api_key:
            params["key"] = settings.api_key

    body: Dict[str, Any] = req.filters or {}

    # Build headers similar to provided curl
    headers = {"Accept": "application/json"}
    if settings.api_auth_bearer:
        headers["Authorization"] = f"Bearer {settings.api_auth_bearer}"
    if settings.api_auth_header_name and settings.api_auth_header_value:
        headers[settings.api_auth_header_name] = settings.api_auth_header_value

    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        if has_query:
            final_url = settings.api_base_url
            r = await client.post(final_url, json=body, headers=headers)
        else:
            final_url = settings.api_base_url
            r = await client.post(final_url, params=params, json=body, headers=headers)
        r.raise_for_status()
        data = r.json()

    raw_items: List[Dict[str, Any]] = data.get("data") or data.get("items") or []
    total = data.get("total")
    if not isinstance(total, int):
        # Fallbacks: available_count or length of returned page
        total = data.get("available_count") if isinstance(data.get("available_count"), int) else len(raw_items)

    return SearchResponseGeneric(
        items=raw_items,
        page=req.page,
        page_size=page_size,
        total=total,
        next_page=(req.page + 1) if ((offset + limit) < int(total or 0)) else None,
    )


# ---- MCP server ----
load_dotenv()
settings = Settings()
app = FastMCP("msp-batch-cards")


@app.tool(name="ping", description="Проверка доступности MCP и связности с внешним API (batchCardsByFilters)")
async def ping() -> dict:
    return {
        "ok": True,
        "api_configured": settings.has_api,
        "api_base_url": settings.api_base_url or None,
    }


@app.tool(
    name="search_companies",
    description=(
        "Поиск компаний по естественным фильтрам (плоское тело JSON). Передавай в payload ключ 'filters' — это будет телом POST к /api/v1/batchCardsByFilters."
    ),
)
async def search_companies(payload: Dict[str, Any]) -> dict:
    try:
        req = BatchCardsRequest(**payload)
        if req.page_size > settings.max_page_size:
            req.page_size = settings.max_page_size
    except ValidationError as e:
        return {"error": "validation_error", "details": e.errors()}

    res = await api_search_batchcards(settings, req)
    return res.model_dump()


async def _run_stdio() -> None:
    async with stdio_server() as (read, write):
        await app.run(read, write)


def main_entry() -> None:
    asyncio.run(_run_stdio())


if __name__ == "__main__":
    main_entry()