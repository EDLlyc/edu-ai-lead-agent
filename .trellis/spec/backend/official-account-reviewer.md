# Official-Account Governed Reviewer

## Scenario: Observe an independently governed editorial review

### 1. Scope / Trigger

This contract applies when the local official-account worker generates a final article and
`OFFICIAL_ACCOUNT_REVIEWER_MODE` is `observe`. The sequence is fixed:

1. deterministic article validation;
2. the existing legacy factual/privacy/safety auditor hard gate;
3. one independently governed editorial Reviewer call;
4. unchanged rendering, handoff, and ready-state behavior.

`off` is the default and must preserve the pre-Reviewer execution exactly: no Reviewer provider
call, intent, record, allocation, artifact, event, budget reservation, status change, output-byte
change, or Reviewer field in the run fingerprint/version bundle. In this implementation,
`enforce` is reserved and configuration must fail closed instead of pretending that repair exists.

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

Durable state is additive in Alembic revision `20260902_0043`:

- `official_account_review_requests` stores `pending | calling | completed | result_unknown`, the
  real attempt number, request fingerprint, immutable input hashes, contract/model versions,
  three artifact references, and real execution allocation/reservation/event references;
- `official_account_review_records` stores `accepted | manual_review | rejected | unavailable`, a
  closed issue snapshot, usage, result artifact, producer event, and record fingerprint.

The frozen configuration bundle consists of Reviewer mode/version, prompt/request/verdict/rubric/
review/repair/budget policy versions, Writer and Reviewer timeouts, Reviewer output-token ceiling,
and provider/model identity. Environment keys use the `OFFICIAL_ACCOUNT_REVIEWER_*` prefix.
Timeouts are independently bounded to 1,000--420,000 ms; provider-backed observe mode requires
both gateway timeouts to cover the provider total-timeout contract.

### 3. Contracts

- The legacy auditor remains the only factual/privacy/safety hard gate. A legacy rejection creates
  no Reviewer intent or call. The editorial Reviewer cannot emit hard-gate issue codes.
- Observe decisions are evidence only. `accepted`, `manual_review`, `rejected`, `unavailable`, and
  `result_unknown` do not block, repair, approve, publish, or otherwise alter business release.
- The Reviewer may read only the current claimed run/task's article, source, and brand artifacts.
  Each artifact stores the exact canonical payload byte size and raw SHA-256; scope, kind, schema,
  SHA, or version mismatch fails before the provider boundary.
- Persist the request intent before any provider call. Bind `calling` to the real execution child,
  parent event, budget reservation, and model-request event created by the capability gateway; do
  not invent placeholder identifiers.
- Root, Writer, and Reviewer budgets are distinct. Root limits include both children while keeping
  the Writer allocation below the delegation threshold. Every reservation is reconciled exactly
  once on success, timeout, cancellation, validation failure, or provider exception.
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
- Downgrade from revision `20260902_0043` refuses while any review request/record or governed
  `official.review:%` execution exists. Empty-state downgrade and re-upgrade must succeed.

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
- Migration tests must upgrade from `20260901_0042`, validate constraints, refuse populated
  downgrade (including orphaned `official.review:%` execution evidence), and prove empty
  downgrade/re-upgrade.
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
