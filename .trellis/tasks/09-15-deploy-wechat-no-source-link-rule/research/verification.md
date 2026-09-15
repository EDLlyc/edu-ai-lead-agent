# No-source-link implementation and release preparation verification

Recorded on 2026-09-15 Asia/Shanghai. This is pre-deployment evidence only. No
production mutation, provider call, model call, image upload, draft operation,
publication, database write, or object-storage write occurred in this phase.

## Product change

- Focused command:
  `conda run --name edu-ai pytest -q backend/tests/unit/test_official_account_source_presentation.py backend/tests/unit/test_official_account_xiaosai_final_cta.py backend/tests/unit/test_official_account_strict_prepared.py backend/tests/unit/test_wechat_official_account_draft.py backend/tests/unit/test_wechat_official_account_draft_worker.py`.
- Result: **124 passed**.
- Changed-file Ruff format: **7 files already formatted**.
- Changed-file Ruff lint: **passed**.
- Strict mypy over the five changed runtime modules: **passed**.
- The tests prove current V2 publisher-only output, explicit manifest null,
  caller-URL rejection before side effects, omitted HTTP source field, frozen V1
  reconstruction, and unchanged framing.

## Release tooling

- Reused the prior 2026-09-14 no-migration source-overlay operator structure.
- Adapted baseline: revision `d2e709c0b6a5e47d1b91d2ec623de734aa3c0eb2`,
  image manifest `sha256:baffc27e9dc4ccbd9fed5ab248e4e00784f80ecfb25f966fe8c63ee286601d8d`,
  schema `20260914_0047`, 12 application services and two dependencies.
- The operator permits only the exact sealed seven-row August preview cohort,
  requires the M/W/F edition table to be completely empty, validates exactly 14 history-owner rows
  including one ready `import-v1` barrier, freezes their canonical digest under
  the deployment lock, and rejects reserved/unknown owner state.
- A fresh production preflight exposed two formal Enterprise WeChat rows whose
  delivery window had not opened. The operator now permits zero through three
  such rows only when their complete safe control projection proves they are
  queued, `pending/pending`, attempt-zero with no attempt records, unleased,
  unstarted, error-free, formal, and strictly future/nonclaimable. It freezes the
  ordered canonical row digest and count at preflight, records only those safe
  values, and repeats the equality check at the pre-stop fence, post-quiescence
  fence, candidate readiness and receipt. All other active work must still equal
  exactly the seven sealed copy jobs.
- Quiescence requires at least ten minutes before the earliest allowed WeCom
  `not_before`; candidate readiness and receipt require at least five minutes.
  Running, partial, delivery-unknown, child-unknown, due, expired, malformed,
  changed, excessive or newly admitted rows fail closed. The operator never
  claims or mutates the allowed rows and exposes no job, recipient, package or
  content identity in logs or receipts.
- It requires the M/W/F minimum date `2026-09-16`, enabled single mode, disabled
  legacy weekly routes, and unchanged rendered Compose except for the immutable
  application image reference. It refuses activation on or after that date.
- It validates the OCI graph before `docker load`, loads before quiescence,
  recreates only the 12 application services with `--no-build --no-deps --pull
  never`, keeps dependencies unchanged, runs no migration, and restores the
  exact previous image and both revision markers after any post-quiescence
  failure.
- Its network-disabled smoke compares untouched application bytes, permanent
  banner bytes, legacy HTML and V1 HTML against the base image. The candidate
  additionally proves V2 contains publisher names but no URL/link/read-original
  affordance, binds a null URL, and sends a fake `draft/add` payload without the
  source field through `httpx.MockTransport`.
- Operator/validator/builder Ruff format and lint: **passed**.
- Strict mypy over the three release programs: **passed**.
- Fake operator/validator harness: **47 passed**. It covers strict manifest
  fields, exact release-env replacement, owner/barrier drift, the sealed queue,
  exactly zero editions, bounded future WeCom acceptance, zero-row compatibility,
  state/window/drift rejection, safe preflight/receipt evidence, pre-quiescence
  non-mutation, a complete post-quiescence fence, fail-closed rollback, exact
  service selection, preflight-only behavior, unsafe archive members, the exact
  five-file overlay layer, and the absence of publish/mass-send/upload/migration
  surfaces.
- Six-profile `docker compose config --quiet`: **passed**.
- Trellis task validation: **passed**, with only the known context-size warning
  for `quality-guidelines.md`.
- `git diff --check`: **passed**.

Current task-local tool hashes:

- builder: `8bbf23ba2fc1d8dcdb566063ea5bbcf571a39eb69e5423aa45d8c7ec265703d1`
- OCI validator: `8f6e169935f9970f0f31c8980783433017d6b836d75651cb61ce1e96225a5e93`
- deployment operator: `38452f764f143398358530791792fb523590e510070aecf0e7279260e34b2669`
- fake harness: `b272f340a314180540f4ba8193a2031e06ae8a4ceba5cec8a7764cc782af2272`

The independent Phase 2.2 review tightened four release gates without changing
product behavior: the OCI validator now parses the added layer and accepts only
the five reviewed app-owned files and exact base configuration; the edition gate
requires the table to be completely empty; activation rechecks protected files,
schema, candidate identity, Compose and queues after quiescence; and failed
rollback readiness stops writers again instead of leaving an unverified runtime.

## Full backend gate

The main session ran `make backend-check` once after the final product-code edit.
It stopped at `backend-format-check` on the known unrelated baseline only:

- `backend/app/domain/official_account_local.py:57`
- `backend/app/domain/topic_selection.py:323`
- `backend/tests/integration/test_title_relevance_ingestion.py:44`
- `backend/tests/integration/test_title_relevance_ingestion.py:277`

No task-owned file was named. Per task scope, those unrelated existing files were
not modified. The focused product and task-local release gates above are green.

## Commit-bound handoff

The deterministic builder intentionally requires a clean committed worktree and
an exact `HEAD` revision, so no candidate image was built from this uncommitted
implementation phase. After the main session commits and pushes the reviewed
change, run from that exact clean commit:

```text
python3 -B .trellis/tasks/09-15-deploy-wechat-no-source-link-rule/research/build-no-source-link-overlay.py \
  --revision <NEW_HEX40> \
  --base-archive /root/projects/edu-ai-lead-agent/output/mwf-single-release-d2e709c0b6a5/backend-image.oci.tar.gz \
  --output-dir /root/projects/edu-ai-lead-agent/output/no-source-links-<NEW_12>
```

The output is a mode-0700 directory containing the mode-0600 candidate OCI,
candidate manifest, validator, operator, and `artifacts.sha256`. Re-run the
task-local 47-test harness after any operator/builder edit. Transfer only those
five generated files, verify `sha256sum -c artifacts.sha256`, then invoke the
operator once without `--execute` and once with `--execute` using the exact
candidate-manifest SHA-256. The main session owns those commit, push, transfer,
activation, and final evidence steps.

The existing `01ff75e` OCI image and candidate manifest do not bind queue-policy
code and do not need rebuilding for this task-local operator adjustment. Before
the next production preflight, replace the staged operator with the reviewed hash
above and regenerate the operator line in `artifacts.sha256`; do not use the older
operator copy emitted by the initial builder run.
