Развертывание (Docker, self-hosted LLM, без DNS/HTTPS)

Цель: запустить локальную LLM (Ollama) и приложение (MCP + веб‑UI) в Docker на хосте 10.0.61.88. Доступ к UI будет по http://10.0.61.88:8000 (только через VPN).

Требования на хосте
- ОС: Linux (Debian 11 ок)
- Docker и Docker Compose v2 установлены (проверка: `docker --version`, `docker compose version`)
- Ресурсы: CPU 4+ vCPU, RAM ≥ 8 GB (свободно ≥ 4 GB), диск ≥ 10 GB
- Порты: 8000 (наружу), 11434 (локальный, только 127.0.0.1)

Шаг 0 — (опционально) освободить память
- Остановите тяжёлые контейнеры/сервисы, если они не нужны.
- Проверьте память: `free -h` (свободно ≥ 4 GB желательно)

Шаг 1 — Копируем проект на сервер
- Вариант A: git clone
  - `git clone <repo_url> && cd msp_llm_filters`
- Вариант B: загрузите архив/scp и распакуйте в каталог, затем `cd msp_llm_filters`

Шаг 2 — Создаём .env с настройками
- На сервере создайте файл `.env` рядом с docker-compose.yml и пропишите значения:

  API_BASE_URL=http://10.0.61.119:8092/api_ext/v1/arbitration/batch-cases
  API_KEY=<ВАШ_API_KEY>
  COURTS_URL=http://10.0.61.119:8092/api_ext/v1/dictionary/arbitration/courts
  DISPUTE_CATEGORIES_URL=http://10.0.61.119:8092/api_ext/v1/dictionary/arbitration/dispute-categories
  DOCUMENT_TYPES_URL=http://10.0.61.119:8092/api_ext/v1/dictionary/arbitration/document-types

  # LLM внутри docker-compose сети
  OLLAMA_BASE_URL=http://ollama:11434
  # Модель (начните с 3B для скорости/экономии ОЗУ)
  OLLAMA_MODEL=qwen2.5:3b-instruct-q4_K_M

- Никогда не коммитьте .env в Git. Храните копию отдельно.

Шаг 3 — Собираем и поднимаем контейнеры
- Из корня проекта:
  - `docker compose up -d --build`
- Проверьте, что сервисы поднялись:
  - `docker compose ps`

Шаг 4 — Загрузка модели в Ollama (однократно)
- Выполните в контейнере ollama:
  - `docker exec -it ollama ollama pull qwen2.5:3b-instruct-q4_K_M`
- (Позже можно сменить модель на 7B: `ollama pull qwen2.5:7b-instruct-q4_K_M` и обновить OLLAMA_MODEL в .env)

Шаг 5 — Проверка доступности UI
- На сервере:
  - `curl -I http://127.0.0.1:8000/` должно вернуть 200
- С рабочей машины (по VPN):
  - Откройте `http://10.0.61.88:8000`

Шаг 6 — Как останавливать/обновлять
- Остановить:
  - `docker compose down`
- Перезапустить с пересборкой:
  - `docker compose up -d --build`
- Логи:
  - `docker compose logs -f app`
  - `docker compose logs -f ollama`

Шаг 7 — Смена модели / ресурсы
- Для скорости/качества можно:
  - 3B (минимум ресурсов): `qwen2.5:3b-instruct-q4_K_M`
  - 7B (лучше понимание): `qwen2.5:7b-instruct-q4_K_M`
- При смене модели:
  - `docker exec -it ollama ollama pull <MODEL>`
  - Обновите OLLAMA_MODEL в .env
  - `docker compose restart app`

Шаг 8 — Безопасность
- Порт 11434 открыт только на 127.0.0.1 (локально на сервере). Наружу публикуется только 8000.
- Доступ к серверу только через VPN — DNS/HTTPS не требуются.

FAQ / проблемы
- Недостаточно памяти (OOM):
  - Освободите ОЗУ (остановите неиспользуемые контейнеры/сервисы)
  - Временно добавьте swap (не рекомендуется надолго, но помогает):
    - `dd if=/dev/zero of=/swapfile bs=1G count=8 && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile`
    - `echo '/swapfile none swap sw 0 0' >> /etc/fstab`
- UI не открывается:
  - `docker compose logs -f app` — смотрим, нет ли ошибок подключения к API 10.0.61.119:8092
  - проверьте доступность вашего API c сервера: `curl -I http://10.0.61.119:8092`
- LLM не отвечает:
  - `docker compose logs -f ollama`
  - проверьте модель: `docker exec -it ollama ollama list` и `ollama pull ...`

Готово. После этих шагов приложение будет доступно по адресу: http://10.0.61.88:8000 (через VPN).
