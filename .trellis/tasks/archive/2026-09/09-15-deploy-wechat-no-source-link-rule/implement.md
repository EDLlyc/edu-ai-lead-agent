# Implementation and deployment plan

## 1. Freeze and verify the change

- [ ] Confirm the worktree contains only the five runtime files, two test files,
  three specification files, and this task's artifacts.
- [ ] Run focused source-presentation, final-CTA/framing, strict-prepared,
  draft-worker, HTTP client, and historical compatibility tests.
- [ ] Run changed-file Ruff format/lint and strict mypy.
- [ ] Run the backend gate once and record only unrelated pre-existing failures if
  the known baseline remains; run `git diff --check` and Compose validation.
- [ ] Update the readable-source specification so deployment status and evidence
  refer to the new release rather than implying V2 was in revision `4782064`.

## 2. Commit and prepare immutable artifacts

- [ ] Review the complete staged diff and commit the reviewed code/tests/spec/task
  artifacts on `release/wechat-two-banner-framing-20260914`.
- [ ] Push that exact commit to the existing Codeup `origin` branch; do not push to
  the disabled GitHub backup.
- [ ] Verify the retained `d2e709c` OCI archive and load the exact production base
  locally without contacting a registry.
- [ ] Build a one-layer candidate containing only the five committed runtime files
  and the new revision label. Preserve base configuration and untouched bytes.
- [ ] Canonicalize/export/reload the candidate, validate the OCI graph and
  network-disabled compatibility smoke, and create a checksum-bound manifest.

## 3. Review the deployment operator

- [ ] Adapt the previous source-overlay operator to the exact current marker,
  image, schema `20260914_0047`, service topology, M/W/F ownership/queue state,
  and five-file smoke.
- [ ] Preserve create-only protected backups, exact baseline fencing, load-before-
  stop, no-dependency recreation, atomic marker updates, readiness waiting, and
  automatic exact-image rollback.
- [ ] Add fake-command tests for manifest tampering, pre-stop failures, partial
  stop/activation/start/readiness failures, rollback, service selection, marker
  preservation, zero model/social routes, and safe receipt contents.
- [ ] Run independent check after the candidate and operator are frozen. Any
  product/operator edit invalidates the affected gate and requires rerun.

## 4. Deploy

- [ ] Capture a fresh read-only production baseline: commit/image/schema, 12+2
  health, restart counts, disk, backup timer, protected config hashes, M/W/F mode,
  ownership rows, private journal seal, and queue state.
- [ ] Transfer only the checksum-bound OCI archive, manifest, and reviewed operator
  bundle into a fresh exact production staging directory.
- [ ] Run manifest validation without `--execute`; confirm zero production changes.
- [ ] Execute once under the deployment lock. Do not rerun an ambiguous activation;
  inspect the protected receipt and live state first.

## 5. Verify and close

- [ ] Run the production health checker and an independent network-disabled
  in-container V2/V1/source-field smoke.
- [ ] Verify new revision/image on all 12 application services, two unchanged
  healthy dependencies, zero restarts, unchanged schema/config/data seals, idle
  queues, no unexpected edition admission, and zero model/social calls.
- [ ] Record safe deployment evidence in task research and correct the production
  status in the relevant backend specification.
- [ ] Run the Trellis check gate, commit evidence/spec-only follow-up if needed,
  archive the task, and record the developer journal entry.

## Rollback point

The exact prior state is revision
`d2e709c0b6a5e47d1b91d2ec623de734aa3c0eb2` and immutable image digest
`sha256:baffc27e9dc4ccbd9fed5ab248e4e00784f80ecfb25f966fe8c63ee286601d8d`.
The deployment operator must not proceed past quiescence unless it can atomically
restore both markers and `.release.env` and recreate all 12 services from that
exact digest.
