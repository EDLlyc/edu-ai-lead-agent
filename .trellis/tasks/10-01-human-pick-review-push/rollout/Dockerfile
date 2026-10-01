# Python-only overlay on the image production runs since 2026-10-01 22:30 (app = mainline 1d4d8b2).
# Release on 1d4d8b2: selection fresh pool + human-pick review/push + before/after edit pairs.
FROM offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:7bffe4edfe8cc073b081e7e4d71eb175697f99383745472f0ec407000cff5646
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
