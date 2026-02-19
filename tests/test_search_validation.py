import pytest
from msp_llm_filters.server import SearchRequest, SearchFilters
from pydantic import ValidationError


def test_search_request_valid():
    req = SearchRequest(
        filters=SearchFilters(participant="1027739020760", sort="sum"),
        page=1,
        page_size=10
    )
    assert req.page == 1
    assert req.page_size == 10
    assert req.filters.participant == "1027739020760"
    assert req.filters.sort == "sum"


def test_search_request_invalid_page_size():
    with pytest.raises(ValidationError):
        SearchRequest(page_size=0)  # должно быть >= 1


def test_search_request_max_page_size():
    with pytest.raises(ValidationError):
        SearchRequest(page_size=101)  # должно быть <= 100


def test_filters_date_format():
    filters = SearchFilters(
        start_date_from="2024-03-20",
        start_date_to="2024-03-20"
    )
    assert filters.start_date_from == "2024-03-20"
    assert filters.start_date_to == "2024-03-20"
