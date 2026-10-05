# Итоговый образ: только то, что нужно на проде
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 service && chown -R service:service /app
USER service

EXPOSE 8000

# gunicorn, а не runserver: рабочий сервер разработки на проде не используют
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]

# Стенд и CI: то же самое плюс pytest, ruff и прочий инструмент.
#
# Отдельной стадией, потому что тащить всё это в итоговый образ незачем:
# лишние пакеты это лишние уязвимости и лишние сто мегабайт.
FROM base AS dev

USER root
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
USER service
