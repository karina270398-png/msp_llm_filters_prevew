import re
from typing import Dict, Any, List

def _to_number(s: str) -> float:
    s = s.strip().replace(" ", "").replace("\u00A0", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def _rubles_to_thousands(value_rub: float) -> int:
    return int(round(value_rub / 1000.0))


def convert_nl_to_batchcards(query: str) -> Dict[str, Any]:
    """
    Простой rule-based конвертер NL → тело запроса для batchCardsByFilters.
    Возвращает структуру {filters, page, page_size}, где filters — это плоский JSON для тела POST.
    """
    q = query.lower()
    filters: Dict[str, Any] = {}
    page_size = 50  # по умолчанию

    # Количество: "покажи 200 компаний" / "20 контрагентов"
    m = re.search(r"(\d+)\s+(компан|контрагент|запис|дел)", q)
    if m:
        try:
            page_size = int(m.group(1))
        except Exception:
            pass

    # Свободный текст
    m = re.search(r"(поиск|содержит|ключев\w* слово)\s*[:\-]?\s*([а-яa-z0-9\s\-\.,]+)$", q)
    if m:
        filters["search_text"] = m.group(2).strip()

    # ОКВЭДы: ищем только если явно упоминается ОКВЭД/вид деятельности
    if "оквэд" in q or "вид деятель" in q or "виды деятель" in q:
        okveds = re.findall(r"\b\d{2}(?:\.\d{1,2}){0,2}\b", q)
        if okveds:
            filters["okveds"] = list(dict.fromkeys(okveds))

    # Регионы (по словам) — базовое покрытие для частых случаев
    # Москва (77) vs Московская область (50); СПб (78)
    if re.search(r"\bмосковск[а-яё]+\s+област", q):
        filters.setdefault("region_codes", [])
        if "50" not in filters["region_codes"]:
            filters["region_codes"].append("50")
    elif re.search(r"\bмоскв[ае]\b|\bмск\b", q):
        filters.setdefault("region_codes", [])
        if "77" not in filters["region_codes"]:
            filters["region_codes"].append("77")
    if re.search(r"\bсанкт[-\s]?петербург\b|\bспб\b", q):
        filters.setdefault("region_codes", [])
        if "78" not in filters["region_codes"]:
            filters["region_codes"].append("78")

    # Регионы (цифрами): "77 регион"
    region_codes = re.findall(r"\b(\d{2})\b\s*регион", q)
    if region_codes:
        filters.setdefault("region_codes", [])
        for rc in region_codes:
            if rc not in filters["region_codes"]:
                filters["region_codes"].append(rc)

    # Тип контрагента (с учётом отрицаний, напр. "не ип")
    neg_ip = re.search(r"\bне\s+ип\b", q) is not None
    pos_ip = re.search(r"\bип\b|индивидуальн[а-яё]*\s+предпринимател", q) is not None
    neg_ul = re.search(r"\bне\s+(?:юр(?:лиц|идическ)[а-яё]*|ооо|ао|зао|oao|ul)\b", q) is not None
    pos_ul = re.search(r"юр(лиц|идическ)[а-яё]*|\bооо\b|\bао\b|\bзао\b|\boao\b", q) is not None
    pos_fl = re.search(r"физ(ическ)[а-яё]*\s+лиц", q) is not None

    if pos_ip and not neg_ip and not pos_ul:
        filters["counterparty_type"] = "ip"
    elif pos_ul and not neg_ul and not pos_ip:
        filters["counterparty_type"] = "ul"
    elif pos_fl:
        filters["counterparty_type"] = "fl"
    elif neg_ip and ("компан" in q or pos_ul) and not neg_ul:
        # Явно исключили ИП и упомянули "компании" или UL-маркеры — считаем UL
        filters["counterparty_type"] = "ul"

    # Флаги
    if "только действующ" in q or "действующие" in q:
        filters["only_active"] = True
    if "с выручко" in q or "есть выручка" in q:
        filters["has_income"] = True
    if "только с бфо" in q or "с бфо" in q:
        filters["only_with_bfo"] = True
    if "только с телефонами" in q or re.search(r"с\s+телефон", q):
        filters["only_with_phones"] = True
    if "только с почта" in q or "с email" in q or "с e-mail" in q:
        filters["only_with_emails"] = True
    if "только с сайт" in q or re.search(r"с\s+сайт", q):
        filters["only_with_websites"] = True
    # Аккредитованные ИТ‑компании
    if re.search(r"аккредитованн[а-яё]*\s+ит", q) or "ит-компан" in q or "ит компании" in q:
        filters["only_it_companies"] = True

    # Основные/доп. ОКВЭДы
    if re.search(r"по\s+доп(олнительным)?\s+оквэд", q):
        filters["only_main_okveds"] = False
    if re.search(r"исключать\s+по\s+доп(олнительным)?\s+оквэд", q):
        filters["exclude_only_main_okveds"] = False

    # Условие И/ИЛИ для контактов
    if re.search(r"контактн[а-яё]*\s+услови[яе].*\bи\b|одновременно", q):
        filters["contact_conditions_operator"] = "AND"
    elif "или" in q:
        filters["contact_conditions_operator"] = "OR"

    # Диапазоны выручки (API ждёт тыс. рублей)
    # Допускаем «составляет/≈/около» между словом «выручка» и сравнением
    filler = r"(?:[а-яё\s,:()–-]{0,40}?)"
    # 1) "выручка ... от X до Y"
    m = re.search(rf"выручк\w*{filler}от\s*([\d\s.,]+)\s*до\s*([\d\s.,]+)\s*(тыс|млн|миллион|млрд|миллиард)?(?:\s*(?:руб(?:\.|лей|ля)?|р\.?|₽))?", q)
    if m:
        x = _to_number(m.group(1))
        y = _to_number(m.group(2))
        unit = (m.group(3) or '').lower()
        mult = 1.0
        if unit in ("млн", "миллион", "миллиона", "миллионов"):
            mult = 1_000_000.0
        elif unit in ("млрд", "миллиард", "миллиарда", "миллиардов"):
            mult = 1_000_000_000.0
        filters["income_from"] = _rubles_to_thousands(x * mult)
        filters["income_to"] = _rubles_to_thousands(y * mult)
    else:
        # 2) "выручка ... больше/свыше/не менее X"
        m = re.search(rf"выручк\w*{filler}(?:>|больше|свыше|выше|не\s*менее|от)\s*([\d\s.,]+)\s*(тыс|млн|миллион|млрд|миллиард)?(?:\s*(?:руб(?:\.|лей|ля)?|р\.?|₽))?", q)
        if m:
            x = _to_number(m.group(1))
            unit = (m.group(2) or '').lower()
            mult = 1.0
            if unit in ("млн", "миллион", "миллиона", "миллионов"):
                mult = 1_000_000.0
            elif unit in ("млрд", "миллиард", "миллиарда", "миллиардов"):
                mult = 1_000_000_000.0
            filters["income_from"] = _rubles_to_thousands(x * mult)
        else:
            # 3) "выручка ... до X"
            m = re.search(rf"выручк\w*{filler}до\s*([\d\s.,]+)\s*(тыс|млн|миллион|млрд|миллиард)?(?:\s*(?:руб(?:\.|лей|ля)?|р\.?|₽))?", q)
            if m:
                x = _to_number(m.group(1))
                unit = (m.group(2) or '').lower()
                mult = 1.0
                if unit in ("млн", "миллион", "миллиона", "миллионов"):
                    mult = 1_000_000.0
                elif unit in ("млрд", "миллиард", "миллиарда", "миллиардов"):
                    mult = 1_000_000_000.0
                filters["income_to"] = _rubles_to_thousands(x * mult)

    # Fallback: "выручка ... составляет [больше] X" (если ранее не сработало)
    if "income_from" not in filters and "income_to" not in filters:
        m = re.search(rf"выручк\w*{filler}(?:составля[ею]т|сост\.)\s*(?:>|больше|свыше|выше|не\s*менее|от)?\s*([\d\s.,]+)\s*(тыс|млн|миллион|млрд|миллиард)?(?:\s*(?:руб(?:\.|лей|ля)?|р\.?|₽))?", q)
        if m:
            x = _to_number(m.group(1))
            unit = (m.group(2) or '').lower()
            mult = 1.0
            if unit in ("тыс", "тысяч", "тысяча", "тысячи"):
                mult = 1_000.0
            elif unit in ("млн", "миллион", "миллиона", "миллионов"):
                mult = 1_000_000.0
            elif unit in ("млрд", "миллиард", "миллиарда", "миллиардов"):
                mult = 1_000_000_000.0
            filters["income_from"] = _rubles_to_thousands(x * mult)

    # Диапазоны прибыли (в тыс. руб.)
    m = re.search(r"прибыл\w*\s*от\s*([\d\s.,]+)\s*до\s*([\d\s.,]+)", q)
    if m:
        filters["net_income_from"] = _rubles_to_thousands(_to_number(m.group(1)))
        filters["net_income_to"] = _rubles_to_thousands(_to_number(m.group(2)))

    # Отчётный год для финансов
    m = re.search(r"за\s+(\d{4})\s*год", q)
    if m:
        try:
            filters["finance_report_year"] = int(m.group(1))
        except Exception:
            pass

    # Динамика роста (финансы)
    m = re.search(r"(стабильн\w*\s+динамик\w*\s+роста|рост)\s*(?:более|>|не\s+менее|от)\s*([\d.,]+)\s*%", q)
    if m:
        growth = float(m.group(2).replace(',', '.'))
        filters["finance_request"] = {
            "metrics": ["INCOME"],
            "growth_from": growth,
            "years_count": 3,
            "year_by_year": True,
        }

    # Даты (YYYY-MM-DD)
    m = re.search(r"создан\w*\s*с\s*(\d{4}-\d{2}-\d{2})\s*по\s*(\d{4}-\d{2}-\d{2})", q)
    if m:
        filters["establishment_date_from"] = m.group(1)
        filters["establishment_date_to"] = m.group(2)
    m = re.search(r"прекращен\w*\s*с\s*(\d{4}-\d{2}-\d{2})\s*по\s*(\d{4}-\d{2}-\d{2})", q)
    if m:
        filters["date_end_from"] = m.group(1)
        filters["date_end_to"] = m.group(2)

    # ЕГР статусы (базовые маппинги)
    status_map = {
        "действующ": "Действует",
        "ликвидац": "В процессе ликвидации",
        "банкрот": "В процессе банкротства",
        "реорганизац": "В процессе реорганизации с последующим прекращением деятельности",
    }
    egr: List[str] = []
    for k, v in status_map.items():
        if k in q and v not in egr:
            egr.append(v)
    if egr:
        filters["egr_statuses"] = egr

    # ОПФ / типы контрагента по кодам/ярлыкам (учитываем отрицания)
    opf: List[str] = []
    if (re.search(r"\bип\b", q) and not re.search(r"\bне\s+ип\b", q)):
        opf.append("ip")
    if (re.search(r"\bул\b|юр(лиц|идическ)", q) and not re.search(r"\bне\s+(?:ул|юр(?:лиц|идическ))\b", q)):
        opf.append("ul")
    if opf:
        filters["opf_codes"] = opf

    # Лицензии, формы поддержки
    lic = re.findall(r"\b\d{5,7}\b(?=.*лиценз)", q)
    if lic:
        filters["licenses"] = list(dict.fromkeys(lic))
    supp = re.findall(r"\b\d{2,4}\b(?=.*поддержк)", q)
    if supp:
        filters["support_forms"] = list(dict.fromkeys(supp))

    # Категории МСП (микро/малое/среднее)
    msp = []
    if "микро" in q:
        msp.append("1")
    if "малое" in q:
        msp.append("2")
    if "средн" in q:
        msp.append("3")
    if msp:
        filters["msp_categories"] = list(dict.fromkeys(msp))

    # Численность сотрудников
    m = re.search(r"(сотрудник|численност)[а-яё]*\s*от\s*(\d+)\s*до\s*(\d+)", q)
    if m:
        filters["ssch_from"] = int(m.group(2))
        filters["ssch_to"] = int(m.group(3))

    # Спец флаги МСП
    if "инновационн" in q:
        filters["only_msp_innovative"] = True
    if "партнер" in q and "мсп" in q:
        filters["only_msp_partner"] = True
    if "социальн" in q and "предприяти" in q:
        filters["only_msp_social"] = True

    # Ювелирные, СРО
    if "ювелир" in q:
        filters["only_jewelry"] = True
    if "нострой" in q:
        filters["only_nostroy_members"] = True
    if "ноприз" in q:
        filters["only_nopriz_members"] = True

    # Общий текстовый поиск по специализации: "специализирующ*ся на <термин>"
    m = re.search(r"специализирующ[а-яё]*\s*ся\s*на\s*([а-яa-z0-9\-\s]+?)(?:[,.]|$)", q)
    if m:
        filters["search_terms"] = [m.group(1).strip()]

    # Росаккредитация
    if "росаккред" in q:
        ra: Dict[str, Any] = {}
        m = re.search(r"(декларац[ия]|сертификат|декларация\s+или\s+сертификат)", q)
        if m:
            t = m.group(1).lower()
            if "декларац" in t and "сертифик" in q:
                ra["type"] = "Декларация или сертификат"
            elif "декларац" in t:
                ra["type"] = "Декларация"
            elif "сертифик" in t:
                ra["type"] = "Сертификат"
        # Статусы
        sts: List[str] = []
        for word, norm in [("прекращ", "Прекращён"), ("возобнов", "Возобновлён"), ("действ", "Действует"), ("недейств", "Недействителен"), ("приостан", "Приостановлен"), ("архив", "Архивный")]:
            if word in q and norm not in sts:
                sts.append(norm)
        if sts:
            ra["statuses"] = sts
        # Описание/термины
        m = re.search(r"росаккред[а-яё\s,]*:(.*)$", q)
        if m:
            ra["description"] = m.group(1).strip()
        if ra:
            filters["rosaccreditations"] = ra

    # Вакансии (синонимы: работа, найм, поиск сотрудников, ищут/нанимают/нужны/требуются)
    if re.search(r"ваканси|работа|найм|поиск\s+сотрудник|\bищут\b|\bищем\b|нанимают|нужн[ыо]|требуютс[я]", q):
        vac: Dict[str, Any] = {"has_vacancies": True}
        if re.search(r"активн|актуал|открыт", q):
            vac["only_active"] = True
        # Зарплата/оклад/зп
        m = re.search(r"(зарплат[аы]?|оклад|з\/?п|вознаграждени[ея])\s*от\s*([\d\s.,]+)\s*до\s*([\d\s.,]+)", q)
        if m:
            vac["salary_min"] = int(_to_number(m.group(2)))
            vac["salary_max"] = int(_to_number(m.group(3)))
        else:
            m = re.search(r"(зарплат[аы]?|оклад|з\/?п|вознаграждени[ея])\s*от\s*([\d\s.,]+)", q)
            if m:
                vac["salary_min"] = int(_to_number(m.group(2)))
            m = re.search(r"(зарплат[аы]?|оклад|з\/?п|вознаграждени[ея])\s*до\s*([\d\s.,]+)", q)
            if m:
                vac["salary_max"] = int(_to_number(m.group(2)))
        # Текст/термины из фраз "вакансии по/с ..." или "ищут/нанимают/нужны/требуются ..."
        m = re.search(r"(?:ваканси[яи]?|работа)\s*(?:по|с)\s*([а-яa-z0-9\-\s]+)", q)
        if not m:
            m = re.search(r"(?:ищут|ищем|нанимают|нужн[ыо]|требуютс[я])\s+([а-яa-z0-9\-\s]+?)(?:[,.]|\bсо\b|$)", q)
        if m:
            vac["text"] = m.group(1).strip()
        # Если явно упомянуты разработчик/программист — добавим в текст
        if re.search(r"разработчик|программист|software\s*engineer|developer", q) and "text" not in vac:
            vac["text"] = "разработчик"
        if "только в названи" in q:
            vac["only_name"] = True
        # Источник
        if re.search(r"\bhh\b|head\s*hun\w*|хэдхантер", q):
            vac["source"] = "HH_VACANCIES"
        # Регион кода внутри вакансий
        m = re.search(r"в\s+регион[еу]?\s*(\d{2})", q)
        if m:
            vac["region_code"] = m.group(1)
        # Период публикаций
        m = re.search(r"публикован[а-яё\s]*с\s*(\d{4}-\d{2}-\d{2})\s*по\s*(\d{4}-\d{2}-\d{2})", q)
        if m:
            vac["publish_date_from"] = m.group(1)
            vac["publish_date_to"] = m.group(2)
        filters["vacancies"] = vac

    # Лизинги (синонимы: договор лизинга, лизинговый договор)
    if re.search(r"лизинг|лизингов\w+\s+договор|договор\s+лизинга", q):
        le: Dict[str, Any] = {"has_leases": True}
        if re.search(r"активн|действующ", q):
            le["only_active"] = True
        m = re.search(r"догов[оа]р[а-яё\s]*с\s*(\d{4}-\d{2}-\d{2})\s*по\s*(\d{4}-\d{2}-\d{2})", q)
        if m:
            le["contract_date_from"] = m.group(1)
            le["contract_date_to"] = m.group(2)
        m = re.search(r"прекращен[а-яё\s]*с\s*(\d{4}-\d{2}-\d{2})\s*по\s*(\d{4}-\d{2}-\d{2})", q)
        if m:
            le["stop_date_from"] = m.group(1)
            le["stop_date_to"] = m.group(2)
        # Роль (синонимы)
        if re.search(r"лизингодател|арендодател", q):
            le["role"] = "Lessor"
        if re.search(r"лизингополучател|арендатор", q):
            le["role"] = "Lessee"
        # Коды классификатора
        cc = re.findall(r"\b\d{7}\b", q)
        if cc:
            le["classifier_codes"] = list(dict.fromkeys(cc))
        # Регион коды
        rcs = re.findall(r"\b(\d{2})\b\s*регион", q)
        if rcs:
            le["region_codes"] = list(dict.fromkeys(rcs))
        # Тексты
        m = re.search(r"лизинг\w*\s*(?:по|с)\s*([а-яa-z0-9\-\s]+)", q)
        if m:
            le["search_text"] = m.group(1).strip()
        filters["leases"] = le

    # Контракты (синонимы: госзакупки, тендеры, торги, госзаказ)
    if re.search(r"контракт|закупк|госконтракт|тендер|торг[аи]?|госзаказ", q):
        co: Dict[str, Any] = {}
        # Типы ФЗ
        if re.search(r"44[-\s]?фз|fz44", q):
            co["contract_type"] = "FZ44"
        elif re.search(r"223[-\s]?фз|fz223", q):
            co["contract_type"] = "FZ223"
        # Роль (синонимы)
        if re.search(r"поставщик|исполнител", q):
            co["role"] = "SUPPLIER"
        if re.search(r"заказчик|покупател", q):
            co["role"] = "CUSTOMER"
        # Даты
        m = re.search(r"(контракт|закупк)[а-яё\s]*с\s*(\d{4}-\d{2}-\d{2})\s*по\s*(\d{4}-\d{2}-\d{2})", q)
        if m:
            co["contract_date_from"] = m.group(2)
            co["contract_date_to"] = m.group(3)
        # Суммы (с учётом НМЦК/стоимость/цена)
        m = re.search(r"(нмцк|начальн[а-яё\s]*цен[аы]|стоимост[ьи]|сумм[аы])\s*от\s*([\d\s.,]+)\s*до\s*([\d\s.,]+)(?:\s*(?:руб|руб\.|р\.?|₽))?", q)
        if m:
            co["min_price"] = int(_to_number(m.group(2)))
            co["max_price"] = int(_to_number(m.group(3)))
        else:
            m = re.search(r"(нмцк|начальн[а-яё\s]*цен[аы]|стоимост[ьи]|сумм[аы])\s*до\s*([\d\s.,]+)(?:\s*(?:руб|руб\.|р\.?|₽))?", q)
            if m:
                co["max_price"] = int(_to_number(m.group(2)))
            m = re.search(r"(нмцк|начальн[а-яё\s]*цен[аы]|стоимост[ьи]|сумм[аы])\s*от\s*([\d\s.,]+)(?:\s*(?:руб|руб\.|р\.?|₽))?", q)
            if m:
                co["min_price"] = int(_to_number(m.group(2)))
        # Текст/термины
        m = re.search(r"по\s+предмет[ау]\s*([а-яa-z0-9\-\s]+)", q)
        if m:
            co["search_text"] = m.group(1).strip()
        # ОКПД2 явное упоминание
        if "окпд2" in q:
            okpd2 = re.findall(r"\b\d{2}\.\d{2}\.\d{2}\.\d{3}\b", q)
            if okpd2:
                co["okpd2_codes"] = okpd2
        # Регион
        m = re.search(r"регион[еу]?\s*(\d{2})", q)
        if m:
            co["region_code"] = m.group(1)
        filters["contracts"] = co

    # Запрос адреса (расширено: поддержка "в/по городу <city>")
    if re.search(r"адрес|в\s+городе|в\s+г\.|по\s+городу", q):
        ar: Dict[str, Any] = {}
        af: List[Dict[str, Any]] = []
        # Ищем город после "в" или "по" (регистронезависимо, берём оригинальный текст)
        m = re.search(r"(?i)(?:в|по)\s+(?:г\.|город[а-яё]*)\s*([А-Яа-яё\-\s]+?)(?=,|$)", query, flags=re.IGNORECASE)
        if m:
            city = m.group(1).strip()
            af.append({"city": city})
            ar["search_terms"] = [city]
        # регион код цифрами
        m = re.findall(r"\b(\d{2})\b\s*регион", q)
        for rc in m:
            af.append({"region_code": rc})
        if af:
            ar["address_filters"] = af
        if ar:
            filters["address_request"] = ar

    return {"filters": filters, "page": 1, "page_size": page_size}
