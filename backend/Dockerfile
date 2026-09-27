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
ARG DEBIAN_SNAPSHOT=20260901T000000Z
ARG FONTS_NOTO_CJK_VERSION=1:20220127+repack1-1

LABEL org.opencontainers.image.created="${BUILD_CREATED}" \
      org.opencontainers.image.revision="${CODEUP_COMMIT}" \
      org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.base.name="${PYTHON_BASE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:${PATH}

RUN rm /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' "deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}/ bookworm main" > /etc/apt/sources.list \
    && apt-get update \
    && apt-get install --yes --download-only --no-install-recommends "fonts-noto-cjk=${FONTS_NOTO_CJK_VERSION}" \
    && printf '%s  %s\n' 4a2515eb6db3978b897fef9709ed0d2b1f4c6c4df4d83d6c4ef65f71f1b1f502 '/var/cache/apt/archives/fonts-noto-cjk_1%3a20220127+repack1-1_all.deb' | sha256sum --check - \
    && apt-get install --yes --no-install-recommends "fonts-noto-cjk=${FONTS_NOTO_CJK_VERSION}" \
    && test "$(dpkg-query -W -f='${Version}' fonts-noto-cjk)" = "${FONTS_NOTO_CJK_VERSION}" \
    && test -f /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
    && test ! -L /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
    && printf '%s  %s\n' b76b0433203017ca80401b2ee0dd69350349871c4b19d504c34dbdd80541690a /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc | sha256sum --check - \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app
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
