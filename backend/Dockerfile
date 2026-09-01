ARG PYTHON_BASE=python:3.11.15-slim-bookworm@sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3

FROM ${PYTHON_BASE} AS dependencies

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:${PATH}

RUN python -m venv "${VIRTUAL_ENV}"
COPY requirements/runtime.lock /tmp/runtime.lock
RUN python -m pip install --require-hashes --no-deps -r /tmp/runtime.lock \
    && python -m pip check

FROM ${PYTHON_BASE} AS runtime

ARG PYTHON_BASE
ARG CODEUP_COMMIT=local
ARG SOURCE_URL=local
ARG BUILD_CREATED=1970-01-01T00:00:00Z

LABEL org.opencontainers.image.created="${BUILD_CREATED}" \
      org.opencontainers.image.revision="${CODEUP_COMMIT}" \
      org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.base.name="${PYTHON_BASE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:${PATH}

RUN groupadd --system app && useradd --system --gid app --home-dir /app app
WORKDIR /app

COPY --from=dependencies /opt/venv /opt/venv
COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN python -m pip check \
    && mkdir -p /app/output \
    && chown -R app:app /app

USER app

CMD ["python", "-m", "uvicorn", "app.api_main:app", "--host", "0.0.0.0", "--port", "8000"]
