# Python-only overlay on the image production runs since 2026-10-01 23:12 (release 765fe1e, mainline 60bc652).
# Release 11ad19c: the controlled planner avoids a subject+cast whose fresh action pool is empty or low.
FROM offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:5887bce7440dee1bea94a9a32026e58403a78ccd7e4a0d2016fbace8d768980e
COPY app/application/services/material_package.py /app/app/application/services/material_package.py
COPY app/domain/visual_assets.py /app/app/domain/visual_assets.py
COPY app/domain/visual_diversity.py /app/app/domain/visual_diversity.py
COPY evals/visual_replay/plan_sim.py /app/evals/visual_replay/plan_sim.py
COPY files.txt /app/release-11ad19c-files.txt
