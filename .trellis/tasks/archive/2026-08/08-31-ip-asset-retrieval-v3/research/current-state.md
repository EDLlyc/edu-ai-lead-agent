# Current-state evidence

- `backend/app/application/services/ip_assets.py:129-131` freezes the current semantic `0.35` and metadata `0.65` weights.
- `backend/app/application/services/ip_assets.py:402-447` performs current-turn filter inference, metadata retrieval, embedding retrieval and truthful degraded fallback.
- `backend/app/application/services/ip_assets.py:938-997` merges raw metadata and normalized cosine scores and owns stable ties.
- `.trellis/spec/backend/ip-asset-hub.md:208-235` requires metadata-only candidates to survive partial indexing and explicit filters to remain authoritative.
- `backend/app/infrastructure/db/models.py:5390` and `backend/app/infrastructure/db/ip_assets.py:582-629` show the existing anonymous daily download aggregate pattern.
- `backend/evals/brand_retrieval/` demonstrates provider-free dataset hashing, production-function reuse, Recall/MRR/nDCG, canonical reports and oracle-isolation checks.
- `.trellis/spec/backend/database-guidelines.md:149-152` explicitly forbids calling PostgreSQL `ts_rank` BM25 and recommends documented rank fusion.

## Planning consequence

V3 should replace only the rank-combination policy, not filter extraction, vector identity, provider fallback or access control. Telemetry must follow the daily aggregate pattern and must not add a search-event or user/session table.
