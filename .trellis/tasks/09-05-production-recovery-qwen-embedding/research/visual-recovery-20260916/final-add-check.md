# Independent final generated-draft reconciliation check

## Scope and clearance

This supersedes the earlier update-only route only for the separately authorized
September 16 target whose original acknowledged media ID returned official error
40007 and was absent from the complete six-item inventory. The original ACK is
not erased or reinterpreted as a failed add. This is one separate reconciliation
operation, not a replay of the original write or a general retry feature.

Current frozen operator: `draft-generated-final-add.py` SHA256
`ba580ff87f6fab130a953b430f0dfe068ce01429741d2f0a2acdcb08c89a40ef`.
This supersedes initial hash `d444a3cf...` after the optional-field compatibility
review below; that initial version stopped during read-only inventory validation.
It seals update helper `e982e292...`, which seals generation helper `2fdfd035...`,
which seals original manual helper `301a9580...`.

Conditional clearance: run the read-only official-API plan first, then use exactly
its privacy-safe inventory fingerprint with `--apply`, same mounted account
journal and stopped affected consumer. The final completion claim additionally
requires the main operator's exact new-ID official readback/inventory check.
This script truthfully reports only add ACK and `readback_verified=false`; a
readback failure must never cause another add.

## Findings fixed

- New-prefix escape prevention: reject either intent or result from every old
  generated-update upload and update operation. Even an orphan result prevents
  treating that route as never started.
- Strict privacy projection: validate the exact closed absence-evidence fields,
  integer counts/error, booleans and 64-character fingerprint before persisting
  authorization or printing a resumed plan. Extra raw inventory metadata cannot
  be inserted into an apparently safe journal projection.
- A returned old media ID must be rejected before saving a successful new ACK,
  and remains rejected on ACK reuse. The retained new intent then stops any
  repeated add rather than converting the anomaly into success on the next run.
- Use composition for the sealed upload helper rather than an untyped dynamic
  subclass; type checking passes and this operator exposes no update method.

## Verified contracts

- Correct configured AppID, exact original source/add receipt and sealed generated
  artifacts remain required. Five generated bodies and all six passing audits
  are reconstructed with `NoModel` and false model-call permission.
- Inventory reconciliation requires exact old-ID error 40007 plus one bounded,
  complete six-item inventory with matching total/item count, unique media IDs,
  and all article subitems examined. Any old ID or same frozen title/author blocks
  creation. Only counts, match-zero/absence flags and a snapshot hash persist or
  reach stdout; no private inventory body/title/author list is retained.
- Plan is explicitly read-only network work, unlike the earlier local-only plans.
  Apply binds the supplied snapshot, source, article/generated-content identity
  and original receipt into a create-only same-day authorization of at most two
  hours. Repeated application cannot refresh it.
- Exact absence is rechecked before uploads and again immediately before add.
  Five audited body JPEGs plus the audited cover are uploaded byte-for-byte; the
  two existing banner ACK URLs are reused. Frozen title, author, digest, article
  words and no-source-links policy remain intact.
- The separate prefix owns six upload intents/results and one add intent/result.
  Each intent precedes its physical write; unknown results cannot be replayed.
  Successful ACK reuse performs no writes. Original journal/SQL history is not
  changed; no model, draft/update, deletion, publishing or mass-send is called.

## Verification

- `pytest -o addopts='' -q --no-cov --tb=short
  backend/tests/unit/test_draft_generated_final_add_operator.py`:
  **23 passed**, 1.52s. Includes complete-inventory/multi-article matching,
  old-target reappearance, unknown add, ACK reuse, forbidden old effect records,
  privacy projection tampering and anomalous old-ID ACK regressions.
- Combined generation/update/final-add focused suite: **59 passed**. Fake models
  and fake network only; not a claim of the full application suite.
- Ruff check/format on final-add operator/test: **pass**.
- `MYPYPATH=backend mypy --follow-imports=silent --check-untyped-defs` on
  final-add operator: **pass**, not full strict-type coverage.
- `git diff --check`: **pass**.
- Unchanged production image `febd216...`, `--network none --read-only`, read-only
  operator mount and Python `-B`: all helper seals/imports and actual old WeChat
  API client with MockTransport passed exact 40007, complete batchget and one
  single-article add with blank source URL. Output marker:
  `original_image_final_add_seals_and_absence_add_fake_contract_ok`.

The reviewer made no live provider/WeChat requests, production SQL writes, commits
or deployments. Live execution and final readback are the main operator's steps.

## Follow-up: actual inventory optional fields

The real read-only plan exposed an overly restrictive assumption: every unrelated
draft was required to contain string author and digest fields. Actual inventory
may omit those optional fields or return null/non-string JSON values. The absence
decision does not need their textual value when the title is clearly unrelated.

The implementer's compatibility fix passed independent inspection without further
code changes:

- Title remains a required string and every article subitem is still checked.
  Exact target title plus exact author is rejected regardless of digest.
- When title matches the target, absent/null/non-string/empty/whitespace author
  is ambiguous and **also rejected**, not silently converted to empty text.
- Unrelated-title optional fields are canonical-JSON hashed with explicit
  presence/type tags. Missing, null, empty string, false, numeric zero, list and
  object values stay distinct; dictionary key order is canonical. Raw values
  remain transient and never reach the evidence journal or stdout.
- Complete inventory, exact old-ID checks, immutable identity/hash chain,
  side-effect guards, two absence checks and unknown-write non-replay remain
  unchanged. A new read-only plan produces the fingerprint for this revision.

Verification on the new hash:

- Final-add focused suite: **48 passed**, 1.25s (original 23 plus 25 field/schema
  cases). Ruff check/format, check-untyped-defs mypy and diff-check all pass.
- Combined generation/update/final-add suite on this revision: **84 passed**,
  13.17s. No models or live network are involved.
- Actual old production image under the same network-disabled/read-only flags:
  real API client plus MockTransport accepts six unrelated mixed optional-field
  records, rejects a matching-title/unknown-author record, and verifies distinct
  typed fingerprints and canonical object order. Output marker:
  `original_image_optional_fields_and_ambiguous_target_fake_contract_ok`.

This remains conditional execution clearance, not a claim that a new draft was
created or officially read back. Those production actions belong to the main run.
