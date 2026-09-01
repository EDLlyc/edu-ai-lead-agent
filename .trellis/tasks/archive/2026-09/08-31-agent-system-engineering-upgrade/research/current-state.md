# Current-state evidence

- `backend/app/application/services/ip_assets.py:129-131,938-997` owns the current 0.65 metadata / 0.35 semantic direct score blend.
- `.trellis/spec/backend/brand-knowledge-rag.md:150-190` documents the existing FTS + pgvector weighted RRF, parent-aware selection and retrieval evaluation pattern.
- `backend/app/domain/official_account_weekly_edition.py:27-33,403-475,628-714` owns weekly identity, Shanghai schedule and three-role selection.
- `backend/app/application/services/official_account_weekly_edition.py:329-568` owns existing immutable three-child aggregate and writer.
- `backend/app/domain/agent_workbench.py:54-90,158-229` owns Workbench limits, trace entries, usage and run trace validation.
- `backend/app/application/services/agent_tools.py:68-90` enforces the current Workbench closed-world/read-only tool boundary.
- `.trellis/tasks/08-27-official-account-editor-automation-v2/implement.md` records the completed-but-uncommitted weekly artifact phases; the new DAG must layer over those files instead of recreating them.
- The repository currently has many unrelated uncommitted changes and Alembic head `20260827_0037`; child migrations must be created sequentially from the head visible at implementation time.

## Planning consequence

The parent owns sequencing and integration only. IP V3 is independent and can ship first. Agent governance must ship before the weekly DAG so the latter consumes one shared trace/budget/permission contract. The IP anonymous funnel remains deliberately separate from Agent trace storage.
