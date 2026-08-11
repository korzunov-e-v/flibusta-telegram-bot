FROM python:3.12

ENV PYTHONPATH /srv

WORKDIR /srv

COPY pyproject.toml poetry.lock alembic.ini /srv/

RUN pip install poetry=="1.8.3" && \
    poetry config virtualenvs.create false && \
    poetry install

COPY src ./src

CMD python src/srv.py
