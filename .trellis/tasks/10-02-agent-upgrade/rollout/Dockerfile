# Python-only overlay on the image production runs since 2026-10-02 13:31 (release 11ad19c, mainline ff398b2).
# Release de22d32: a blocked first draft is repaired by the tool-using agent first; full regeneration as fallback.
FROM offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:b8fa7adaecbf24b0c5371245b9f8fec40ca3ad31b43c1cb5e23d36427117cba2
COPY app/application/ports/copy_generation.py /app/app/application/ports/copy_generation.py
COPY app/application/services/copy_generation.py /app/app/application/services/copy_generation.py
COPY app/content_worker_main.py /app/app/content_worker_main.py
COPY app/core/config.py /app/app/core/config.py
COPY app/infrastructure/db/copy_generation.py /app/app/infrastructure/db/copy_generation.py
COPY files.txt /app/release-de22d32-files.txt
