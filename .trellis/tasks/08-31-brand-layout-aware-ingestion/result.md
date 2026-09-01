# Brand Layout-aware Ingestion — Result

## Status

Repository implementation, focused verification, controlled provider compatibility diagnostics, and the
two-document local v4 rebuild/activation gate are complete. Both scoped PDFs are active-ready with retained
v3 rollback versions. The task-focused gate, canonical brand eval, Compose check, and global diff/privacy
checks are green. The full repository backend gate is explicitly **not green** because unrelated dirty-worktree
format/lint, mypy, pytest, and local migration-state findings remain; a safe path-scoped commit is also pending
main-session staging review. The task therefore stays `in_progress`.

No SSH, push, server deployment, publication, news/business run, or production workflow was performed.

## Delivered contract

- Added deterministic v4 PDF quality routing, typed multi-page Layout projection, provider-neutral page/block
  DTOs, exact page/block offsets, page-local chunking, and conservative title/body card grouping.
- Retained executable v2/v3 parsing and chunking behavior, generic Markdown compatibility, immutable version
  coexistence, rollback, the 600-chunk cap, and unchanged public HTTP/MCP/persistence projections.
- Closed Zhipu raw Layout validation covers page identity/dimensions, index, canonical label, bbox,
  content limits, element/source conflicts, and all 25 official PP-DocLayoutV3 native roles. Image roles,
  including `header_image` and `footer_image`, are validated then excluded from brand text projection.
- Content-free OCR diagnostics preserve the generic public error while recording only an allowlisted failure
  class on attempt metadata/logs. Provider values, bodies, Markdown, layout content, bbox, paths, and exception
  context never enter the diagnostic contract.
- Layout roles and bbox hints remain ephemeral v4 parse/chunk data. No Alembic revision, stored bbox, public
  role field, alternate vector dimension, or retrieval SQL redesign was introduced.

## Controlled active-ready aggregate evidence

| Aggregate | Scoped PDF A | Scoped PDF B |
|---|---:|---:|
| Pages | 48 | 50 |
| Page sections | 48 | 48 |
| Canonical characters | 9,708 | 20,924 |
| Chunks | 359 | 468 |
| Complete embeddings | 359 | 468 |
| Maximum chunk characters | 465 | 269 |
| Embedding dimensions | 2,048 | 2,048 |

- All 827 chunks were exact slices of their page sections, and every chunk had one complete 2,048-dimensional
  Alibaba `qwen3-vl-embedding` vector.
- OCR identity was Zhipu `glm-ocr`; derivation identities were parser v4, chunker v4, and embedding input v2.
- Both ready v4 versions became active. Each document retained one old ready v3 version for rollback.
- Failed immutable v4 diagnostic-version counts were retained as 5/1; no failed version was rewritten or
  activated.
- The metadata-only provider probe observed exactly `header_image` and `footer_image`, with no corpus content
  or provider payload retained.

## Retrieval smoke

- The real hybrid retrieval smoke succeeded after one transient query-embedding `ConnectError` and one
  bounded operator retry.
- Top-5 results were all bound to page sections, both active v4 versions were represented, and aggregate source
  pages were `[6, 7, 13, 43, 11]`.
- No query or result text is recorded. This is a structural retrieval smoke, not a production accuracy or
  private-corpus quality score.

## Verification

- The final task-focused suite passed all 227 tests; no brand/layout test failed.
- Focused Ruff format/lint and strict mypy passed for the affected implementation surfaces.
- The canonical sanitized brand eval passed 36/36 cases: Recall@5 `0.95`, nDCG@5 `0.928633`, parent-diversity
  gain `+0.15`, and `0` policy violations.
- Compose configuration validation passed.
- Real PostgreSQL attempt-metadata coverage passed for the closed diagnostic reasons; immutable v3/v4
  coexistence, failed-job no-activation, and ready activation/rollback are covered. The repository has exactly
  one Alembic head, `0040`; the local database remains at `0038` because unrelated migrations are not applied,
  so repository-wide migration convergence is not green.
- Global `git diff --check`, privacy/credential scanning, and owned-path review passed. Exact-slice, sentinel,
  exception-context, and content-free diagnostic checks also passed.

### External blockers in the full backend gate

- Repository-wide formatting/lint is blocked by unrelated changes in models, weekly, title, and topic files.
- Repository-wide strict mypy is blocked by unrelated `local_exact_target_selection` `Literal` errors.
- Full pytest finished with 1,752 passed and 30 unrelated failures: 3 acquisition, 1 topic-rerank, and 26
  copy/IP-settings failures. No brand/layout test failed.
- These results do not constitute final full-backend acceptance, even though the task-owned scope is green.

## Pending finalization

- Resolve or explicitly scope out the unrelated repository-wide format/lint, mypy, pytest, and local database
  migration drift before declaring the final full backend gate accepted.
- The main session must scope staging and decide whether task-owned changes can be isolated for a safe local
  path-scoped commit. The commit step remains pending; do not push or deploy.

## Break-loop retrospective

- The five-part MaaS contract-drift analysis is recorded in
  [research/maas-layout-contract-drift-break-loop.md](research/maas-layout-contract-drift-break-loop.md).
- Its durable provider-schema-drift playbook is captured in
  [brand-knowledge-rag.md](../../spec/backend/brand-knowledge-rag.md). No corresponding Trellis template source
  exists for this project-local spec, so template synchronization is not applicable.
