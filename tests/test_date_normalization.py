from msp_llm_filters.server import normalize_date


def test_normalize_epoch_ms_to_iso():
    # 2024-03-20T00:00:00Z in ms
    ms = 1710892800000
    iso = normalize_date(ms)
    assert iso.startswith("2024-03-20")


def test_normalize_string_passthrough():
    assert normalize_date("2024-01-01") == "2024-01-01"
