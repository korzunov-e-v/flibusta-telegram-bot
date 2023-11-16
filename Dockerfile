FROM python:3.10.0-alpine

ENV PYTHONPATH /srv
WORKDIR /srv
COPY requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY .env ./.env
COPY src ./src


