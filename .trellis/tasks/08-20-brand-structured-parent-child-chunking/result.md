# Implementation Result

## Status

Backend implementation, compatibility review and final engineering gates are complete. The original
provider-free controlled-material acceptance is complete. A separately authorized one-attempt OCR-only
gate was executed on 2026-08-21 and failed closed during local post-provider chunk validation. After the
local fix and green independent review, one separately authorized post-fix HTTP attempt completed the
aggregate validation successfully. No production, deployment, database write, re-ingestion, embedding,
activation, downstream business flow, commit or push action was performed.

## Delivered

- Added typed page/Q&A/heading/generic parent sections, chunk-level content and claim metadata, exact
  canonical offsets, deterministic identities and one contextual embedding-input builder.
- Refactored PDF parsing to retain non-empty source pages and split parent-local card blocks; refactored
  DOCX parsing to retain paragraph/table order and question-answer parents, with generic/OCR fallback.
- Added Alembic head `20260820_0023`, `brand_sections`, structured chunk fields, contextual FTS and a
  null-safe historical backfill that preserves raw chunks and vectors.
- Bound ingestion claims and stale-lease recovery to the exact parser/chunk/input/provider/model identity;
  persistence now writes sections, chunks and existing 2048-dimensional embeddings in FK order.
- Preserved executable rollback behavior: the exact v2 bundle replays whole-document PDF/DOCX parsing,
  global overlap, legacy keys, raw embedding input and nullable parent metadata; the v3 bundle uses
  structured parents and contextual input. Mixed or unknown bundles fail closed before job creation.
- Added version-dispatched retrieval: v3 prefers unseen parent sections before repeated children, while
  v2 retains adjacent-global-ordinal compatibility. HTTP, copy generation and Agent Workbench expose the
  same null-safe typed metadata, and the affected API/types and offline baseline were regenerated.
- Made external-claim classification conservative for policy, market, award, certification, financing,
  proportion and third-party cooperation signals even without a numeric value; external scope takes
  priority over normative rules and always requires verification.
- Fixed the observed v3 generic OCR chunk-budget failure without changing the hard cap: ordinary
  boundaries are retained when they fit; pathological tiny blocks are coalesced only within their
  parent, with a continuous parent-local bounded fallback and terminal rejection when content truly
  cannot fit. Frozen v2 behavior remains byte/fingerprint compatible.
- Synchronized parser/chunk/input/retrieval defaults, Compose, Doctor, release migration declaration and
  backend specifications. Qwen3-VL was neither added nor called.
- Added a provider-free brand-text retrieval policy evaluation with 36 sanitized cases balanced
  across all nine content types. The evaluator uses the same domain-owned weighted RRF and frozen
  v2/current v3 selector as PostgreSQL, while keeping graded relevance scorer-only. Checked JSON and
  Markdown reports include an explicit fixture-only disclaimer and no private corpus content.
- Updated the public one-page internship resume with final Recall@5 and nDCG@5 from the sanitized
  offline evaluation. The resume omits fixture count and legacy-policy comparison, while retaining
  the offline boundary rather than presenting the metrics as live/private-corpus accuracy.
- Reworked the internship highlights so the implemented LangGraph bounded tool loop, Typed Tool
  Registry/MCP surface, autonomous tool ordering, observation synthesis, cited answers, call budget,
  strict schemas, and deterministic fallback are visible instead of presenting the system as only a
  scheduled content pipeline.
- Registered the existing read-only fixture Agent Workbench MCP server in the local Codex client over
  STDIO and verified a real Codex-originated four-tool chain. The chain completed `search_evidence`,
  `get_event`, `retrieve_brand_context` and `validate_copy` in the requested order with no tool error;
  only aggregate counts/statuses were retained, and no production database, provider or delivery path
  was available to the server.

## Verification

- Focused post-compatibility brand/copy/Agent unit and contract suite: 166 passed.
- Real PostgreSQL/pgvector brand, clean migration, metadata drift, historical upgrade/downgrade and
  migration-head contract suite: 5 passed.
- Final `make backend-check`: Ruff format/lint, strict mypy over 170 source files and 1176 backend tests
  passed with 82% coverage.
- Final release pipeline contract slice: 13 passed; the broader focused release suite previously passed
  54 tests.
- Provider-free Agent Workbench evaluation: 42/42 passed; checked reports synchronized.
- Ruff format/lint: passed. Strict mypy: 170 source files passed.
- Production and Agent OpenAPI checks plus generated frontend type drift checks: passed.
- Frontend TypeScript and ESLint checks: passed.
- Compose validation, Doctor shell syntax, migration compilation, task-context validation,
  `git diff --check` and scoped privacy/Qwen integration scans: passed.
- Brand retrieval evaluation: 36/36 cases passed. Legacy v2 versus structured v3 macro metrics were
  Recall@5 80.00% -> 95.00%, MRR@5 100.00% -> 100.00%, nDCG@5 84.37% -> 92.86%, and parent
  diversity@5 85.00% -> 100.00%. External-claim verification coverage was 100% for both and
  brand-as-fact violations were zero. These are sanitized fixture retrieval-policy results, not live
  embedding or private-corpus accuracy claims.
- Focused post-eval gate: 49 brand retrieval/knowledge tests passed; Ruff, strict mypy over the
  affected production/eval sources, `make brand-retrieval-eval`, and canonical drift checks passed.
- Final post-eval `make backend-check`: Ruff format/lint, strict mypy over 177 source files and
  1,225 backend tests passed with 82% coverage.
- Public resume XeLaTeX build: one A4 page; no overfull/underfull box, undefined-reference,
  missing-character, encryption, JavaScript, clipping, or text-extraction failure observed.
- Local Codex MCP compatibility: the official SDK/STDIO contract suite passed 6 tests; Codex first
  completed a one-call `search_evidence` probe with one fixture result, then completed the bounded
  four-tool chain with one evidence result, one brand-context result, successful event retrieval and an
  accepted copy-validation result. The demo process tree was explicitly cleaned after the completed
  turn, and no demo process remained.

## Controlled-material aggregate check

- The local bounded parser inspected exactly two PDFs and one DOCX without retaining filenames, paths or
  source text in task artifacts.
- The 48-page PDF produced 43 page sections and 43 exact-slice child chunks without OCR.
- The initial offline check found only 17 usable text-layer page sections/chunks in the 50-page PDF and
  correctly requested the existing OCR path; that initial check itself made no provider call. The later
  explicitly authorized one-call OCR outcome is recorded separately below.
- The DOCX produced 14 sections, including all 9 interview Q&A parents, and 77 exact-slice child chunks.
- All 137 locally produced child chunks matched their canonical source offsets exactly.

## Authorized OCR-only aggregate gate — 2026-08-21

- Read-only preflight resolved exactly two controlled PDFs and exactly one sparse 50-page match. Its
  text layer still exposed 17 parents and requested OCR. Zhipu/`glm-ocr` and its credential were
  configured; the input fit the 100-page, 40 MiB request and 10 MiB response limits; timeout was 180
  seconds; competing OCR process count was zero.
- The normal transport configuration permits three attempts, but this isolated gate constructed the
  existing adapter with a one-attempt budget. Exact HTTP attempts: 1. Provider retries: 0.
- Provider status: success at the HTTP/model-envelope adapter boundary. Local validation status:
  failed closed with content-free code `brand_chunk_limit`; the v3 generic OCR parent produced more
  than the configured 600 parent-local child chunks.
- The protected OCR output existed only in a mode-0700 temporary workspace with a mode-0600 raw file.
  It was overwritten, fsynced, unlinked and the workspace removed. No filename, path, source/OCR text,
  API key, request payload, provider body, fingerprint or request ID was retained here.
- The local rejection occurred before the aggregate success record was assembled. Therefore exact
  returned-page coverage, section/chunk counts, slice invariants and deterministic replay are
  **not asserted** for this pre-fix OCR result. No retry or second request occurred within that gate;
  the separately authorized post-fix gate is recorded below.

## Post-gate local fix validation

- Synthetic OCR Markdown with 701 tiny blocks now stays below the existing 600 hard cap without
  truncation. Every non-whitespace source character is covered by exact, maximum-size-bounded,
  non-overlapping children; repeated chunking returns identical sections, keys, offsets and hashes.
- Two synthetic generic OCR parents with 620 blocks each remain independently bound; no child crosses
  a parent. A 1,000-character parent with a two-child budget still terminates with
  `brand_chunk_limit`, proving the hard cap was not raised or bypassed.
- Independent review added successful continuous-parent fallback, non-OCR/non-generic scope guards and
  the existing worker OCR-handoff regression for pathological Markdown. Focused brand/OCR/parser unit
  suite: 42 passed. Full Ruff format/lint: 306 files passed. Strict mypy: 170 source files passed. No
  provider/OCR call was made during implementation or independent review.
- The implementation passed independent review before the separately authorized post-fix call below.

## Authorized post-fix OCR aggregate gate — 2026-08-21

- Read-only preflight again resolved exactly one sparse 50-page input, confirmed Zhipu/`glm-ocr`, v3
  parser/chunker/input identities, the 100-page/600-child/900-character limits and zero competing OCR
  processes. The configured three-attempt transport was overridden to one attempt.
- Exact HTTP attempts: 1. Provider retries: 0. Provider/model status: success. Typed page coverage:
  50/50. The normalized OCR result contained 32,992 characters; provider usage was 151,689 prompt tokens
  and 52,515 completion tokens with 93,247 ms adapter latency.
- The fixed v3 path produced one `generic` parent and 38 children. Maximum observed child size was exactly
  900 characters; child count was within the unchanged 600 hard cap, so the prior
  `brand_chunk_limit` is resolved.
- Parent and child canonical slices were exact; every child remained inside its parent; deterministic
  replay from the same already-returned local OCR text matched exactly and made no provider request.
  Uncovered non-whitespace characters: 0. Uncovered separator-only characters: 74. Overlap characters:
  0. Content-type counts were 14 product, 10 external-claim, 9 safety, 1 visual and 4 other; claim scope
  was 27 external and 11 brand statements.
- Raw OCR existed only in the protected 0700 workspace/0600 file, then was overwritten, fsynced,
  unlinked and verified absent. No filename, path, source/OCR text, key, request/response body,
  fingerprint or provider request ID was retained. No DB, embedding, activation or downstream action
  occurred.

## Residual risks

- Text-layer PDF parsing is intentionally best effort: it preserves authoritative page boundaries but does
  not reconstruct coordinate-level visual layouts. The v3 generic OCR fallback now handles pathological
  small-block fragmentation and the real-result aggregate gate passed. The OCR representation preserves
  typed 50-page coverage but lacks reliable per-page offsets, so it intentionally remains one generic
  parent rather than fabricating page sections; Qwen3-VL is not required or integrated.
- Historical chunks intentionally have no fabricated parent metadata; their safe section fields remain
  null. Retrieval v2 preserves adjacent-ordinal behavior; retrieval v3 gives each historical row an
  independent null-safe parent key.
- New default version identities create new immutable derivations for later uploads; existing active
  versions are not automatically reprocessed or activated.
