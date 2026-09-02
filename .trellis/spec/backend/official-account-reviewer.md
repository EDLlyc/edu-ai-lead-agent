# Official-Account Governed Reviewer

## Scenario: Observe or enforce an independently governed editorial review

### 1. Scope / Trigger

This contract applies when the local official-account worker generates a final article and
`OFFICIAL_ACCOUNT_REVIEWER_MODE` is `observe` or `enforce`. The common prefix is fixed:

1. deterministic article validation;
2. the existing legacy factual/privacy/safety auditor hard gate;
3. one independently governed editorial Reviewer call.

Observe then preserves rendering, handoff, and ready-state behavior. Calibrated live enforce may
accept revision 1 or execute exactly one code-directed Writer repair, deterministic/legacy recheck,
and terminal revision-2 Reviewer call before downstream rendering.

`off` is the default and must preserve the pre-Reviewer execution exactly: no Reviewer provider
call, intent, record, allocation, artifact, event, budget reservation, status change, output-byte
change, or Reviewer field in the run fingerprint/version bundle. Enforce remains default-off and
requires the literal acknowledgement plus a lowercase SHA-256 of a manually approved calibration
report; fixture runs and migration defaults cannot activate it.

### 2. Signatures

The public application contracts are `OfficialAccountReviewer`,
`OfficialAccountReviewRepository`, and `OfficialAccountReviewGovernance` in
`app.application.ports.official_account_reviewer`. A review request binds the frozen
`ReviewRequest`, exact source snapshot, exact `ArticlePackage`, and an output-token ceiling. A
result contains only the closed `ReviewVerdict`, safe provider/model/request identifiers, token
usage, latency, and deterministic validation-correction count.

Governed identities are fixed and separate:

- root: `official.review.orchestrator`;
- Writer: `official.writer.initial`, role `WORKER`, capability `official.article.generate`;
- Reviewer: `official.reviewer.r1`, role `REVIEWER`, capability `official.article.review`.
- repair Writer: `official.writer.repair`, role `WORKER`, capability `official.article.repair`;
- terminal Reviewer: `official.reviewer.r2`, role `REVIEWER`, capability
  `official.article.review`.

Durable state is additive in Alembic revision `20260902_0043`:

- `official_account_review_requests` stores `pending | calling | completed | result_unknown`, the
  real attempt number, request fingerprint, immutable input hashes, contract/model versions,
  three artifact references, and real execution allocation/reservation/event references;
- `official_account_review_records` stores `accepted | manual_review | rejected | unavailable`, a
  closed issue snapshot, usage, result artifact, producer event, and record fingerprint.

Revision `20260902_0044` adds independent `revision_no` (`1 | 2`) identity,
`repair_of_article_version_id`, one durable repair intent per run, exact review-record run/article
lineage, the active accepted review pointer, and render-to-review lineage. `version` remains the
article schema family and must never be reused as a repair counter.

The frozen configuration bundle consists of Reviewer mode/version, prompt/request/verdict/rubric/
review/repair/budget policy versions, Writer and Reviewer timeouts, Reviewer output-token ceiling,
and provider/model identity. Environment keys use the `OFFICIAL_ACCOUNT_REVIEWER_*` prefix.
Timeouts are independently bounded to 1,000--420,000 ms; provider-backed observe/enforce requires
each active gateway timeout to cover the provider total-timeout contract.
Enforce additionally freezes repair timeout/output budget, enforce policy, acknowledgement, and
calibration-report SHA. Observe fingerprints and version bundles exclude all enforce-only fields.

The activation contract is concrete:

| Key | Observe | Enforce |
|---|---|---|
| `OFFICIAL_ACCOUNT_REVIEWER_MODE` | `observe` | `enforce` |
| `AI_PROVIDER_MODE` | fixture or `zhipu` according to the run | must be `zhipu` and the claimed run must be `live` |
| `OFFICIAL_ACCOUNT_REVIEWER_ENFORCE_ACKNOWLEDGEMENT` | ignored by identity/fingerprint | exactly `I_ACKNOWLEDGE_REVIEWER_ENFORCE_V1` |
| `OFFICIAL_ACCOUNT_REVIEWER_CALIBRATION_REPORT_SHA256` | ignored by identity/fingerprint | exactly 64 lowercase hexadecimal characters |
| `OFFICIAL_ACCOUNT_REVIEWER_ENFORCE_POLICY_VERSION` | ignored by identity/fingerprint | `official-account-review-enforce-v1` |
| repair timeout/output keys | ignored by identity/fingerprint | frozen, bounded, and compatible with provider timeout |

Blank acknowledgement and calibration values in `.env.example` are intentional. Configuration,
executor, and claimed-run validation all fail closed; setting only the mode never activates enforce.

### 3. Contracts

- The legacy auditor remains the only factual/privacy/safety hard gate. A legacy rejection creates
  no Reviewer intent or call. The editorial Reviewer cannot emit hard-gate issue codes.
- Observe decisions are evidence only. `accepted`, `manual_review`, `rejected`, `unavailable`, and
  `result_unknown` do not block, repair, approve, publish, or otherwise alter business release.
- Enforce accepts only an exact accepted record for the current run and article. A repairable r1
  rejection projects closed code-owned directives to one repair Writer; manual, unavailable,
  non-repairable, provider-unknown, budget denial, or any non-accepted r2 result goes to stable
  manual review. There is no r3, second repair, model substitution, or minted budget.
- The Reviewer may read only the current claimed run/task's article, source, and brand artifacts.
  Each artifact stores the exact canonical payload byte size and raw SHA-256; scope, kind, schema,
  SHA, or version mismatch fails before the provider boundary.
- Persist the request intent before any provider call. Bind `calling` to the real execution child,
  parent event, budget reservation, and model-request event created by the capability gateway; do
  not invent placeholder identifiers.
- Root, Writer, and Reviewer budgets are distinct. Root limits include both children while keeping
  the Writer allocation below the delegation threshold. Every reservation is reconciled exactly
  once on success, timeout, cancellation, validation failure, or provider exception.
- Enforce root limits include the real allocation prefix in order: initial Writer, r1 Reviewer,
  repair Writer, r2 Reviewer. Every cumulative prefix before the last child must remain below the
  70% delegation fence; sizing only from total or the largest child is invalid.
- A unique `(run_id, article_version_id)` request makes replay idempotent. A `calling` intent from
  the same attempt denotes an in-flight concurrent join/no-op; a later attempt recovers it as
  `result_unknown`, conservatively reconciles the existing reservation once, and must not call the
  provider again.
- Request and record fingerprints cover the frozen contract and immutable input/output identity.
  Provider JSON rejects duplicate keys, extra fields, changed identities, unsafe metadata, and
  negative usage.
- Trace and snapshots contain only allowlisted enums, fingerprints, counts, safe references, and
  safe provider metadata. Never store article text, prompts, raw provider bodies, credentials,
  user identifiers, query-bearing URLs, or private object paths.
- Historical official-account rows without a Reviewer record remain readable, but callers must not
  claim that they passed the new Reviewer.
- A committed revision 2 must replay its completed repair intent even when the article already
  exists, so a crash between the article commit and child completion closes the existing Writer
  allocation without another provider call.
- Active article, final accepted review, render, media, draft, handoff, and release fingerprint form
  one exact run/article/review lineage. An r1 record or manual approval cannot project to r2.
- Downgrade from revision `20260902_0044` refuses while any enforce run, repair/revision-2 evidence,
  or governed enforce root/repair/r2 allocation exists, including orphan governed evidence.
  Empty-state downgrade to `0043` and re-upgrade must succeed; `0043` retains its observe guard.

### 4. Validation & Error Matrix

| Condition | Before provider | Durable outcome | Business outcome |
|---|---:|---|---|
| Mode `off` | Yes | No Reviewer state of any kind | Existing bytes/API/status unchanged |
| Legacy hard gate rejects | Yes | No Reviewer request or record | Existing rejection behavior |
| Artifact scope/SHA/schema/version mismatch | Yes | No provider call; governed failure evidence | Fail closed as an invariant violation |
| Valid observe verdict | No | Completed request plus immutable record/artifact | Continue render/handoff/ready |
| Provider timeout/exception/result uncertainty | No | `result_unknown`, reconciled reservation, terminal trace | Continue render/handoff/ready |
| Duplicate or invalid provider JSON | No | `result_unknown`; raw body is discarded | Continue render/handoff/ready |
| Same-attempt concurrent `calling` replay | Yes | Join/no-op; do not rewrite the in-flight intent | Existing caller owns completion |
| Later-attempt `calling` replay | Yes | Recover once to `result_unknown`; no recall | Continue normal recovery |
| Enforce r1 repairable rejection | No | One repair intent/revision 2, then terminal r2 | Accept exact r2 or require manual review |
| Repair provider exception/ambiguous result | No | `result_unknown`; no provider recall or r2 allocation | Stable manual review |
| Crash after revision-2 commit | Yes on replay | Close existing repair child; no new reservation/call | Resume audit and r2 |
| Any non-accepted r2 / exhausted budget | Yes after outcome | Terminal trace; no r3 or second repair | Stable manual review |
| Populated migration downgrade | Yes | Refuse downgrade | Preserve evidence |

### 5. Good / Base / Bad Cases

**Good:** the Writer creates an article through `official.article.generate`; deterministic and
legacy checks pass; exact article/source/brand artifacts are verified; the gateway atomically
reserves the Reviewer budget, writes `MODEL_REQUESTED`, then exposes those real bindings to the
pre-call intent; a strict closed verdict is stored and the existing ready path continues.

**Base:** mode is `off`, or the legacy auditor rejects the article. The official-account flow keeps
its prior semantics and Reviewer call/row/allocation counts remain exactly zero.

**Bad:** a caller reuses an article hash from another task, changes a frozen version, sends a
duplicate-key JSON object, gives the Reviewer a Writer capability, marks a same-attempt call as
unknown, or records synthetic reservation/event UUIDs. Each is rejected or recovered without
cross-scope data access, double charging, a duplicate provider call, or a false quality claim.

### 6. Tests Required

- Unit tests must cover closed schema/rubric projection, duplicate JSON keys, provider identity and
  usage validation, role/capability separation, dynamic root budgeting, timeout/cancellation/
  exception reconciliation, and `off` fingerprint exclusion.
- PostgreSQL integration tests must cover all four verdicts, `result_unknown`, off zero drift,
  legacy-hard-gate skip, replay, same-attempt concurrency, later-attempt crash recovery, exact
  artifact binding, cross-run/task access, SHA/version tamper, and real execution foreign keys.
- Migration tests must cover `0042 -> 0043 -> 0044`, backfill revision 1, validate composite
  run/article/review constraints, refuse populated downgrade (including orphaned governed enforce
  evidence), and prove empty downgrade/re-upgrade.
- Regression tests must retain official-account worker/handoff outputs, Workbench execution
  governance, weekly DAG behavior, Ruff/format, mypy, Compose rendering, and `git diff --check`.
- Provider-backed tests are opt-in only and must never be represented as executed without separate
  authorization, credentials, and retained experiment evidence.

### 7. Wrong vs Correct

#### Wrong

```python
# Calls the model before durable intent and fabricates causal IDs afterward.
result = await reviewer.review(request)
await reviews.mark_calling(intent, reservation_id=uuid4(), request_event_id=uuid4())
```

```python
# A concurrent observer poisons the current in-flight attempt.
if intent.status == "calling":
    await reviews.mark_result_unknown(intent=intent, error_code="worker_restart")
```

#### Correct

```python
async def before_handler(binding: CapabilityInvocationBinding) -> None:
    # The gateway has already reserved budget and written MODEL_REQUESTED.
    await reviews.mark_calling(intent=intent, execution=to_review_binding(binding))

result = await gateway.invoke(..., before_handler=before_handler)
```

```python
if intent.status == "calling" and intent.attempt_number == claimed.attempt_number:
    return None  # same-attempt join/no-op
if intent.status == "calling":
    return await recover_previous_attempt_without_recall(intent)
```
