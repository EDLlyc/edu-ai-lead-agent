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

## Scenario: Produce truthful paired Reviewer A/B evidence

### 1. Scope / Trigger

Use `evals.official_account_reviewer_live_ab` when preparing evidence for Reviewer calibration,
portfolio claims, or resume metrics. The checked package is an evidence harness, not a provider
integration: it must remain provider-free, must not read credentials or mutable prices, and must
report `live_model_calls=0`. A real adapter, provider/model, sample/repetition count, and cost cap
require separate explicit authorization and review.

### 2. Signatures

The CLI signature is:

```text
python -m evals.official_account_reviewer_live_ab.runner \
  {prepare,preflight,live,worksheet,report,confirm-report} ...
```

- `prepare` freezes the dataset, paired initial artifacts, versions, provider/model identity,
  time window, price identity, sample/repetition cap, exact maximum call count, and total ceiling.
- `preflight` validates one explicit local authorization artifact without reading credentials.
- `live` returns the closed `executor_not_installed` failure in this provider-free package.
- `worksheet` creates the blinded worksheet and private map from imported terminal attempts.
- `report` recomputes metrics from attempts plus human judgments/adjudications and requires an
  explicit failure-ledger output path.
- `confirm-report` binds an eligible canonical report SHA and exact human confirmation to a
  non-activating calibration candidate.

`AttemptExecutor` is the only execution port. No concrete provider adapter belongs in this package.
There is no API or database signature; all live evidence is written to explicit ignored paths.

### 3. Contracts

- Baseline and treatment share the exact initial Article SHA. Baseline makes zero Reviewer calls;
  treatment permits only the prefix `reviewer_r1 -> repair_writer -> reviewer_r2`. Each phase is
  invoked at most once, a failure stops the attempt, and there is no per-case or whole-suite retry.
- The default synthetic dataset has 12 cases. With one repetition the treatment ceiling is exactly
  36 calls; a `$0.05` per-call ceiling derives a `$1.80` total ceiling rather than accepting an
  independently typed total.
- Manifest SHA and canonical authorization SHA flow through attempt plans, observations, report,
  and calibration candidate. Reports additionally bind the canonical SHA of attempts, worksheet,
  blind map, judgments, and adjudications. Missing, duplicate, extra, cross-run, cross-authorization,
  or fingerprint-mismatched evidence fails integrity checks.
- A local authorization file proves explicit input to the harness, not identity, signature, quota,
  payment, or provider receipt. A future adapter must revalidate it immediately before every
  provider boundary.
- Worksheets expose only non-semantic blind IDs and domain-separated HMAC commitments. Raw arm,
  artifact reference, and artifact SHA remain only in the `0600` blind map. Report import loads the
  worksheet, blind map, and blinding key and compares recomputed commitments in constant time.
- Human adjudication is the only primary gold. Agreement uses only independent annotators selected
  by gold adjudications for both arms of the manifest calibration subset; a disputed case requires
  an independent adjudicator. LLM-judge rows are not accepted as primary labels.
- False-accept rate uses gold negatives; false-reject rate uses gold positives. A zero denominator
  is unknown, never zero. Bootstrap resampling is paired and clustered by case; repetitions produce
  a separate variance. Reports also retain Pass@1/Pass@2, critical-defect recall, manual-review
  rate, P50/P95 latency, input/output tokens, known/unknown cost, incremental calls/latency/cost,
  failure taxonomy, and bad cases.
- Resume claims require complete evidence, the minimum sample and independent-annotation gates,
  known usage/cost, no provider failure, positive paired delta, and a positive 95% confidence-interval
  lower bound. Otherwise paired estimates and resume claims are empty and a no-uplift failure ledger
  is written. No report may silently drop failed attempts or bad cases.
- Evidence output uses a newly created `0700` directory and exclusive atomic `0600` regular files.
  Reject symlinks, unsafe parents, traversal, overwrites, tracked canonical destinations, and
  group/other-readable private inputs. CLI errors expose only closed error codes.
- `confirm-report` never changes `.env`, `OFFICIAL_ACCOUNT_REVIEWER_MODE`, a database run, or a
  production configuration. A candidate SHA is evidence for a later operator decision only.

### 4. Validation & Error Matrix

| Condition | Result | Claims |
|---|---|---|
| `prepare` without authorization | `authorization_missing`, `live_model_calls=0` | Empty |
| `preflight` with field/hash/window/budget mismatch | Closed authorization failure | Empty |
| `live` in this package, regardless of credentials | `executor_not_installed`, exit 2 | Empty |
| Executor exception or ambiguous attempt | Stop without retry; retain safe terminal attempt/failure ledger | Empty |
| Unknown token usage or cost | Preserve unknown instead of estimating precision | Empty |
| Missing/extra/duplicate/cross-run/cross-authorization evidence | `artifact_integrity`, exit 2 | Empty |
| Blind commitment, map, or key mismatch | Reject before accepting human labels | Empty |
| Missing gold class, sample, double annotation, or independent adjudicator | `insufficient_evidence` | Empty |
| Complete evidence but delta/95% CI gate fails | Eligible diagnostic report without uplift | Empty |
| Complete evidence and every claim gate passes | Hash-bound eligible report | Only report-supported scoped claims |
| Confirmation SHA/text differs from canonical eligible report | Reject candidate creation | Unchanged |

### 5. Good / Base / Bad Cases

- Good: an ignored run directory contains complete paired attempts, HMAC-blinded independent human
  labels, exact input hashes, known usage/cost, retained bad cases, and a positive clustered CI;
  an operator confirms the canonical report SHA and receives a non-activating candidate.
- Base: `prepare` runs against the synthetic dataset with no authorization. It computes the exact
  36-call/`$1.80` ceiling, writes a safe ledger, and proves zero live model calls.
- Bad: a report imports a ledger from another authorization, treats missing usage as zero cost,
  computes false accepts over all samples, leaks a raw artifact SHA to the worksheet, or emits an
  uplift from a positive point estimate whose CI includes zero. Each path fails closed.

### 6. Tests Required

- Dataset/manifest: strict JSONL, duplicate/extra/missing case rejection, paired initial SHA,
  deterministic call/cost ceilings, canonical hashes, and calibration/holdout identity.
- Authorization/execution: no env or network access, current `live` fail-closed behavior, exact
  authorization binding, allowed phase prefix, one call per phase, exception stop, zero retry, and
  conservative unknown usage/cost.
- Evidence I/O: `0700`/`0600`, atomic exclusive publish, regular-file/no-follow checks, overwrite,
  traversal, symlink, cross-run, cross-authorization, hash, and partial-artifact tamper rejection.
- Blinding/human truth: HMAC domain separation and unlinkability, no raw arm/ref/SHA in worksheet,
  constant-time validation, independent calibration annotations/adjudicator, and LLM-judge exclusion.
- Metrics/report: class-specific denominators, zero-denominator unknown, case-clustered bootstrap,
  repeat variance, bad/failure retention, minimum evidence, CI claim gate, canonical confirmation,
  privacy scan, and absence of production-mode mutation.
- Regression: Reviewer unit/contract/governance/worker/handoff tests and canonical Reviewer eval stay
  green; the canonical eval must continue to print `live_model_calls=0`.

### 7. Wrong vs Correct

#### Wrong

```python
# Unpaired artifacts, retry-until-success, and a point estimate presented as a resume claim.
for arm in ("baseline", "treatment"):
    result = await generate_new_article_and_retry(arm)
resume_claim = treatment_rate(result) - baseline_rate(result)
```

```python
# A raw artifact digest is still reversible against a public frozen dataset.
worksheet["artifact_sha256"] = observation.artifact_sha256
```

#### Correct

```python
assert baseline.initial_article_sha256 == treatment.initial_article_sha256
attempt = await executor.execute_once(plan)  # no implicit retry
```

```python
worksheet["artifact_commitment"] = blind_hmac(
    key=blinding_key,
    manifest_sha256=manifest.sha256,
    run_ref=manifest.run_ref,
    pair_ref=pair_ref,
    candidate_ref=candidate_ref,
    blind_ref=blind_ref,
    artifact_sha256=observation.artifact_sha256,
)
assert resume_claims == [] or paired_ci_low > 0
```
