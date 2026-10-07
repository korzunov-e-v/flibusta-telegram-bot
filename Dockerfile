# syntax=docker/dockerfile:1

# --- сборка зависимостей: poetry остаётся в этом слое и в итоговый образ не попадает
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    POETRY_CACHE_DIR=/tmp/poetry-cache

WORKDIR /srv

RUN pip install "poetry==2.5.1"

COPY pyproject.toml poetry.lock ./

RUN poetry install --only main --no-interaction --no-ansi && \
    rm -rf "$POETRY_CACHE_DIR"


# --- итоговый образ
FROM python:3.12-slim

ENV PYTHONPATH=/srv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/srv/.venv/bin:$PATH"

WORKDIR /srv

# /srv/data создаём заранее с нужным владельцем: named volume при первом
# монтировании наследует права каталога из образа
RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --no-create-home --home-dir /srv --shell /usr/sbin/nologin app && \
    mkdir -p /srv/data && \
    chown app:app /srv /srv/data

COPY --from=builder /srv/.venv /srv/.venv
COPY alembic.ini ./
COPY src ./src

USER app

CMD ["python", "src/srv.py"]
