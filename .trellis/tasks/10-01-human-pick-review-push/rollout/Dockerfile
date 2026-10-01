# Python-only overlay on the image production runs since 2026-09-30 15:56 (app = mainline 3a79c22).
# Release f4ff3a4 = selection fresh pool (db69ffd) + human-pick review/push (f4ff3a4), on d7de3c4.
FROM offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:30f6cd0e176b6b1645282f1654472ad4d4882b77a2b39a4c93888921dcd3c25e
COPY app/api/v1/routes/content_slots.py /app/app/api/v1/routes/content_slots.py
COPY app/application/services/human_pick_review.py /app/app/application/services/human_pick_review.py
COPY app/application/services/wecom_delivery.py /app/app/application/services/wecom_delivery.py
COPY app/domain/human_pick_review.py /app/app/domain/human_pick_review.py
COPY app/infrastructure/db/content_slot_human_picks.py /app/app/infrastructure/db/content_slot_human_picks.py
COPY app/infrastructure/db/copy_generation.py /app/app/infrastructure/db/copy_generation.py
COPY app/infrastructure/db/human_pick_review.py /app/app/infrastructure/db/human_pick_review.py
COPY app/infrastructure/db/topic_selection.py /app/app/infrastructure/db/topic_selection.py
COPY app/schemas/content_slots.py /app/app/schemas/content_slots.py
COPY files.txt /app/release-f4ff3a4-files.txt
