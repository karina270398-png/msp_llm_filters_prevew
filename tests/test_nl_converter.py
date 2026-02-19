from msp_llm_filters.nl_converter import convert_nl_to_filters


def test_convert_date_march():
    query = "дела от 20 марта 2024 года"
    result = convert_nl_to_filters(query)
    
    assert result["filters"]["start_date_from"] == "2024-03-20"
    assert result["filters"]["start_date_to"] == "2024-03-20"


def test_convert_page_size():
    query = "покажи 5 дел"
    result = convert_nl_to_filters(query)
    
    assert result["page_size"] == 5


def test_convert_inn():
    query = "где ответчик ИНН 7707083893"
    result = convert_nl_to_filters(query)
    
    assert result["filters"]["participant"] == "7707083893"
    assert result["filters"]["role"] == "RESPONDENT"


def test_convert_court():
    query = "в Арбитражном суде Челябинской области"
    result = convert_nl_to_filters(query)
    
    assert result["filters"]["court"] == "Арбитражный суд Челябинской Области"


def test_convert_sort_sum():
    query = "покажи цены иска"
    result = convert_nl_to_filters(query)
    
    assert result["filters"]["sort"] == "sum"
    assert result["filters"]["order"] == "DESC"
