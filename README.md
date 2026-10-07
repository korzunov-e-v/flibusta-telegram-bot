# 📚 Flibusta Telegram Bot

Telegram-бот для поиска и скачивания книг с Flibusta.

### Возможности

* 🔍 Поиск книг по названию и автору, выдача с пагинацией
* 📖 Просмотр информации и аннотации
* ⬇️ Скачивание в `fb2`, `epub`, `mobi`, `pdf`, `djvu`
* 📩 Отправка книг на E-mail
* ✅ Подтверждение E-mail кодом из письма
* 🚦 Суточный лимит писем на пользователя (`EMAIL_DAILY_LIMIT`)
* 💾 Хранение E-mail пользователей в PostgreSQL
* 🐳 Запуск через Docker Compose

### Команды бота

```text
/start   — начать работу
/help    — справка
/email   — посмотреть или изменить E-mail
/cancel  — отменить текущее действие (например, ввод E-mail)
```

Любое другое текстовое сообщение — поисковый запрос.

### Переменные окружения

Все настройки читаются из `.env`. Образец с комментариями — [`template.env`](template.env).

| Переменная | Обязательна | По умолчанию | Назначение |
|---|---|---|---|
| `TOKEN` | да | — | токен Telegram-бота |
| `ADMINS` | да | — | id администратора; несколько — через запятую |
| `SMTP_USER`, `SMTP_PASS` | да | — | учётная запись SMTP |
| `SMTP_HOST`, `SMTP_PORT` | нет | `smtp.gmail.com`, `587` | SMTP-сервер |
| `POSTGRES_PASSWORD` | да | — | пароль БД |
| `POSTGRES_DB`, `POSTGRES_USER` | да для Docker | `flibusta` | база и пользователь (compose подставляет их в контейнер postgres) |
| `POSTGRES_HOST`, `POSTGRES_PORT` | нет | `localhost`, `5432` | в Docker задаются в `docker-compose.yml` (`postgres:5432`) |
| `FLIBUSTA_URL` | нет | `https://flibusta.is` | адрес сайта или зеркала |
| `EMAIL_DAILY_LIMIT` | нет | `10` | писем в сутки на пользователя |
| `DATA_DIR` | нет | `data` | каталог с файлом состояния бота; в Docker — `/srv/data` |
| `SMTP_TIMEOUT` | нет | `30` | таймаут SMTP, секунды |
| `MAX_CHAT_FILE_MB`, `MAX_EMAIL_FILE_MB` | нет | `50`, `18` | предельный размер файла при отправке в чат и на почту |

URL подключения к БД собирается из `POSTGRES_*`, отдельной переменной для него нет.

### Запуск в Docker

```bash
git clone https://github.com/korzunov-e-v/flibusta-telegram-bot.git
cd flibusta-telegram-bot
cp template.env .env   # и заполнить
make build
make up
```

Миграции применяются автоматически при старте контейнера бота.

* Данные PostgreSQL лежат в volume `postgres_data`, состояние бота — в volume `bot_data`; оба переживают пересоздание контейнеров.
* Порт PostgreSQL наружу не публикуется.
* Логи пишутся в stdout в формате JSON: `make logs`. Размер docker-логов ограничен (5 файлов по 10 МБ на контейнер).

### Команды make

```text
make build      — собрать образ
make up         — запустить в фоне
make down       — остановить
make logs       — последние 100 строк логов
make restart    — перезапустить бота
make exec       — shell в контейнере бота
make dev        — запуск с оверлеем разработки (docker-compose.dev.yml)
make dev-down   — остановить окружение разработки
make migrate    — alembic upgrade head в одноразовом контейнере
make lint       — ruff check
make format     — ruff format + автоисправления
make typecheck  — mypy
make test       — pytest
make check      — lint + typecheck + test
```

### Локальная разработка

Нужны Python 3.12 и [Poetry](https://python-poetry.org/) 2.x.

```bash
poetry config virtualenvs.in-project true   # окружение в ./.venv
poetry install                              # зависимости + dev-группа
cp template.env .env
```

`make lint / format / typecheck / test` вызывают инструменты из `./.venv/bin/`.
Если окружение в другом месте: `make test VENV_BIN="poetry run "`.

**Вариант 1 — всё в Docker.** `make dev` поднимает те же контейнеры с оверлеем
`docker-compose.dev.yml`: PostgreSQL доступен на `127.0.0.1:5432`, каталог `./src`
смонтирован в контейнер поверх кода из образа. После правок кода — `make restart`.

**Вариант 2 — бот с хоста.** Нужен только PostgreSQL из compose; в `.env` должно быть
`POSTGRES_HOST=localhost`.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres
PYTHONPATH=. .venv/bin/alembic upgrade head
PYTHONPATH=. .venv/bin/python src/srv.py
```

Новая миграция:

```bash
PYTHONPATH=. .venv/bin/alembic revision --autogenerate -m "описание"
```

Pre-commit (ruff): `pip install pre-commit && pre-commit install`.

### CI и деплой

GitHub Actions (`.github/workflows/deploy.yml`): на каждый push в `master` и pull request
запускаются `ruff`, `mypy` и `pytest`. Деплой на сервер (`git pull && make build && make up`
по ssh) выполняется только после успешных проверок и только для `master`
(push или ручной запуск).
