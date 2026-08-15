# 配图受控多样性 v2 — Result

## Outcome

The independent-news image path now supports a default-off, versioned controlled-diversity mode.
It preserves the approved Sai Xiansheng/Xiaosai polished 3D cartoon identity and blue-white-orange
brand language while deterministically varying scene, composition, camera, cast, slot tone,
subject, and approved action/style references.

The planner reserves a primary and alternate plan under a short PostgreSQL advisory lock using a
bounded seven-day history. Existing media, OCR, identity, and visual-quality gates run before a
deterministic perceptual similarity check. A near-duplicate first result activates the reserved
alternate exactly once. If the second safe result is still near-duplicate, one immutable image and
one independent material package succeed with the bounded code
`near_duplicate_after_retry`; existing automatic delivery remains eligible and no third diversity
generation occurs.

The approved visual-text standard is now part of the same versioned contract rather than a prompt
convention. Every controlled v2/v3 image requests exactly one three-level title card: the fixed
brand signature `赛先生科学`, one of six allowlisted category titles, and its matching short
subtitle. The card uses deep science blue, restrained orange, and subject-safe placement. The
main prompt, provider-rejection recovery, OCR allowlist, and audit metadata share this contract;
extra, missing, reordered, pseudo, raw-news, or model-authored text is not accepted. Historical v1
metadata and replay remain byte-shape compatible.
Enabling controlled diversity now also requires OCR at settings validation, so a deployment cannot
silently skip this gate.

## Delivered contracts

- Added the v2/v3 version bundle, ten scenes, eight compositions, five cameras, three casts, three
  slot tones, eight topic objects, staged relaxation, deterministic fingerprints, and calibrated
  Pillow dHash fixtures.
- Generic science coverage is intentionally neutral: robot, AI, astronomy, and competition
  objects require the matching governed category and cannot be invented for novelty.
- Added Alembic `20260815_0021`, matching ORM, exact composite lineage, attempt-aware references,
  plan reservations, similarity attempts, and legacy-compatible additive artifact fields.
- Added safe material API projection and a local-only accessible “配图变化方案” panel. Prompts,
  seeds, raw perceptual hashes, nearest object identity, private paths/keys, bytes, and provider
  bodies are not projected.
- Added default-off bounded settings, Compose/Doctor equality checks, production evidence counts,
  baseline/rollout/rollback documentation, and executable Trellis guidance.
- Historical v1 brief/selector/prompt/pipeline dispatch and old package/API replay remain intact.
- Added finite category subtitle mapping, exact three-line prompt/recovery clauses, OCR equality,
  and regressions for v1 metadata absence plus all six controlled categories.

## Independent check findings fixed

1. The generic science object pool originally allowed unsupported robot/AI/space/competition
   subjects. It was restricted to neutral science-book/model and experiment-apparatus objects,
   with regression coverage.
2. The production evidence query treated the string warning code as a Boolean. The query and
   runbook now match `near_duplicate_after_retry`; the SQL was executed successfully against the
   migrated local PostgreSQL schema and a release contract regression was added.
3. The v3 prompt crossed the 2,000-character bound when three long approved asset IDs were
   attached. Prompt assembly now keeps only ordered reference roles, never asset IDs or filenames;
   a three-reference maximum-length regression covers the production case.
4. Historical OCR validation correctly ignored block order, but the new card requires a visual
   hierarchy. Controlled v2/v3 requests now require exact signature/title/subtitle order and emit
   `misordered_visual_text`; v1 retains its historical order-insensitive semantics.
5. The diversity flag could previously start while OCR was disabled. Settings now fail closed
   unless exact OCR is enabled, and the PostgreSQL/fake-provider integration exercises that gate.

## Verification

- Focused diversity/material/API/delivery/migration matrix: 147 passed before final audit;
  affected regressions after the audit: 25 passed.
- Final backend gate: Ruff format/lint, strict mypy on 147 source files, 766 tests passed, 80%
  coverage.
- Final frontend/local inspection gate: OpenAPI/type drift, Prettier, ESLint, TypeScript, 39 tests,
  and Vite build passed. No frontend production artifact was deployed.
- Release tool tests: 50 passed. Python hash-lock drift: passed.
- Alembic has one head (`20260815_0021`); local upgrade and Doctor passed.
- Full governance/content/WeCom Compose render, API contract, all shell syntax, and
  `git diff --check` passed.
- After approving the three-level text standard, the independent focused brief/prompt/OCR/config/
  provider-recovery matrix passed 140 unit tests plus 1 PostgreSQL integration test; affected Ruff
  and strict mypy checks passed. Exhaustive prompt-bound evaluation covered 172,800 plans: main
  prompt maximum 1,908 characters and recovery maximum 1,272, both below the 2,000 limit.
- Real PostgreSQL concurrency/replay and fake repeating-image-provider tests prove two provider
  calls maximum for diversity, one MinIO success, `regenerate` then `accepted_with_warning`, and
  delivery eligibility.

## Safety and rollout state

- `IMAGE_DIVERSITY_ENABLED` remains false by default. Migration and code are ready, but no live
  image-provider smoke, Enterprise WeChat send, ACR operation, remote deployment, or production
  configuration change was performed.
- Existing unrelated dirty `.agents/skills/trellis-break-loop/SKILL.md` and `reports/**` were not
  modified or reverted.
- Production enablement and any bounded live acceptance require separate authorization and the
  documented backup/baseline/observation gates.
