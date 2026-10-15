FROM offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:e008f5f8c0d8634fdd314cb007f9a4583271fbe9d21a9ea2fea1237936063ecc
ARG FIX_COMMIT
LABEL org.opencontainers.image.revision=$FIX_COMMIT
LABEL edu-ai.change="admin-news-review"
COPY --chown=0:0 tree/alembic/versions/20261015_0062_news_reviews.py /app/alembic/versions/20261015_0062_news_reviews.py
COPY --chown=0:0 tree/app/api/v1/routes/admin_news_reviews.py /app/app/api/v1/routes/admin_news_reviews.py
COPY --chown=0:0 tree/app/api_main.py /app/app/api_main.py
COPY --chown=0:0 tree/app/application/services/visitor_display.py /app/app/application/services/visitor_display.py
COPY --chown=0:0 tree/app/application/services/visitor_improvement.py /app/app/application/services/visitor_improvement.py
COPY --chown=0:0 tree/app/application/services/visitor_moments.py /app/app/application/services/visitor_moments.py
COPY --chown=0:0 tree/app/infrastructure/db/models.py /app/app/infrastructure/db/models.py
COPY --chown=0:0 tree/app/infrastructure/db/news_reviews.py /app/app/infrastructure/db/news_reviews.py
COPY --chown=0:0 tree/app/infrastructure/db/visitor_display.py /app/app/infrastructure/db/visitor_display.py
COPY --chown=0:0 tree/app/infrastructure/db/visitor_improvement.py /app/app/infrastructure/db/visitor_improvement.py
COPY --chown=0:0 tree/app/infrastructure/db/visitor_moments.py /app/app/infrastructure/db/visitor_moments.py
COPY --chown=0:0 tree/app/infrastructure/db/visitor_report.py /app/app/infrastructure/db/visitor_report.py
COPY --chown=0:0 tree/app/infrastructure/visitor_review_store.py /app/app/infrastructure/visitor_review_store.py
COPY --chown=0:0 tree/app/schemas/visitor_display.py /app/app/schemas/visitor_display.py
