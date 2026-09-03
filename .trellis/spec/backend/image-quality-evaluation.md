# Image-Quality Evaluation and Final-Publication Observation

## 1. Scope / Trigger

Use this contract when changing the provider-free image-quality harness, the optional official-
account final-publication observer, generated-visual persistence, or editor-handoff visibility
claims. The observer evaluates the publication artifact produced after center crop and JPEG
encoding. It is evidence only: `observe` must not become a release gate or regeneration policy.

## 2. Signatures

- Shared domain: `app.domain.image_quality_eval`
  - `build_image_eval_issue(...) -> ImageEvalIssue`
  - `build_image_eval_observation(...) -> ImageEvalObservation`
  - `decide_image_eval(...) -> ImageEvalDecision`
  - `decide_image_eval_batch(...) -> ImageEvalBatchDecision`
  - `active_image_eval_rubric() -> ImageEvalRubric`
- Provider port: `ImageQualityAuditor.audit(ImageQualityAuditRequest) -> ImageQualityAuditResult`.
  `ImageQualityAuditRequest` carries final bytes, media type, a SHA-256 request fingerprint,
  bounded per-image criteria, prompt/rubric versions, and typed reference images.
- Repository completion:
  `persist_generated_visual(claimed, plan, result, eval_result=None)` must mark the visual ready and
  insert the optional immutable eval row in one fenced transaction.
- Repository projection:
  `list_generated_visual_evals(run_id=...)` performs one bounded batch query; ORM relationships and
  per-visual lazy loads are not used.
- Alembic `20260901_0041` adds `official_account_generated_visual_evals` and the parent composite
  unique key `(id, run_id, sha256)` used by the child final-hash foreign key.

## 3. Contracts

- `IMAGE_QUALITY_EVAL_MODE` is `off|observe` and defaults to `off`.
- `off` performs no quality-provider call and creates no eval row. Existing ready behavior remains
  unchanged.
- `observe` audits the exact final `image/jpeg`, `1536x1024` bytes. It records `accepted`,
  `manual_review`, `rejected`, or `unavailable` but does not change readiness or release gates.
- A single-image provider record covers exactly semantic faithfulness, IP identity, OCR/text,
  aesthetics/artifacts, and publication layout. Batch diversity remains a separately reported
  offline/future batch-evaluator dimension and must not be claimed from one image.
- The approved reference is normalized with the plan's frozen image-input version and its PNG
  checksum must equal `plan.reference_input_checksum` before it is sent to the auditor.
- Each child row is immutable and unique per generated visual. Its composite foreign key binds
  `generated_visual_id`, `run_id`, and `publication_sha256` to the ready parent result. The record
  stores only bounded versions, fingerprints, decisions, normalized observations, safe issue
  codes, and optional provider/model identity.
- `record_fingerprint` covers the visual/run IDs, final SHA-256, request fingerprint, versions,
  provider/model, normalized observations, and aggregate decision. It excludes completion time.
- Never persist image bytes, scene criteria, raw prompts, provider bodies, vectors, private paths,
  bucket keys, or free-form provider explanations in an eval row.
- Handoff emits `durable_image_audit_accepted` only for a recomputed, current-version accepted
  record whose request fingerprint, record fingerprint, run/visual identity, and final SHA-256 all
  match. Every absent, unavailable, warning/review, rejected, stale-version, or mismatched record
  projects `passed_local_visual_inspection`; it does not make a ready visual undeliverable.
- A ready historical row without an eval child is never backfilled by a paid call during recovery.

## 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Mode is not `off|observe` | Settings/executor construction rejects it |
| `observe` with no usable adapter or credentials | Five unavailable observations; ready still commits |
| Provider timeout or typed transport failure | `unavailable/provider_unavailable`; no raw error persisted |
| Invalid provider schema | `unavailable/invalid_output` |
| Provider/model/request fingerprint mismatch | `unavailable/identity_mismatch` |
| Unknown provider issue code | Stable `provider_audit_unclassified` warning and manual review |
| Critical closed issue | Aggregate `rejected`; aesthetic scores cannot offset it |
| Warning without critical issue | Aggregate `manual_review` |
| Final SHA or normalized reference checksum mismatch | Reject the attempted binding; never claim accepted |
| Lease/fencing loss before completion | No ready transition and no eval child |
| Stored observation/decision/record fingerprint drift | Repository treats the row as invalid |

## 5. Good / Base / Bad Cases

- Good: `observe` audits the prepared JPEG, MinIO content-addressed storage succeeds, and one
  fenced commit writes both ready metadata and an accepted, hash-bound child. Handoff may claim
  `durable_image_audit_accepted`.
- Base: mode is `off`, or a historical visual is already ready without a child. It remains
  deliverable and handoff says `passed_local_visual_inspection`.
- Good degraded case: the adapter is unavailable or returns a typed failure. The same completion
  transaction writes ready plus an unavailable child; release behavior is unchanged.
- Bad: persist ready first and insert eval in a second transaction. A crash creates a ready row
  with missing evidence and recovery skips the paid provider call.
- Bad: audit raw provider output before publication crop/compression, or send JPEG reference bytes
  under a PNG media type. Neither result is evidence about the delivered artifact.

## 6. Tests Required

- Domain/runner: strict schema, closed taxonomy, five-dimension batch aggregation, six-dimension
  fixture coverage, duplicate/malformed/hash/canonical drift, critical false-pass, and manual
  review metrics.
- Provider adapter: criteria, prompt/rubric version, closed single-image issue codes, final JPEG,
  typed normalized PNG reference, and strict structured output.
- Worker service: default off makes no auditor call; observe uses final bytes; accepted, warning,
  critical, empty rejection, and unavailable branches; storage/lease failure; ready recovery makes
  no audit call.
- Repository/PostgreSQL: ready+eval atomicity, exact replay behavior, composite hash/run FK,
  one-record uniqueness, JSON/decision constraints, old ready rows without children, record
  fingerprint validation, empty downgrade success, and populated downgrade refusal.
- Handoff: exact current accepted record yields durable status; no record and every other decision,
  hash/version/fingerprint mismatch yield local-inspection status without failing the ready gate.
- Canonical command: `make image-quality-eval` must remain provider-free and use `--check` in CI.

## 7. Wrong vs Correct

### Wrong

```python
stored = await repository.persist_generated_visual(claimed=claim, plan=plan, result=result)
await repository.insert_eval(stored.id, provider_observation)  # second transaction
```

This permits `ready` without its claimed evidence after a crash and invites recovery-time duplicate
provider calls.

### Correct

```python
eval_result = await observe_final_publication(prepared.image_bytes) if mode == "observe" else None
stored = await repository.persist_generated_visual(
    claimed=claim,
    plan=plan,
    result=prepared.result,
    eval_result=eval_result,
)
```

The provider call stays outside the transaction, while ready metadata and the optional immutable
record share one fenced commit.

## Scenario: Produce bounded single-model image calibration evidence

### 1. Scope / Trigger

Use this scenario when changing `evals.image_quality_panel`, its shared `evals.model_panel`
contracts, or the explicit app-level live composition. This experiment is separate from both the
provider-free canonical harness and the production single-image observer. Its output is automated
single-model calibration evidence only and must never be described as Human Gold, consensus,
agreement, or a production activation decision.

### 2. Signatures

- Provider-free preflight: `python -m evals.image_quality_panel.runner preflight`.
- Provider-free `live` remains fail-closed and never reads credentials or chooses endpoints.
- App composition: `python -m app.image_quality_panel_main
  {prepare|authorize|preflight|live}`.
- Live composition injects exactly one direct-Zhipu `OneShotExecution` into
  `execute_image_plan(...) -> ImagePlanExecutionResult`.
- `IMAGE_QUALITY_AUDIT_MODEL` independently selects the production vision auditor identity and
  defaults to `glm-5v-turbo`; it must not inherit `AI_CHAT_MODEL`.
- The production single-image quality auditor uses the same closed Zhipu visual request dialect:
  omit `response_format` and `temperature`, disable thinking, and set `do_sample=false`. The OCR
  adapter's existing JSON-object request profile remains separate and unchanged.

### 3. Contracts

- The dataset contains 48 deterministic pairs derived from six public source families. Report
  `effective_source_cluster_n=6`; never claim 48 independent real images. Calibration and holdout
  are disjoint by source family.
- The unique evaluator receives exactly `48*2 + 12*2 = 120` AB/BA calls. The first call is the
  four-image diversity capability case. A non-completed first call stops the whole plan without
  retry, fallback, or replacement probe.
- The only route is direct Zhipu `glm-5v-turbo` at exactly
  `https://open.bigmodel.cn/api/paas/v4/chat/completions`. The returned model identity must exactly
  match `glm-5v-turbo`; the image-panel path must not construct a ToAPIs or `glm-4.6v` transport.
- Pricing is an operator-reviewed, self-hashed snapshot. It carries a source digest, native token
  rates, conservative per-call reservation, `effective_at`, and `expires_at`; its validity window
  covers the manifest execution window. The only provider budget is the Zhipu `cny` budget capped
  at 100 CNY. Do not add guessed rates or currency conversion.
- Before reading credential values, validate source rights/blob/content hashes, the derived dataset,
  manifest self-hash, authorization self-hash/window, pricing self-hash/window, all 120 request
  fingerprints/artifacts, and the complete cost ceiling. Then atomically create a previously
  nonexistent `output/evals/**` live directory through `SecureEvidenceStore`; it must be
  gitignored, untracked, owner-only `0700`, and empty.
- The only image-panel live credential variable is `AI_PLATFORM_API_KEY`; the image-panel path must
  not read `TOAPIS_API_KEY` or `ZHIPU_API_KEY`. Construct `httpx.AsyncClient(trust_env=False)`.
  Never print credentials, prompts, provider bodies, private paths, or image bytes.
- Privacy scanning treats only schema-named lowercase 64-hex SHA/fingerprint values and the exact
  hash-derived `attempt-`/`pair-`/`blind-`/`imgblind-` reference formats as opaque. Incidental digit
  runs inside those values are not PII; malformed digests, ordinary fields, prohibited keys,
  paths, and secret-shaped values remain fail-closed.
- `SecureEvidenceStore.write_json_exclusive` writes one canonical JSON object with no leading or
  trailing whitespace, matching its strict single-object loader. JSONL writers alone append one
  newline per record. Do not relax `strict_json_object` for stored artifacts or the default
  Reviewer response profile; a previously written newline-bearing immutable object is invalid and
  requires a new run.
- Only the closed `zhipu-vision-v1` judge-content profile may trim outer whitespace or unwrap one
  standalone lowercase `json` Markdown fence. It must then pass the same duplicate-key rejecting
  exact-object parser, strict schema and arm invariants, and request-scoped issue-code allowlist.
  Prose, multiple objects/fences, malformed fences, extra keys, and invalid arrays remain rejected.
  Persist only `judge_content_framing_invalid`, `judge_content_schema_invalid`, or
  `judge_content_policy_invalid`; retain generic `judge_content_invalid` and
  `invalid_provider_output` only for evidence compatibility.
- Image arm verdicts use exact keys. `accept` requires `critical=false` and no issues; `reject`
  requires a boolean critical flag and at least one allowed issue; `abstain` requires
  `critical=null` and no issues. Issue arrays are unique, lexically sorted, and allowlisted. Prompt
  or adapter changes require a new version and a fresh manifest/authorization.
- A request crosses the provider boundary at most once. Missing usage or separately priced missing
  reasoning usage remains unknown and reconciles at the conservative reservation. A timeout,
  connection ambiguity, 5xx, or adapter crash records `result_unknown`; it is never retried.
- Votes contain pair preference plus A/B decision, critical flag, and closed issue codes. Reports
  retain failures and abstentions, distinguish case count from source-cluster count, and emit only
  a `non_activating=true` candidate artifact. Objective recipe gold is the only correctness source.
- Subjective cases have no external correctness label. Report only the unique evaluator's AB/BA
  position conflict, repeat consistency, coverage, and abstention with `single_model_only=true` and
  `external_label_n=0`; do not emit consensus, agreement, target-to-proxy, or Fleiss-kappa metrics.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Source lacks explicit external-evaluation basis or tracked clean hash | Fail before credentials |
| Manifest/request/authorization/pricing/file hash mismatch | Fail before credentials |
| Pricing window does not cover the execution window | Fail before credentials |
| Existing or non-gitignored live output path | Reject; require a new run path |
| Mixed zero-hash and bound request authorizations | Reject before credentials |
| PII regex matches only inside a validated digest/HMAC reference | Treat the opaque value as safe |
| The same PII text occurs in an ordinary or malformed-digest field | Reject as privacy-unsafe |
| Single-object JSON has leading/trailing whitespace | Reject; create a new canonical artifact |
| Zhipu judge content is one exact fenced JSON object | Normalize the fence, then apply strict schema/policy |
| Judge content has prose/multiple objects, bad schema/invariants, or disallowed issues | Record the corresponding closed framing/schema/policy failure; retain no raw content |
| JSONL row has no terminating newline or contains a blank row | Reject as incomplete evidence |
| Planned conservative provider total exceeds the Zhipu CNY cap | Reject before credentials |
| Returned model differs from requested model | One terminal identity failure; no retry |
| Usage or separately priced reasoning usage is missing | `result_unknown`; charge reservation |
| First four-image capability attempt is not completed | Stop the plan and report incomplete |
| Plan is interrupted or incomplete | Nonzero exit; journal remains crash-visible and the run path cannot be reused |
| Production image-eval mode is `off` | No production auditor call or record change |

### 5. Good / Base / Bad Cases

- Good: an operator freezes a source-backed pricing snapshot whose window covers the manifest,
  prepares and authorizes one 120-call plan, passes zero-secret preflight, and runs into a new
  private output path. Every attempt is journaled before the one-shot call.
- Base: provider-free preflight rebuilds all 48 cases and reports `live_calls=0`; canonical
  `make image-quality-eval` remains unchanged and in normal CI.
- Bad: use an existing run directory, read a ToAPIs credential, accept a gateway model alias,
  continue after a failed capability call, generate a subjective proxy label, or promote the
  candidate artifact into production configuration.

### 6. Tests Required

- Assert the single exact `glm-5v-turbo`/Zhipu endpoint route, `AI_PLATFORM_API_KEY`-only bearer
  routing, `trust_env=False`, one HTTP attempt on failures, and exact returned identity.
- Assert 120 request fingerprints, AB/BA inversion, four-image first call, family-disjoint split,
  six effective clusters, reference-image rules, and single-model position/repeat stability.
- Assert snapshot self-hash, native units/caps, conservative reservation equality, increasing
  timezone-aware validity, and full execution-window coverage.
- Assert no credential read before every evidence check and new-run creation; reject mixed
  authorization, any existing output path, unknown usage, and incomplete execution.
- Assert cancellation leaves crash-visible incomplete evidence and never permits a run-directory
  reuse or selective continuation.
- Assert nested BaseModel/sequence SHA and fingerprint fields ignore incidental numeric substrings,
  while the same substrings in ordinary, malformed-digest, path, and secret fields still fail.
- Assert `write_json_exclusive` bytes equal canonical JSON exactly and round-trip through
  `load_json_model`; newline-bearing single objects remain rejected while JSONL retains delimiters.
- Assert Zhipu-only exact-fence normalization plus fail-closed prose, multiple-object/fence,
  duplicate-key, extra-field, arm-invariant, array-order, and issue-allowlist classifications; the
  default Reviewer profile must still reject whitespace and Markdown wrappers.
- Re-run production observer/default-off/factory wiring and provider-free canonical commands.

### 7. Wrong vs Correct

#### Wrong

```python
# Ambient proxy credentials, an existing output path, and a silent retry invalidate evidence.
client = httpx.AsyncClient()
result = await retry(judge(request))
```

#### Correct

```python
preflight_all_hashes_and_native_caps()
run_dir = secure_store.create_run_directory(new_output_path)
client = httpx.AsyncClient(trust_env=False)
attempt = await one_shot_execution.execute(identity=identity, request=request, material=material)
```
