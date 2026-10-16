FROM offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:a3a3e7f766646415caf89688961e2289daa04fae5a8b0445ca1059f6da485a06
ARG FIX_COMMIT
LABEL org.opencontainers.image.revision=$FIX_COMMIT
LABEL edu-ai.change="builtin-phrases-worker"
COPY --chown=0:0 tree/app/domain/builtin_phrases.py /app/app/domain/builtin_phrases.py
COPY --chown=0:0 tree/app/domain/copy_generation.py /app/app/domain/copy_generation.py
COPY --chown=0:0 tree/app/infrastructure/db/builtin_phrases.py /app/app/infrastructure/db/builtin_phrases.py
COPY --chown=0:0 tree/app/infrastructure/db/models.py /app/app/infrastructure/db/models.py
COPY --chown=0:0 tree/app/infrastructure/db/content_slots.py /app/app/infrastructure/db/content_slots.py
COPY --chown=0:0 tree/app/infrastructure/db/content_slot_human_picks.py /app/app/infrastructure/db/content_slot_human_picks.py
COPY --chown=0:0 tree/app/infrastructure/db/copy_generation.py /app/app/infrastructure/db/copy_generation.py
COPY --chown=0:0 tree/app/infrastructure/db/human_pick_review.py /app/app/infrastructure/db/human_pick_review.py
