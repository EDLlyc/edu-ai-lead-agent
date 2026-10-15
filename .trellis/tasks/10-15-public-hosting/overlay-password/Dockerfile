FROM offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:e2372099fc74a822f5eafc49c6fba6c9a22829a8b6a79142886f480d5158f255
ARG FIX_COMMIT
LABEL org.opencontainers.image.revision=$FIX_COMMIT
LABEL edu-ai.change="admin-account-chosen-password"
COPY --chown=0:0 app/domain/admin_auth.py /app/app/domain/admin_auth.py
COPY --chown=0:0 app/application/services/admin_accounts.py /app/app/application/services/admin_accounts.py
COPY --chown=0:0 app/schemas/admin.py /app/app/schemas/admin.py
COPY --chown=0:0 app/api/v1/routes/admin_accounts.py /app/app/api/v1/routes/admin_accounts.py
COPY --chown=0:0 app/admin_users_main.py /app/app/admin_users_main.py
