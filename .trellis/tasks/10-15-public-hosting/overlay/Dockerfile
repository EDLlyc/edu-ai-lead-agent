FROM offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:a3a3e7f766646415caf89688961e2289daa04fae5a8b0445ca1059f6da485a06
ARG FIX_COMMIT
LABEL org.opencontainers.image.revision=$FIX_COMMIT
LABEL org.opencontainers.image.base.name="offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:a3a3e7f766646415caf89688961e2289daa04fae5a8b0445ca1059f6da485a06"
LABEL edu-ai.change="admin-session-cookie-domain"
COPY --chown=0:0 app/core/config.py /app/app/core/config.py
COPY --chown=0:0 app/api/v1/routes/admin.py /app/app/api/v1/routes/admin.py
