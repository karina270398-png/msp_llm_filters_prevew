import re
from typing import Dict, Any, Optional
from datetime import datetime


def convert_nl_to_filters(query: str) -> Dict[str, Any]:
    """
    Простой rule-based конвертер NL → filters для локальной отладки.
    Не заменяет LLM, но помогает проверить логику маппинга.
    """
    filters: Dict[str, Any] = {}
    page_size = 20  # по умолчанию
    
    query_lower = query.lower()
    
    # Даты (простейшие случаи)
    date_patterns = [
        (r"(\d{1,2}) (января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря) (\d{4})", "single_date"),
        (r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", "iso_date"),
    ]
    
    for pattern, date_type in date_patterns:
        match = re.search(pattern, query_lower)
        if match:
            if date_type == "single_date":
                day, month_name, year = match.groups()
                month_map = {
                    "января": "01", "февраля": "02", "марта": "03", "апреля": "04",
                    "мая": "05", "июня": "06", "июля": "07", "августа": "08",
                    "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12"
                }
                month = month_map.get(month_name, "01")
                date_str = f"{year}-{month}-{day.zfill(2)}"
                filters["start_date_from"] = date_str
                filters["start_date_to"] = date_str
            elif date_type == "iso_date":
                year, month, day = match.groups()
                date_str = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                filters["start_date_from"] = date_str
                filters["start_date_to"] = date_str
    
    # Количество дел (цифрами)
    count_match = re.search(r"(\d+)\s+дел", query_lower)
    if count_match:
        page_size = min(int(count_match.group(1)), 100)
    else:
        # Количество дел (словами): один, два, три, четыре, пять, шесть, семь, восемь, девять, десять
        num_words = {
            "один": 1, "одна": 1, "одно": 1, "перв": 1,
            "два": 2, "две": 2, "втор": 2,
            "три": 3, "треть": 3,
            "четыре": 4, "четвер": 4,
            "пять": 5, "пят": 5,
            "шесть": 6, "шест": 6,
            "семь": 7, "седь": 7,
            "восемь": 8, "восьм": 8,
            "девять": 9, "девят": 9,
            "десять": 10, "десят": 10,
            "двадцать": 20
        }
        # ищем шаблоны вида "(слово-числительное) (дел|дела|дело)"
        word_match = re.search(r"\b([а-яё]+)\s+дел\w*", query_lower)
        if word_match:
            w = word_match.group(1)
            # нормализуем до основы (берём первые 5 символов для эвристики суффиксов)
            value = None
            if w in num_words:
                value = num_words[w]
            else:
                # попробуем по префиксу
                for k, v in num_words.items():
                    if w.startswith(k[:5]):
                        value = v
                        break
            if value:
                page_size = min(int(value), 100)
    
    # Сортировка
    if "по цене иска" in query_lower or "цен" in query_lower:
        filters["sort"] = "sum"
        filters["order"] = "DESC"  # обычно хотят от большего к меньшему
    elif "по дате" in query_lower:
        filters["sort"] = "date_start"
        if "возраст" in query_lower:
            filters["order"] = "ASC"
        else:
            filters["order"] = "DESC"
    
    # ИНН
    inn_match = re.search(r"инн[\s:]*([\d]{10,12})", query_lower)
    if inn_match:
        filters["participant"] = inn_match.group(1)
    
    # Роль
    if "ответчик" in query_lower:
        filters["role"] = "RESPONDENT"
    elif "истец" in query_lower:
        filters["role"] = "PLAINTIFF"
    
    # Суд: полное название
    court_match = re.search(r"арбитражн[а-яё]+\s+суд[а-яё]*\s+([а-яё\s]+област[а-яё]|[а-яё\s]+кра[а-яё]|[а-яё\s]+республик[а-яё])", query_lower)
    if court_match:
        region = court_match.group(1).strip()
        filters["court"] = f"Арбитражный суд {region.title()}"
    else:
        # Аббревиатура: "АС Челябинской области" → "Арбитражный суд Челябинской области"
        ac_match = re.search(r"\bас\s+([а-яё\s]+област[а-яё]|[а-яё\s]+кра[а-яё]|[а-яё\s]+республик[а-яё])\b", query_lower)
        if ac_match:
            region = ac_match.group(1).strip()
            filters["court"] = f"Арбитражный суд {region.title()}"
    
    # Документы
    if "документ" in query_lower or "включи" in query_lower:
        filters["need_document"] = True
    
    return {
        "filters": filters,
        "page": 1,
        "page_size": page_size
    }


if __name__ == "__main__":
    # Тестовые примеры
    examples = [
        "Покажи цены иска пяти дел от 20 марта 2024 года зарегистрированных в Арбитражном суде Челябинской области",
        "Дела, где ответчик ИНН 7707083893, за декабрь 2024, документы включи",
        "Выведи 50 дел по участнику ООО Ромашка, отсортируй по дате возрастанию"
    ]
    
    for i, example in enumerate(examples, 1):
        print(f"\nПример {i}: {example}")
        result = convert_nl_to_filters(example)
        print(f"Результат: {result}")
