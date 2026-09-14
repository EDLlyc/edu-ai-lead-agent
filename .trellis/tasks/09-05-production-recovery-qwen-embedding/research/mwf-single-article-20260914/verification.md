# Verification ledger: M/W/F single drafts

All local backend commands run from the release-hardening worktree with
`PYTHONPATH=backend` and the existing `edu-ai` Conda environment. New PostgreSQL
tests use isolated `edu_ai_test_*` databases through the integration fixture;
neither developer nor production schemas are test targets. Fake clients only:
no model generation, manual draft upload or subscriber publication in validation.

## Main-agent legacy regression

Selected 219 tests across the existing weekly planner/DAG/edition, strict prepared,
source presentation, draft service/settings/artifacts/worker and inbox contracts.
The first run found missing ignored private fixture PNGs in the clean worktree and
two genuine legacy log-field regressions. Copied only the three existing fixture
PNG bytes from the main workspace into the ignored worktree asset directory.
No image generation, asset edit or new tracked binary was involved.

The second run passed 217/219; both remaining failures asserted the lost legacy
`week_start` log field. Implementation restored it without changing old assertions.
Re-ran the entire `test_official_account_weekly_material_preflight.py` file after
the fix: **35 passed**. Thus the two observed failures are covered by a passing
targeted rerun; do not represent the earlier 219-test invocation as wholly green.

Additional existing worker, strict-visual worker, local CLI and local API regression
after the frozen generation retry-policy addition: **54 passed** (`--no-cov`).

`docker compose --env-file .env.example` with weekly/local/draft profiles and
`config --quiet` passed. `bash -n` for doctor/production-check and `git diff --check`
passed. Task context validation passed (12 entries); the existing large quality
guide emits its known injection-size warning, so required sections were read
explicitly rather than assuming full automatic injection.

## Implementer and independent review

Independent final product review: **41 new unit cases**, **8 isolated PostgreSQL
cases**, and strict mypy across **17 product files** passed. This includes the
reviewer's 11 runtime/failure cases and a real Alembic downgrade attempt refused
when only the new history-owner table is populated (head and owner retained).
Frozen model attempt/expiry policy is enforced on enqueue, failure, claim and
manual retry without changing legacy request fingerprints or legacy bundles.
No remaining product blocker was reported. Product code is frozen: Ruff check on
23 owned Python files passed, 20 formatted files were unchanged, and diff checks
passed. Full-backend mypy (274 files) retains only two pre-existing Literal errors
in unchanged `local_exact_target_selection.py:158-159`; changed-product strict
mypy passed as above. Do not call the full-backend baseline wholly green.
Earlier additional weekly/source/framing cases
84 passed; release/runtime compatibility tests 48 passed. The one-shot operator's first
32 fake-command cases passed, followed by independent requests for stronger
pre-stop, quiescence, service-flag and forward-recovery verification.
Final independent operator review: **42 tests**, Ruff lint and format all passed;
all four requested guards are covered. Frozen operator SHA-256
`b4199a4fc266f1795dc42c9e96bf781f216a444d9a068643c991b3ceeae08c30`;
test SHA-256 `bf5729306b7e565da2b1c1fb329f10d6ef3331edcf8e49c33cf4aec128e30104`.
Its same-directory prior-helper dependency is independently pinned to
`2956e2f4869265cad874771e2210659369087c12d60835cb0b89998c64d79c8b`.
These checked artifacts are eligible for the main operator's separate under-lock
production preflight, not evidence that activation has already occurred.

## Activation evidence

Completed: commit `d2e709c`, immutable image/archive and exact-base source proof,
reviewed under-lock full backup/migration/activation, and fresh runtime verification.
See `activation.md` for pinned hashes and evidence: 12 services plus two dependencies
healthy, schema 0047, zero new editions, 14 history-owner rows with one ready barrier,
old route disabled. Future draft acknowledgement is not yet observed or claimed.
