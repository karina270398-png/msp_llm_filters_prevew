import pytest
from msp_llm_filters.server import api_search, Settings, SearchRequest, SearchFilters


@pytest.mark.asyncio
async def test_api_search_mock_mode():
    """Тест моков без реального API."""
    settings = Settings(api_base_url="")  # Форсируем моки независимо от окружения
    req = SearchRequest(
        filters=SearchFilters(participant="test", court="Тестовый суд"),
        page=1,
        page_size=3
    )
    
    res = await api_search(settings, req)
    
    assert res.page == 1
    assert res.page_size == 3
    assert res.total == 1000
    assert len(res.items) == 3
    
    # Проверяем, что моки используют фильтры
    first_item = res.items[0]
    assert first_item.title == "Дело №1 (мок)"
    assert first_item.court == "Тестовый суд"


@pytest.mark.asyncio
async def test_api_search_pagination():
    """Тест пагинации в моках."""
    settings = Settings(api_base_url="")
    req = SearchRequest(page=2, page_size=5)
    
    res = await api_search(settings, req)
    
    assert res.page == 2
    assert res.page_size == 5
    assert res.next_page == 3
    
    # ID должны начинаться с CASE-5 (page=2, page_size=5)
    first_item = res.items[0]
    assert first_item.id == "CASE-5"
