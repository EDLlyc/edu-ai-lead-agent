# Implementation plan: tiered science and technology news priority

## Preconditions

- Do not implement until the user explicitly approves this PRD/design/plan and the task is started.
- At implementation start, load `trellis-before-dev` for the affected backend layers and preserve
  every unrelated dirty-worktree file.
- Treat `science-ai-education-v1`, `product-matrix-fit-v1`, acquisition v4, topic `.4`/`.5`,
  veto v1/v2, and `science-policy-priority-v2` as immutable historical contracts.
- Do not modify or regenerate any file under `reports/`; do not change active/pending source
  membership.

## Ordered implementation checklist

1. [x] Capture focused baseline behavior for editorial relevance, acquisition, source-version
   replay, Ministry priority, topic selection, persistence, and API explanation; record current
   migration head and active/pending source counts.
2. [x] Add the pure bilingual `science-tech-editorial-v2` policy with typed cohorts, bounded scores,
   stable reason codes, science-talent pathway signals, topic-plus-progress frontier qualification,
   exclusions, title/body match separation, and 6,000-character handling. Keep v1 code and tests
   unchanged.
3. [x] Add immutable `product-matrix-fit-v2-science-pathways`, retaining v1 directions/caps while
   recognizing white-list competitions, technology-specialty students, Strong Foundation Plan,
   and comprehensive-evaluation pathways with stable reasons and non-inflating contributions.
4. [x] Add exhaustive domain fixtures/tests for education priority, pathway keyword positives,
   admissions/training/guarantee/score-line negatives, ambiguous `综评`, qualified robotics/AI/
   scientific advances, overlap precedence, financing/marketing/ordinary-release negatives,
   deterministic replay, product caps, and boundary truncation.
5. [x] Add v2 acquisition dispatch and deterministic list ordering: education titles, frontier
   titles, then bounded neutral probes; use product fit only inside a cohort and preserve the stable
   fallback keys.
6. [x] Re-evaluate title plus bounded detail body, persist only v2 candidates, and add cohort/scores/
   reasons/product/bound/counter metadata to candidates and observations. Preserve freshness,
   zero-match, no-quota-fill, safe-fetch, lease, retry, snapshot, and idempotency behavior.
7. [x] Publish `acquisition-v5-tiered-science-tech` and immutable v2 source versions for the ten
   active seeds. Verify seed reconciliation leaves Xinhua active and CAST/EdSurge pending and keeps
   every historical source version executable.
8. [x] Extend event projection and internal topic candidate/score structures with v2 cohort,
   editorial-priority score, frontier/education scores, reasons, and rule version while retaining
   v1 fields for `.5` replay.
9. [x] Add `.6` config serialization/deserialization with the approved
   30/25/15/10/10/10 `editorial_priority` feature map and `topic-veto-v3-governed-content`.
   Ensure `.4`, `.5`, and `.6` branch only on immutable stored metadata.
10. [x] Implement `ministry-education-priority-v3`: authenticate controlled Ministry occurrence
    metadata, require the v2 education cohort, cover white-list competition and science-talent
    pathway news, remove the old action-word requirement, and permit threshold bypass only when
    there is no hard veto.
11. [x] Update ranking eligibility and explanations so Ministry bypass cases persist
    `passes_threshold=false`, `eligible=true`, `priority_applied=true`, and
    `threshold_bypass_applied=true`; ordinary below-threshold and every hard-veto case remain
    ineligible.
12. [x] Add topic unit regressions for all Ministry included themes/pathways, title-only spoofing, each hard
    veto, ordinary threshold behavior, education-over-frontier ranking, deterministic tie-break,
    no-topic outcomes, and exact historical `.4`/`.5` semantics.
13. [x] Add real-PostgreSQL and API regressions for source-policy propagation, config fingerprints,
    immutable conflict detection, cutoff/replay, score/explanation round trips, ranks, and public
    response-shape stability.
14. [x] Update README/operator text and executable backend specs to describe v2 acquisition, `.6`
    scoring, Ministry threshold bypass, the retained genuine vetoes, and historical compatibility.
15. [x] Run focused tests, backend full gates, frontend/API/Compose/doctor gates, migration and
    sensitive-data audits, and `git diff --check`; run `trellis-check` and reconcile any spec drift.

## Focused validation commands

Start with the existing modules and extend filenames only where a dedicated v2 suite is clearer:

```bash
conda run --name edu-ai pytest -q \
  backend/tests/unit/test_editorial_relevance.py \
  backend/tests/unit/test_topic_selection.py

conda run --name edu-ai pytest -q \
  backend/tests/integration/test_title_relevance_ingestion.py \
  backend/tests/integration/test_acquisition_repositories.py \
  backend/tests/integration/test_topic_selection_repositories.py \
  backend/tests/integration/test_topic_selection_api.py
```

Required focused assertions include:

- education-title > frontier-title > neutral-probe, with stable repeated output;
- white-list competition, technology-specialty student, Strong Foundation Plan, and
  comprehensive-evaluation pathway positives are recognized, while training/admissions marketing
  and guaranteed-outcome negatives are not rescued by the terms;
- product fit cannot create a v2 candidate or override a hard veto;
- controlled Ministry education content below `0.62` is selected unless a genuine veto applies;
- text saying “教育部” without controlled source metadata receives no Ministry priority;
- ordinary frontier content below threshold remains unselected;
- `.5` still emits `outside_science_ai_education_scope`, while `.6` does not;
- `.4` still requires its original policy action/threshold semantics;
- ten active/two pending sources and the roadmap PDF are unchanged.

## Final validation commands

```bash
make backend-check
make frontend-check
make api-contract-check
docker compose config --quiet
make doctor
git diff --check
```

Also verify the unique Alembic head is unchanged, no generated API artifact drifts, and no response
body, secret, credential, or private object location enters task artifacts or logs.

## Risk and rollback checkpoints

- Highest risk is version dispatch in acquisition and topic config deserialization. Land pure policy
  tests first, then acquisition, then scoring, keeping historical focused tests green at every step.
- Ministry threshold bypass is intentionally narrow. Centralize the `no veto AND (threshold OR new
  priority)` calculation; do not add scattered source-name conditions.
- Keep source authentication in persisted policy metadata. Never infer official identity from
  title, summary, URL display text, or a reposted attribution.
- No migration is planned. If typed storage or a public API field becomes necessary, stop and return
  to design review before adding it.
- Roll back future acquisition with the prior source versions and future ranking with `.5`; never
  delete or rewrite v2 candidates, `.6` scores, config snapshots, or daily decisions.

## Final review checklist before task start

- [x] Product scope is converged: AI education is priority, qualified frontier technology is
  allowed, and Ministry education content is highest priority without the ordinary threshold.
- [x] White-list competitions, technology-specialty students, Strong Foundation Plan, and
  comprehensive evaluation are explicit science-talent pathway signals with marketing and
  keyword-only false-positive boundaries.
- [x] Ministry priority remains subordinate to every genuine hard veto.
- [x] The PDF and source activation registry are explicitly out of scope.
- [x] Design defines immutable acquisition, content, veto, priority, and scoring versions with
  historical replay.
- [x] Implementation/check contexts contain only relevant spec and research files.
- [x] User reviewed the final plan and explicitly approved implementation.

## Implementation outcome

- Implemented and independently reviewed on 2026-08-13 without migration or public API drift.
- Review fixes made product fit incapable of creating qualification, bound pathway substance to the
  same text neighborhood, excluded generic product/financing/compute/forum false positives, and
  restricted Ministry threshold bypass to the exact `.6`/editorial-v2/priority-v3 configuration.
- Verification: 680 backend tests, 147 affected tests, 26 connector contract tests, strict mypy
  over 136 modules, Ruff, frontend lint/type/build, 27 frontend tests with one worker, API contract,
  Compose, doctor, and diff checks passed. Default parallel Vitest startup was unavailable because
  the shared host had approximately 72 MiB free; no frontend assertion failed.
- Registry remains exactly 10 active and 2 pending; Alembic head remains `20260807_0019`.
- `reports/`, PDFs, and the pre-existing `.agents/skills/trellis-break-loop/SKILL.md` diff were not
  modified by this task.
