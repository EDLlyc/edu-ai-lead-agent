# Implementation plan: Evaluation next-stage P0

## Phase 0 — preserve current baseline

- [x] Confirmed the separate P0 reliability-gate task is still uncommitted/unarchived; kept its
      dirty Make/CI/topic fixture changes isolated. Seed V2 unified-gate wiring remains owned by
      that task, while this task uses the explicit provider-free V2 checks below.
- [x] Freeze existing 100-query/4,100-grade Seed hashes and the reviewed V2/V3 live evidence.
- [x] Load current backend/IP-asset specs and record overlapping dirty files before edits.

## Phase 1 — Codex Seed V2 authoring contract

- [x] Preserve Seed V1 byte/hash identity and introduce additive `codex_seed_v2` query/grade/review
      identities with complete-matrix validation.
- [x] Re-view all 41 approved images before labeling; do not open live rank or score observations
      during authoring.
- [x] Add exactly 24 no-answer/near-miss queries and complete all 984 new grades, producing exactly
      124 queries and 5,084 judgments in V2.
- [x] Blind-review risky V1 slices and emit a bounded old/new grade change ledger; keep maturity Seed
      and reject human Gold/agreement wording.

## Phase 2 — no-answer and robustness expansion

- [x] Assign 18 new queries to dev and 6 to holdout, producing exactly 30 no-answer queries overall.
- [x] Add paired paraphrase/noise consistency and filter-monotonicity metadata without making them
      ranking inputs.
- [x] Regenerate only intentional query/seed authoring artifacts and review distribution/hash diffs.

## Phase 3 — selective-retrieval evaluation

- [x] Extend safe live observations with bounded decision evidence; keep labels isolated and business
      telemetry disabled.
- [x] Implement deterministic threshold/policy sweep on dev and one-shot holdout reporting.
- [x] Report no-answer false-positive, answerable false-abstention, coverage/risk, ranking metrics,
      slices, bad cases and paired bootstrap intervals.
- [x] Do not activate any production threshold or new search version in this task.

## Phase 4 — evidence retention and validity

- [x] Add a minimal versioned safe run manifest and explicit artifact-hash validation; do not create
      a general platform or database migration.
- [x] Add validity notes for harness identity, contamination, ambiguous/broken cases, judge/label
      provenance and corpus drift.
- [x] Update the IP asset evaluation spec with only implemented contracts and truthful maturity.

## Validation

```bash
make ip-asset-grounded-eval-check
make eval-check
conda run --name edu-ai pytest \
  backend/tests/unit/test_ip_asset_retrieval_grounded_eval.py \
  backend/tests/unit/test_ip_assets.py -q --no-cov
conda run --name edu-ai ruff format --check <task-python-paths>
conda run --name edu-ai ruff check <task-python-paths>
conda run --name edu-ai mypy <task-python-paths>
git diff --check
```

Live/provider runs remain explicit and require separate authorization for provider cost. Codex
review may improve consistency and coverage but must not manufacture human evidence.

## Risky files and rollback points

- `backend/evals/ip_asset_retrieval_grounded/`: dataset/query/label/run/report hashes must be reviewed
  as coherent groups.
- `backend/app/application/services/ip_assets.py`: evaluation-only boundary must not change ordinary
  search telemetry or production behavior.
- `Makefile` and quality specs currently overlap the separate uncommitted P0 reliability task; read
  the latest diff and stage by path/hunk only.
- Any proposed production `v4` selector is explicitly out of this task and must be independently
  approved after this Seed report is reviewed; human calibration remains deferred.
