FROM python:3.11.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system app && useradd --system --gid app --home-dir /app app
WORKDIR /app

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN python -m pip install --upgrade pip && python -m pip install .

USER app

CMD ["python", "-m", "uvicorn", "app.api_main:app", "--host", "0.0.0.0", "--port", "8000"]
