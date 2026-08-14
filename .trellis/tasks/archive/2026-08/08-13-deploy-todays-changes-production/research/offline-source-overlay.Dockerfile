ARG DEPENDENCY_BASE_IMAGE
FROM ${DEPENDENCY_BASE_IMAGE}

ARG RELEASE_COMMIT
ARG DEPENDENCY_BASE_DIGEST
ARG DEPENDENCY_INPUT_SHA256

LABEL org.opencontainers.image.revision="${RELEASE_COMMIT}" \
      io.trellis.dependency-base.digest="${DEPENDENCY_BASE_DIGEST}" \
      io.trellis.dependency-input.pyproject-sha256="${DEPENDENCY_INPUT_SHA256}"

USER root
WORKDIR /app

# The dependency base was built with `pip install .`, which left source copies in
# the build tree and site-packages. Remove every old application copy before the
# complete, checksum-verified target tree is overlaid. Installed third-party
# dependencies and distribution metadata remain intact.
RUN set -eu; \
    site_packages="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"; \
    rm -rf \
        /app/app \
        /app/alembic \
        /app/build \
        /app/edu_ai_lead_agent_backend.egg-info \
        "${site_packages}/app"; \
    rm -f \
        /app/alembic.ini \
        /app/pyproject.toml \
        /app/.release-source.sha256

COPY --chown=app:app pyproject.toml alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app
COPY --chown=app:app .release-source.sha256 ./.release-source.sha256

USER app
