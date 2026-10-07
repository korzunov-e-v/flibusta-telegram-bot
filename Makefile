COMPOSE     := docker compose -f docker-compose.yml
COMPOSE_DEV := $(COMPOSE) -f docker-compose.dev.yml
SERVICE     := tg-bot
# Инструменты разработки берутся из локального окружения (poetry install создаёт .venv,
# см. README). Можно переопределить: make test VENV_BIN="poetry run"
VENV_BIN    ?= .venv/bin/

.PHONY: build up down logs restart exec dev dev-down migrate lint format typecheck test check

build:
	$(COMPOSE) build
up:
	$(COMPOSE) up -d
down:
	$(COMPOSE) down
logs:
	$(COMPOSE) logs --tail=100
restart:
	$(COMPOSE) restart $(SERVICE)
exec:
	$(COMPOSE) exec $(SERVICE) /bin/sh

# разработка: postgres на 127.0.0.1:5432, ./src смонтирован в контейнер
dev:
	$(COMPOSE_DEV) up -d --build
dev-down:
	$(COMPOSE_DEV) down

# миграции в одноразовом контейнере бота (postgres поднимется сам)
migrate:
	$(COMPOSE) run --rm $(SERVICE) alembic upgrade head

lint:
	$(VENV_BIN)ruff check .
	$(VENV_BIN)ruff format --check .
format:
	$(VENV_BIN)ruff format .
	$(VENV_BIN)ruff check --fix .
typecheck:
	$(VENV_BIN)mypy src
test:
	$(VENV_BIN)pytest

check: lint typecheck test
