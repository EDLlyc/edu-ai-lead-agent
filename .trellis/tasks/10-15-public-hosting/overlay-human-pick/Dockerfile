FROM offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:0ab05e2e9afd3afb55ee299ea2641d3374614aa35e1d845da3884c29e3bf0e6c
ARG FIX_COMMIT
LABEL org.opencontainers.image.revision=$FIX_COMMIT
LABEL edu-ai.change="admin-human-pick"
COPY --chown=0:0 tree/app/api/v1/routes/admin_human_picks.py /app/app/api/v1/routes/admin_human_picks.py
COPY --chown=0:0 tree/app/api/v1/routes/admin_news_reviews.py /app/app/api/v1/routes/admin_news_reviews.py
COPY --chown=0:0 tree/app/api_main.py /app/app/api_main.py
COPY --chown=0:0 tree/app/application/services/visitor_display.py /app/app/application/services/visitor_display.py
COPY --chown=0:0 tree/app/infrastructure/db/visitor_display.py /app/app/infrastructure/db/visitor_display.py
COPY --chown=0:0 tree/app/schemas/visitor_display.py /app/app/schemas/visitor_display.py
