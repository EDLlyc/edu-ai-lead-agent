FROM offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:98b9d189dd623b0ff7a8818c481b30e044a911402508c48b43f7c10a1359acfe
ARG FIX_COMMIT
LABEL org.opencontainers.image.revision=$FIX_COMMIT
LABEL edu-ai.change="builtin-phrases"
COPY --chown=0:0 tree/app/api/v1/routes/admin_builtin_phrases.py /app/app/api/v1/routes/admin_builtin_phrases.py
COPY --chown=0:0 tree/app/api_main.py /app/app/api_main.py
COPY --chown=0:0 tree/app/schemas/admin_builtin_phrases.py /app/app/schemas/admin_builtin_phrases.py
COPY --chown=0:0 tree/app/domain/builtin_phrases.py /app/app/domain/builtin_phrases.py
COPY --chown=0:0 tree/app/domain/copy_generation.py /app/app/domain/copy_generation.py
COPY --chown=0:0 tree/app/infrastructure/db/builtin_phrases.py /app/app/infrastructure/db/builtin_phrases.py
COPY --chown=0:0 tree/app/infrastructure/db/models.py /app/app/infrastructure/db/models.py
COPY --chown=0:0 tree/app/infrastructure/db/content_slots.py /app/app/infrastructure/db/content_slots.py
COPY --chown=0:0 tree/app/infrastructure/db/content_slot_human_picks.py /app/app/infrastructure/db/content_slot_human_picks.py
COPY --chown=0:0 tree/app/infrastructure/db/copy_generation.py /app/app/infrastructure/db/copy_generation.py
COPY --chown=0:0 tree/app/infrastructure/db/human_pick_review.py /app/app/infrastructure/db/human_pick_review.py
COPY --chown=0:0 tree/alembic/versions/20261016_0063_builtin_phrases.py /app/alembic/versions/20261016_0063_builtin_phrases.py
