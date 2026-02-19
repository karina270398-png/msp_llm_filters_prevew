msp-llm-filters

Кратко
- Локальный веб‑UI и MCP-инструменты для поиска компаний по естественному языку с маппингом в тело запроса к API /api/v1/batchCardsByFilters (или preview-эндпоинт с фиксированными limit/offset).
- Конвертер NL→filters: правило‑based (по умолчанию) + опционально LLM (Ollama). В UI видно, какой парсер сработал.

Структура
- src/msp_llm_filters/server_batchcards.py — MCP-адаптер и HTTP‑клиент для BatchCards
- src/msp_llm_filters/webapp_batchcards.py — локальный веб‑UI
- src/msp_llm_filters/nl_converter_batchcards.py — конвертер NL→filters (правила/регэкспы)
- prompts/system_instructions_batchcards.md — системные инструкции для LLM (если используете Ollama)
- pyproject.toml — зависимости и entrypoints

Быстрый старт
1) Python 3.11+ (рекомендовано) и виртуальное окружение.
2) Установка:
   pip install -e .[dev]
3) Настройте .env (см. раздел «Переменные окружения»). Минимум — API_BASE_URL.
4) Запуск веб‑UI с авто‑перезагрузкой:
   uvicorn msp_llm_filters.webapp_batchcards:app --host 127.0.0.1 --port 8001 --reload
5) Откройте http://127.0.0.1:8001. Введите запрос на русском. Внизу страницы отображается «Парсер: llm/rule-based» и разбор filters.

Переменные окружения (.env)
- API_BASE_URL — базовый URL к /api/v1/batchCardsByFilters или .../batchCardsByFiltersPreview?limit=50&offset=0
- API_KEY — (необязательно) добавится как query-параметр key, если API это использует
- API_AUTH_BEARER — (необязательно) Authorization: Bearer <value>
- API_AUTH_HEADER_NAME / API_AUTH_HEADER_VALUE — (необязательно) произвольная заголовочная авторизация
- REQUEST_TIMEOUT_SECONDS — таймаут HTTP‑клиента (по умолчанию 30)
- DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE — ограничения пагинации для UI
- OLLAMA_BASE_URL, OLLAMA_MODEL — включают путь LLM. Если переменная не задана или чекбокс «Использовать LLM» снят, работает только rule‑based конвертер.

Поддерживаемые поля и правила конвертера (кратко)
- География: region_codes (Москва=77, МО=50, СПб=78), «NN регион», адресный поиск: «в/по городу <город>» → address_request.search_terms/address_filters.city
- Финансы: income_from/to, net_income_from/to; единицы «тыс/млн/млрд», иначе число трактуется как рубли и переводится в тысячи
- Динамика роста: finance_request.metrics=[INCOME], growth_from, years_count=3, year_by_year=true по фразам «стабильная динамика роста более X%»
- Контрагент: counterparty_type=ul/ip/fl; понимает отрицания «не ип» и т.п.; opf_codes учитывают отрицания
- Вакансии: has_vacancies, only_active, salary_min/max, text/only_name, источник HH, region_code, publish_date_*; распознаёт «ищут/нанимают/нужны/требуются …»
- Контракты: 44‑ФЗ/223‑ФЗ, роли (SUPPLIER/CUSTOMER), min/max_price, предмет (search_text), даты, регион, okpd2_codes при явном упоминании
- Лизинг: only_active, даты договора/прекращения, роль (Lessor/Lessee), classifier_codes, region_codes, search_text
- EGR‑статусы: базовые синонимы с нормализацией (можно расширять до кодов)
- МСП‑категории, ИТ‑аккредитация, контактные флаги и др.

Примеры запросов
- «аккредитованные ИТ‑компании в Москве, выручка которых составляет больше 2 млн р со стабильной динамикой роста более 5 %, которые ищут разработчиков»
  → filters включает: region_codes=["77"], only_it_companies=true, income_from=2000, finance_request{growth_from=5}, vacancies{text="разработчиков"}
- «по городу чебоксары, компании специализирующиеся на прокате машин, не ип»
  → counterparty_type='ul', search_terms=["прокате машин"], address_request{search_terms=["чебоксары"], address_filters:[{city:"чебоксары"}]}

CLI/скрипты
- msp-llm-filters — MCP STDIO‑сервер (инструменты)
- msp-batch-cards — MCP‑обёртка для компаний (BatchCards)

Тесты
- pytest -q — базовые тесты нормализации/конвертера (можно расширять)

Отладка и типовые проблемы
- 403 Forbidden и «Optional int parameter 'limit' cannot be null»: если API_BASE_URL уже содержит ?limit=50&offset=0, клиент не добавляет params повторно
- Не проставляется выручка/вакансии: убедитесь, что отключён чекбокс «Использовать LLM», перезапустите UI с --reload
- Порт занят: завершите процесс на 8001 (macOS: lsof -nP -iTCP:8001 -sTCP:LISTEN; kill PID) или запустите на другом порту

Где править правила
- src/msp_llm_filters/nl_converter_batchcards.py — добавляйте синонимы/регэкспы по разделам (финансы/вакансии/контракты/лизинг/адрес/прочее).
- При желании можно вынести словари синонимов в отдельный модуль/JSON/YAML — дайте знать, подготовим.
