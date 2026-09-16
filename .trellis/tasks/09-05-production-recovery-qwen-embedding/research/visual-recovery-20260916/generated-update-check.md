# Independent generated replacement review — September 16

Scope: the explicitly authorized generation and replacement of the **same already
acknowledged** September16 draft. Original SQL unknown rows stay unchanged. This
review does not authorize another draft/add, publishing or a general deployment.
Reviewer performed no model/WeChat request and no production write.

## Historical initial generation-only clearance

`generated-draft-update.py` SHA256:
`98b643344235742f05361e1fdf6659d1d26f4ebe20ea77ecd440976ca2ae3c64`.

Conditional clearance: production default plan must pass against the real account,
source and mounted journal before `--generate-only`. This version explicitly
rejects `--update`; update is a separately reviewed operator. A subsequent code or
scope change invalidates this exact-hash clearance.

Fixed during independent review:

- Separate worker capabilities: generation runs in the local image worker, whose
  WeChat credentials are intentionally absent. Its account is bound by the exact
  SQL target and original account journal/claim/add ACK. The update worker must
  independently validate its configured AppID against that original account;
  generation must not require WeChat credentials or relax its model policy.
- Recompute the original single-write binding from exact edition/article/content/
  account/max-attempts; reject conflicting original add ACK/not-applied records.
- Enforce exactly five generation inputs and the existing strict native image
  bound (12MiB), rather than the initial ad-hoc 20MiB bound.
- Replace opaque plan failures with closed, safe stage codes. No raw provider
  response, URL/token, article body or secret appears in diagnostics.
- Fix import-loader narrowing, tuple/list type flow and Ruff findings.

Verified behavior: five distinct physical generation keys are different from the
original logical request keys. Each paid intent is journaled before dispatch;
an intent lacking a result cannot be replayed. Final bounded JPEG bytes and
checksums are stored per image before result acknowledgement. There are five body
audits and one actual cropped 1175×500 cover audit, all requiring exact identity,
accepted=true and no issues. Resuming accepted artifacts makes no model calls.
Default plan does not instantiate generation/audit clients or write authorization.

## Generation verification

- Actual immutable base image
  `offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:febd216660c4fdf3919a8cd2c7da8c233d69d1e53503ff50b27df00c2aa58655`:
  imported the operator and verified `load_manual()` under `docker run --network
  none --read-only --cap-drop ALL --security-opt no-new-privileges --pull never`,
  with the operator directory mounted read-only and Python `-B`. Result:
  `original_image_import_and_manual_seal_ok`. No app-code overlay was mounted.
- `PYTHONPATH=backend pytest -o addopts='' -q --no-cov --tb=short
  backend/tests/unit/test_generated_draft_update_operator.py`: **7 passed**,
  10.10s. Fake generation and review only.
- Ruff check and format check on operator/test: **pass**, two files.
- `MYPYPATH=backend mypy --follow-imports=silent --check-untyped-defs
  .trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-recovery-20260916/generated-draft-update.py`:
  **pass**, one script. This is check-untyped-defs, not a claim of full strict
  typed coverage for the one-off script.

## Terminal-invalid recovery clearance (supersedes initial generation hash)

`generated-draft-update.py` SHA256:
`2fdfd035b82ba7c431dcbcb0aefecb09e594717366e6182f950ab968bc21b83d`.

The initial production call returned the generic `image_output_invalid` exit.
Its precise raster failure cause was not recorded and is **not proven to be
geometry**. This revision permits only the observed image-zero operation with
original intent fingerprint
`fc6a1e15fec14f375e99056f22320e4abcbc2b0e5c5a8f3cf186060c7c8ef57f`
and original operator hash `98b643...` to receive one explicitly authorized paid
replacement. It does not infer a safe retry merely from intent-without-result.

Fixed during recovery review:

- Restricted both CLI and internal recovery binding to exact ordinal zero and
  that fixed original intent. New invalid outcomes on images 1–4 may be recorded
  but cannot authorize a replacement in this version.
- The separate attempt-two authorization is create-only and persists before its
  POST; it inherits the original deadline without extending it. The original
  intent remains unchanged, while the replacement has a distinct physical key.
  Unknown or invalid attempt two cannot create a third attempt.
- Bound the new raster normalization version into subsequent, not-yet-started
  images 1–4 and their physical keys; image-zero's original intent remains
  byte-equivalent for the historical binding. Attempt two also binds that policy.
- Confirmed only output raster normalization is overridden. Existing URL/DNS,
  redirect, bounded transport and one-POST controls are inherited unchanged.
  Valid single-frame PNG/JPEG/WEBP is limited to 12MiB, 16MP and bounded edges,
  EXIF-oriented, flattened on white, fitted to 1536×1024 and deterministically
  encoded as JPEG. Invalid/oversized/animated/non-image payloads remain rejected.
  Original source dimensions, media type and checksum are separately recorded;
  normalized output is not represented as native provider geometry.
- Existing strict final-image preparation, five final-byte body audits and the
  actual cropped-cover audit remain required. No original SQL records change.

Production must first run the recovery default plan, then the explicit generation
operation in the image-capable local worker, using the shared original journal.
This permits one replacement of the already observed failed operation plus the
four not-yet-generated body images, not unbounded retries.

## Update-only clearance

`draft-generated-update-only.py` SHA256:
`e982e292f49c405b13b29581ff7f1a8f0c64cfddad9f2210f335b9f68d8f044e`.
It is cleared only with that frozen hash and its embedded generation seal
`2fdfd035...`.
Default plan reconstructs only already accepted generation/audit receipts; its
`NoModel` capability and false call permission prevent any model operation.

Fixed and verified during update review:

- Added an explicit endpoint/query allowlist rejecting draft/add, publish and
  mass-send endpoints before transport. Cover upload keeps `type=thumb` in the
  query parameters together with the token.
- Preserved exact final audited image bytes without re-encoding, original article
  title/author/digest/body words, fixed header/footer and their original upload
  ACKs. Source links remain absent.
- Verified the configured account and original acknowledged draft identity;
  exact draft/get comparisons happen before uploads and again before the one
  draft/update. WeChat's data-src form is accepted, while conflicting image
  attributes and duplicate HTML attributes are rejected.
- Rejected duplicate JSON keys, non-finite values and ambiguous/non-integer-zero
  update acknowledgements. Each upload/update persists intent before dispatch;
  an unknown outcome stops resume instead of being resent. A successful update
  receipt is reused without any repeated writes.
- Original draft/add receipt, generation receipts and SQL unknown records remain
  untouched. Final status reports update ACK rather than claiming post-update
  readback or publication.

Clearance remains conditional on a successful real default plan, unchanged source
and journal, the original authorization deadline and the affected draft consumer
being stopped as required by the operator usage. No ordinary schedules change.

## Combined final verification

- `pytest -o addopts='' -q --no-cov --tb=short
  backend/tests/unit/test_generated_draft_update_operator.py
  backend/tests/unit/test_draft_generated_update_only_operator.py`: 36 focused
  cases passed (20 generation and 16 update), using fake model/network calls.
  Includes exact image-zero replacement followed by images 1–4, six final-byte
  audits, and no-model resume; independent unknown-upload and unknown-update
  non-replay regressions.
- Ruff check and format check: four operator/test files pass.
- `MYPYPATH=backend mypy --follow-imports=silent --check-untyped-defs` on both
  one-off operators: pass. Not a full strict-typing or full-suite claim.
- `git diff --check`: pass.
- Actual unchanged production base image (`febd216...`) under `--network none`,
  read-only filesystem, read-only operator mount and Python `-B`: both sealed
  imports pass. Its real generation adapter plus MockTransport successfully
  normalizes a 768×1024 PNG with exactly one keyed POST; its real WeChat client
  plus MockTransport correctly sends cover type and same-ID draft/update with
  blank source URL. Markers: `original_image_normalized_single_post_fake_contract_ok`
  and `original_image_seals_and_update_cover_fake_contract_ok`.

No reviewer invocation used a paid provider, live WeChat transport, production
database write, deployment, commit or publication.
