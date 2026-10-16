FROM offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:da05208214aa273084fd2bccb9ce86dbdc1c0ee2069a855706a5d058686e2df7
ARG FIX_COMMIT
LABEL org.opencontainers.image.revision=$FIX_COMMIT
LABEL edu-ai.change="acquisition-skip-unreadable-page"
COPY --chown=0:0 tree/app/application/services/execute_acquisition.py /app/app/application/services/execute_acquisition.py
