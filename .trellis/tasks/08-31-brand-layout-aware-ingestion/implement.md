# Implementation Plan

1. [x] Freeze current v2/v3 parser, OCR handoff, DOCX Q&A, chunk-key/hash and retrieval behavior with focused
       regression tests before changing shared domain/adapter seams.
2. [x] Add provider-neutral brand OCR page/block DTOs and ephemeral parsed layout-block contracts with closed
       kinds, bounded text/bbox/page identities and exact-offset invariants.
3. [x] Extract/reuse the existing Zhipu raw layout envelope, page-dimension, index/label and bbox validation
       primitives; extend the brand document adapter to project bounded multi-page text/table/formula blocks
       while discarding image content and retaining frozen v3 Markdown compatibility.
4. [x] Add the deterministic PDF page-quality profile and v4 layout-routing pure function; cover slide-like
       sparse positives and ordinary/dense PDF negatives without using filenames or private metadata.
5. [x] Implement parser v4 OCR page assembly, page titles, canonical separators, exact page/block offsets,
       empty/image-only handling and strict failure when layout structure is unavailable.
6. [x] Implement chunker v4 layout-block boundaries and conservative aligned title/body card grouping;
       preserve parent-local splitting/overlap, 600 hard cap, generic fallback and exact deterministic IDs.
7. [x] Register only the complete v4 derivation bundle in domain/config/factories, update safe defaults and
       `.env.example`, and keep v2/v3 dispatch executable and mixed-bundle rejection intact.
8. [x] Add unit, provider-contract and application-service tests for multi-page layout, tables/formulas,
       bbox variants, typed failures/privacy, v3 compatibility, DOCX equivalence and no-provider local PDFs.
9. [x] Add real PostgreSQL/pgvector integration coverage for immutable v3/v4 coexistence, failed-job no-
       activation, ready activation/rollback and unchanged schema/migration head; do not create an Alembic
       revision or extend public HTTP/MCP projections.
10. [x] Keep the sanitized brand-text eval on the shared production RRF/selector and cover layout-sensitive
        behavior with typed parser/chunker fixtures rather than hand-authored retrieval ranks; retain all
        existing Recall@5, nDCG@5 and safety gates without fabricating a private-corpus metric.
11. [x] Run focused Ruff, strict mypy, unit/contract/integration tests and privacy scans; perform an independent
        Trellis check and fix confirmed findings before any real corpus/provider action.
12. [x] Run the development-only re-index plan, then rebuild exactly the two scoped PDF originals using
        repeated explicit `--document-id` UUID arguments and the configured Zhipu OCR/Alibaba embedding.
        The repository claim allowlist must cover fresh queued and stale-recovery paths; never select by
        private title/path. Retain aggregate-only 48/50 page/section/chunk/exact-slice evidence and activate
        only ready versions after layout-sensitive retrieval smoke passes.
13. [ ] Finalization is partially verified, but the full backend gate is not green: retained ready v3 versions
        preserve rollback; 227 task-focused tests, focused Ruff/strict mypy, the 36-case brand eval, Compose,
        one-head inspection, and global diff/privacy checks passed. Repository-wide format/lint and mypy remain
        blocked by unrelated dirty-worktree files; full pytest has 1,752 passes and 30 unrelated failures, with
        no brand/layout failure. The repository head is `0040`, while the local database remains at `0038`
        because unrelated migrations are not applied. See `result.md`; do not treat this as final acceptance.
14. [ ] Update `.trellis/spec/backend/brand-knowledge-rag.md`, task result/journal and any head/default contract
        touched by implementation; create one local path-scoped commit only if unrelated dirty changes can be
        excluded safely. Do not push, SSH, deploy, run business workflows or publish.

## Owned implementation surfaces

- Brand domain/ports/parser and Zhipu layout adapter shared primitives.
- Brand ingestion settings/factories/re-index wiring required by the v4 bundle.
- Focused brand/OCR/provider/eval/PostgreSQL tests and sanitized fixtures/reports.
- Brand backend spec and this task's Trellis artifacts.

Shared files such as `zhipu.py`, `config.py`, `Makefile`, specs and tests may already contain unrelated edits.
The implementer must inspect their live diff before editing and preserve all concurrent work.

## Deliberate non-edits

- No Alembic/model schema change.
- No retrieval SQL/RRF/API/MCP/copy-generation behavior change beyond consuming newly indexed chunks.
- No DOCX or digital-IP visual retrieval redesign.
- No deployment/release scripts or server configuration.

## Rollback

- Code/config rollback: restore the v3 default bundle; v4 rows remain immutable and readable.
- Data rollback: reactivate the retained prior ready version; never rewrite provider/model/version columns.
- Provider or local rebuild failure: leave current active version untouched and record only typed aggregate
  failure metadata.

## Controlled live-gate follow-up (2026-08-31)

- The first explicitly scoped v4 gate claimed exactly two PDF jobs. Both failed closed with the public
  `brand_ocr_invalid_output` code before embedding or persistence; neither version was activated and no vector
  artifact was created. This task record retains only those aggregate outcomes, not private identifiers,
  titles, paths, provider bodies, Markdown, layout elements, bbox values, or exception text.
- Before any further provider action, add one content-free diagnostic layer: an allowlisted internal reason on
  `BrandOcrInvalidOutputError`, exact stage mapping from existing shared issue codes, and safe attempt/log
  propagation. Bind persisted reasons to the generic `brand_ocr_invalid_output` code and cover the attempt-only
  metadata boundary against real PostgreSQL. Project classification outside raw JSON/Pydantic exception blocks
  so public errors retain no provider-input context/cause. The public code/message remain generic and unchanged.
- The diagnostic patch must not accept a new provider representation, retry/rebuild either document, inspect
  the private corpus, activate a version, call OCR/embedding, or alter the v4 fail-closed policy. A subsequent
  controlled gate requires a separate main-session decision after focused tests and independent review.

## Controlled compatibility follow-up (2026-08-31)

- A later explicitly scoped 48-page v4 run again failed before embedding or activation, now with the single
  allowlisted reason `brand_ocr_layout_element_extra`; the retained v3 version stayed active and no vector
  artifact was created. This note is aggregate-only and contains no document identity, title, path, body,
  Markdown, element content, bbox, or provider exception text.
- Public GLM-OCR formatter/SDK contracts show one bounded MaaS refinement field, `native_label`, while the
  canonical projection remains `index`/`label`/`content`/`bbox`. The compatibility patch therefore names and
  strictly validates only `native_label`; it does not enable generic ignored extras or broaden canonical
  labels, content, bbox, page dimensions, or source envelopes.
- The closed normalized role is retained only in memory so parser v4 can prefer explicit document/paragraph
  page/card titles without promoting figure captions, footnotes, seals, or formula numbers. Omitted metadata
  and generic `text` retain the bounded positional fallback. Canonical `label` continues to determine
  text/table/formula projection and image discard. Frozen v2/v3 OCR ignores Layout refinements. Invalid, unknown,
  over-limit, non-string, control-bearing, or canonical-conflicting native roles fail closed with the safe
  native-label reason. No provider retry/call, private-corpus inspection, rebuild, indexing, activation,
  deployment, commit, or publication is part of this patch.

## Second controlled diagnostic follow-up (2026-08-31)

- The subsequent explicitly scoped one-PDF retry failed closed before embedding with the aggregate-only
  diagnostic `brand_ocr_layout_native_label_invalid`. No provider value, document identity, payload,
  Markdown, layout content, bbox, exception text, or vector artifact is retained in this task record.
- Replace that coarse emitted reason with four closed content-free reasons: present null/empty/non-string
  type, overlength/control-character limit, unknown role, and canonical-label/role conflict. Field omission
  remains compatible, the role set and canonical projection remain frozen, and public job/version
  code/message remain `brand_ocr_invalid_output` / `brand OCR provider returned invalid output`.
- The worker and repository continue to propagate only enum-allowlisted reasons into attempt metadata and
  structured logs. They must never persist `native_label` itself. No further provider call, corpus read,
  retry, rebuild, indexing, activation, deployment, commit, push, or publication is authorized here.

## Third controlled compatibility follow-up (2026-08-31)

- The next explicitly scoped one-PDF Gate failed closed before embedding with the aggregate-only subreason
  `brand_ocr_layout_native_label_unknown`. The prior active version remained untouched; this task note retains
  no provider value, document identity, payload, Markdown, layout content, bbox, exception text, or vector.
- The official GLM-OCR PP-DocLayoutV3 configuration has 25 layout class identities. At the semantic refinement
  boundary, add only the six missing roles `aside_text`, `footer`, `footnote`, `header`, `number`, and
  `reference`. This intermediate assumption treated header/footer image identities as duplicate aliases; the
  later metadata-only probe and official PaddleOCR label list supersede that assumption.
- Each new role is compatible only with canonical `text` and is explicitly non-title/non-card. It cannot win
  positional page-title fallback, title/body pairing, persistence, or public projection. Values outside the
  complete set and canonical conflicts still fail closed. No provider call, corpus read, retry, rebuild,
  indexing, activation, deployment, commit, push, or publication is authorized by this patch.

## Metadata-only provider alias correction (2026-08-31)

- A bounded metadata-only probe observed exactly two additional enum names: `header_image` and
  `footer_image`. No provider content, document identity, payload, Markdown, bbox, exception text, or private
  corpus data was inspected or retained.
- The official PaddleOCR PP-DocLayoutV3 model label list is the compatibility oracle: it contains 25 unique
  labels and classifies header/footer images separately from textual `header`/`footer`. GLM-OCR's merge-mode
  comments that repeat header/footer are descriptive drift; its `id2label` entries and PaddleOCR documentation
  retain the distinct image labels.
- Add both roles only with canonical `image`. They are validated, classified as non-title/non-card, and
  discarded before brand text projection like chart/image. The role remains ephemeral and v4-only; public and
  persistence schemas are unchanged. Unknown values outside the official 25 and canonical conflicts still fail
  closed. No provider call, corpus read, rebuild, indexing, activation, commit, push, or deployment is
  authorized by this correction.

## Successful controlled v4 activation gate (2026-08-31)

- Exactly two scoped PDF originals completed under Zhipu `glm-ocr`, Alibaba
  `qwen3-vl-embedding`, parser/chunker/input versions v4/v4/v2. Their aggregate page counts were
  48/50, page-section counts 48/48, canonical character counts 9,708/20,924, and
  chunk-plus-embedding counts 359/359 and 468/468. Maximum chunk sizes were 465/269 characters.
- All 827 chunks were exact slices of their bound page sections. All 827 embeddings were present and
  exactly 2,048 dimensions. Both new versions reached ready and became active only after these checks.
- Rollback remained available: one old ready v3 version was retained for each document. Failed immutable
  diagnostic v4 versions were also retained, with aggregate counts 5/1; none was rewritten or activated.
- The bounded metadata-only compatibility probe observed only `header_image` and `footer_image`; no content,
  path, document identity, bbox, provider body, or exception text was retained.
- A real hybrid retrieval smoke succeeded after one transient query-embedding `ConnectError` and one bounded
  operator retry. All Top-5 hits were page-linked, both active v4 versions were represented, and the aggregate
  source pages were `[6, 7, 13, 43, 11]`. Neither query nor hit text is recorded here, and this smoke is not a
  production-quality or private-corpus accuracy claim.
- Final full backend/brand-eval gates, final owned-path privacy/diff review, and any path-scoped local commit
  remain pending under checklist items 13–14. No SSH, push, deployment, publication, or business run occurred.
