FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN groupadd --gid 10001 fluvius \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin fluvius \
    && mkdir -p /app/storage \
    && chown -R fluvius:fluvius /app/storage

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
