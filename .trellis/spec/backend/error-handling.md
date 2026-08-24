# Error Handling

## Contract status

This is the initial greenfield error contract. Update it with actual exception and handler paths
after the first vertical slice. Error behavior must preserve the distinction between client input,
policy vetoes, deterministic validation failures, transient infrastructure failures, and terminal
pipeline failures.

## Typed failures

Define a small application-owned hierarchy in `app/core/errors.py` (or its real successor):

```python
class AppError(Exception):
    code: str = "internal_error"
    retryable: bool = False

class InputError(AppError):
    code = "invalid_input"

class NotFoundError(AppError):
    code = "not_found"

class ConflictError(AppError):
    code = "conflict"

class PolicyVetoError(AppError):
    code = "policy_veto"

class DeterministicValidationError(AppError):
    code = "validation_failed"

class TransientProviderError(AppError):
    code = "provider_unavailable"
    retryable = True
```

Provider adapters translate SDK/network exceptions into these typed failures and retain the
original exception as the cause. Application code must not branch on provider error strings.

Durable model workflows also validate returned provider identity at the application boundary.
When a generator/auditor result's `provider` or `model` differs from the claimed run bundle, raise
the non-retryable `ProviderIdentityMismatchError` with code `provider_identity_mismatch` before
validation, policy transformation, or persistence. This is a deployment/configuration mismatch,
not transient provider unavailability: retrying the same claimed run against the current adapter
would repeat or conceal the version drift.

Structured-output adapters project a terminal Pydantic `ValidationError` into a bounded,
application-owned diagnostic before crossing the provider boundary. The diagnostic contains only
normalized `loc` segments and the stable Pydantic `type`: at most 12 issues, at most eight location
segments per issue, with bounded token lengths. It must never contain `msg`, `input`, raw model
content, prompts, response bodies, or exception text. The same safe projection is used for a
bounded schema-correction prompt, structured worker logging, and durable attempt `safe_metadata`;
the external API continues to expose only the generic `invalid_provider_output` code.

This is a cross-layer contract, not an adapter-only convenience. The typed provider error carries
the diagnostic through application orchestration, and the repository serializes only the
allowlisted `loc` / `type` projection. Focused contract, worker, PostgreSQL, and API regressions
must prove nested locations remain useful, issue counts are capped, and raw values or exception
causes do not leak at any boundary.

Before Pydantic validation, approved structured-output adapters may normalize only one bounded
top-level JSON object through the shared provider helper. Current topic-rerank v3, literal v2, and
structured copy use that exact scanner; literal topic-rerank v1 retains exact-object parsing.
Historical v1/v2 topic-rerank outcomes keep their original application behavior. Accepted
envelopes are: a pure object, one `json` code fence containing only that object, or bounded non-JSON
prose around one uniquely balanced object. The scanner must handle escaped quotes, backslashes, and
braces inside JSON strings. Reject array roots, multiple objects, a second JSON structure/value,
unclosed or malformed JSON, ambiguous/multiple fences, non-standard JSON constants, and over-limit
envelopes. Parse only the extracted object; never deserialize surrounding prose. Envelope
compatibility does not relax Pydantic fields, claims, bindings, enums, limits, permutation
completeness, or priority barriers.

## Scenario: Bounded structured-output schema correction

### 1. Scope / Trigger

Use this contract when a provider adapter permits one correction after a JSON object fails a
Pydantic structured-output boundary. It prevents an opaque type name from producing the same bad
shape twice and prevents provider-controlled field names from leaking through validation locations.

### 2. Signatures

```python
async def _complete_strict_json(
    *,
    transport: _StructuredArticleClient,
    base_prompt: str,
    output_tokens: int,
    schema: type[BaseModel],
    schema_name: str,
) -> tuple[str, _ChatCompletion, tuple[int, int, int, int], int]: ...

def _safe_validation_issues(
    schema: type[BaseModel],
    error: ValidationError,
) -> tuple[ProviderValidationIssue, ...]: ...
```

### 3. Contracts

- Historical official-account v1--v7 identities keep their frozen initial system instruction and
  base user prompt exactly. The distinct v8 identity (`official-account-generator-v5-structured-output`
  with `official-account-auditor-v2-structured-output`) is the sole approved exception: its first
  system instruction carries the canonical validation schema, and the audit instruction also carries
  the tagged `accepted`/`issue_codes`/`claim_ids` conditional invariant. Both first-call forms are
  versioned contract bytes; a correction schema or invariant must not silently alter either form or
  its request fingerprint.
- The one permitted correction appends canonical, compact `schema.model_json_schema(mode="validation")`
  under a fixed tag. Bound the schema itself and then apply the existing complete prompt character
  limit before the HTTP request.
- A custom Pydantic model validator may enforce rules that generated JSON Schema does not express.
  Add a bounded, deterministic correction-only invariant schema for those rules. For
  `OfficialAccountAuditVerdict`, `accepted=true` requires empty `issue_codes` and `claim_ids`, while
  `accepted=false` requires a present, non-empty `issue_codes` array.
- Validation locations retain only integer indexes and property names present in the selected
  schema. Map every provider-created string segment to `unknown` before correction, logging, or
  persistence.
- Never include the rejected JSON, field values, exception text, raw response, prompt, or provider
  body in correction diagnostics. Exhausting the correction remains terminal
  `invalid_provider_output`; do not add another logical request.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| First object matches the selected Pydantic model | Return it with zero corrections |
| First object has a known structural error | One correction with canonical schema and safe `loc`/`type` |
| Root cross-field validator fails | Correction also carries the bounded explicit invariant |
| Error location contains an unknown field name | Replace that segment with `unknown` everywhere outside the adapter |
| Schema, invariant, or complete corrected prompt exceeds its bound | `ProviderInputLimitError`; no correction request |
| Corrected object is still invalid or has an invalid envelope | Terminal `invalid_provider_output`; exactly two logical calls total |

### 5. Good / Base / Bad Cases

- Good: a legacy-shaped first article object receives the current schema, returns a valid
  discriminated-block object on the only correction, and persists only safe usage metadata.
- Base: an already-valid object bypasses schema construction in the provider message and preserves
  the frozen first-call bytes.
- Bad: tell the provider only "return `GeneratedArticleDraft`", echo an unknown extra-field name,
  omit a custom cross-field invariant, or issue a third completion after correction failure.

### 6. Tests Required

- Assert the first user prompt is byte-equal to the frozen prompt builder output and contains no
  correction tags.
- Make the second fake response valid only when the canonical schema tag is present; assert block
  discriminator requirements are included and raw value sentinels are absent.
- Exercise the audit root invariant with an invalid `accepted`/issue combination; require the exact
  conditional invariant before the fake returns a valid verdict.
- Assert generation corrections never inherit audit-only invariants, unknown provider field names
  become `unknown`, prompt bounds stop before a second request, and exhausted correction makes
  exactly two logical calls.

### 7. Wrong vs Correct

#### Wrong

```python
correction = f"Return {schema.__name__} again: {error}"
```

This exposes uncontrolled error text and gives the provider neither the executable structure nor
custom cross-field rules.

#### Correct

```python
schema_json = canonical_json(schema.model_json_schema(mode="validation"))
issues = safe_schema_locations(schema, validation_error)
correction = tagged_bounded_schema(schema_json, invariant_for(schema), issues)
```

The correct form preserves the first-call prompt, gives one bounded repair enough structural
information, redacts provider-created locations, and remains terminal after that repair fails.

Topic reranking distinguishes bounded internal `topic_rerank_completion_invalid`,
`topic_rerank_json_envelope_invalid`, and `topic_rerank_schema_invalid` stages. After a valid chat
completion envelope, an invalid content body keeps only the safe prompt fingerprint, non-negative
usage counters, latency, and normalized `loc`/`type` entries. Topic-specific location projection
retains only stable schema segments and integer indexes; provider-controlled extra-field names map
to `unknown` rather than entering diagnostics. It never carries raw content, candidate text, prompt
text, response bodies, credentials, or exception strings. Application and durable/API projections
still expose only `invalid_provider_output`, perform no schema-repair model call, and preserve the
exact deterministic base order.

Current v3 finalization failures are typed domain outcomes rather than exceptions. A request
fingerprint, pool, event/version, candidate availability, priority/final-set barrier, same-day, or
cap mismatch must produce the exact deterministic fallback without a second provider call.

Expected outcomes such as `no_topic` are domain/run results, not exceptions. A hard veto can be a
typed control failure inside a stage, but it must be persisted as a structured veto result rather
than presented as an unhandled system error.

## API responses

Register centralized FastAPI exception handlers. Return a stable problem response without stack
traces, prompts, SQL, provider payloads, or secrets:

```json
{
  "error": {
    "code": "pipeline_run_conflict",
    "message": "A run already exists for this schedule date.",
    "request_id": "01J...",
    "details": {}
  }
}
```

Use status codes consistently: 400/422 for invalid input, 404 for absent resources, 409 for
idempotency/state conflicts, 429 for rate limits, and 500/503 for unexpected or unavailable
dependencies. A `202 Accepted` enqueue response returns a durable run identifier and status URL.

Messages shown to internal users should explain the next safe action. Detailed diagnostics belong
in structured logs linked by `request_id`, not in the response.

## Worker retries and terminal states

- Retry only errors explicitly classified as transient (timeouts, rate limits, temporary provider
  unavailability, lease loss before side effects).
- Use bounded exponential backoff with jitter and a configured maximum attempt count.
- Do not blindly retry schema failures, missing evidence, policy vetoes, prompt-injection findings,
  invalid credentials, unsupported content, or durable provider/model identity mismatches.
- Treat brand section/chunk exact-slice, parent-version FK, content/claim enum, and embedding-input
  hash mismatches as terminal ingestion defects; never persist a partially ready version.
- Before retrying an external side effect, inspect the persisted request fingerprint and provider
  request ID/result state.
- On exhaustion, store the terminal issue code, safe message, attempt history, and last stage;
  preserve prior successful artifacts for inspection.

Draft audit rejection may trigger a bounded regeneration attempt with typed issue codes and claim
IDs. It is not treated as a generic infrastructure retry.

Ordinary copy editorial findings and ordinary image OCR/visual-quality findings are recoverable
warnings. Each stage may consume at most one targeted repair; a remaining warning does not block a
package when no hard safety, evidence, provenance, output-integrity, or publishing-boundary error
exists. After the image repair budget or a single provider-rejection neutralization is exhausted,
the worker may render one already-reserved, topic-matched brand-catalog reference. The fallback is
validated and stored through the normal private immutable path, records a typed initial error, and
never makes a third provider request. Missing/invalid references or storage failure remain
`review_required`/failed terminal states.

Perceptual similarity repair is a separate one-use budget, not a provider/network retry, an OCR or
quality repair, or provider-rejection neutralization. A near duplicate on the first controlled
plan schedules the pre-reserved alternate. A safe near duplicate on the alternate succeeds with
`near_duplicate_after_retry`; it must not be converted into `review_required`, retried a third
time, or allowed to override a safety/integrity failure. See
[`visual-diversity.md`](./visual-diversity.md).

## Scenario: Direct Comfly raster generation response

### 1. Scope / Trigger

`OpenAICompatibleImageGenerator` is an OpenAI-compatible adapter, not a JSON-only adapter. The
Comfly creation endpoint may return a completed raster directly instead of a JSON URL, Base64
envelope, or task identifier. Treating every non-JSON HTTP 200 response as
`image_provider_rejected` causes a false retry and hides a valid model image behind the catalog
fallback.

### 2. Signatures

```python
async def generate(request: ImageGenerationRequest) -> ImageGenerationResult: ...

class ImageProviderRejectedError(ProviderError):
    def __init__(
        self,
        *,
        http_status: int | None = None,
        response_kind: str | None = None,
    ) -> None: ...
```

The only permitted `response_kind` values are `json`, `raster`, and `other`.

### 3. Contracts

- `POST /v1/images/generations` with a successful `Content-Type` of `image/png`, `image/jpeg`, or
  `image/webp` is a direct candidate output. Validate bounded bytes, matching signature, and the
  required 1024x1024 dimensions before returning `ImageGenerationResult`.
- JSON URL, JSON Base64, and asynchronous task responses continue through their existing JSON
  decoder and output-host/download checks.
- If a syntactically valid creation JSON envelope is structurally unsupported while extracting an
  image representation, preserve only the already-allowlisted HTTP status and normalized response
  kind on `ImageProviderRejectedError`. This distinguishes a provider's `200` JSON error/envelope
  from a local output-validation failure without retaining its fields or content.
- A direct raster result never schedules provider-rejection recovery or a brand-catalog fallback.
- A true `ImageProviderRejectedError` may expose only integer HTTP status and the allowlisted
  response kind to the material-package warning event. Do not persist or log raw bodies, prompts,
  response headers, URLs, credentials, or private image data.

### 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| 2xx allowed raster type, valid signature and 1024x1024 dimensions | Return success and persist generated image normally |
| 2xx allowed raster type with invalid signature, dimensions, or byte size | `ImageOutputValidationError` with an allowlisted reason |
| 2xx JSON URL/Base64/task envelope | Existing JSON behavior |
| 2xx JSON envelope with no supported image/task representation | `ImageProviderRejectedError(http_status=200, response_kind="json")` |
| 2xx non-raster non-JSON body | `ImageProviderRejectedError(http_status=200, response_kind="other")` |
| 3xx/4xx provider response | `ImageProviderRejectedError` with safe status/kind when available |
| 401/403, quota, rate limit, timeout, or 5xx | Existing typed authentication/quota/transient errors |

### 5. Good / Base / Bad Cases

- Good: a direct `image/png; charset=binary` response passes signature and dimension checks and is
  stored as a generated image.
- Base: a JSON response with a signed external URL follows existing safe DNS resolution and bounded
  download behavior.
- Bad: decoding a `text/plain` success body as an image, logging its text, or treating an invalid
  raster as a successful image.

### 6. Tests Required

- Mock direct PNG, JPEG, lossy WebP (`VP8`), and lossless WebP (`VP8L`) creation responses; assert
  no task poll or URL download occurs.
- Assert invalid or oversized direct raster bytes raise `ImageOutputValidationError`.
- Assert a non-raster non-JSON body remains rejected, preserves only safe diagnostics, and never
  exposes its content through `str`, `repr`, or the material-package log event.
- Keep existing URL, Base64, task-polling, authentication, quota, and multi-reference tests green.

### 7. Wrong vs Correct

#### Wrong

```python
created = await request_json("POST", "/v1/images/generations", payload)
```

This assumes every successful provider response is JSON and converts direct raster success into a
provider rejection.

#### Correct

```python
response = await request("POST", "/v1/images/generations", json=payload)
direct = normalize_direct_raster(response)
if direct is not None:
    return direct
created = decode_json_envelope(response)
```

The direct branch shares the existing byte/signature/dimension validation and the JSON branch stays
unchanged.

## Scenario: Documented Comfly gpt-image-2 task envelope

### 1. Scope / Trigger

This applies when changing the Comfly `gpt-image-2` creation payload or interpreting a JSON task
response. The provider documentation defines a bounded field set and nests asynchronous result
images below task metadata. Keeping undocumented creation fields or treating task metadata as an
image causes false `image_provider_rejected` failures.

### 2. Signatures

```python
POST /v1/images/generations
GET /v1/images/tasks/{task_id}

async def OpenAICompatibleImageGenerator.generate(
    request: ImageGenerationRequest,
) -> ImageGenerationResult: ...
```

### 3. Contracts

- The creation JSON contains `model`, `prompt`, `size`, optional ordered `image`, and explicit
  `response_format="url"`. Do not send `aspect_ratio`, which is not in the published
  `gpt-image-2` contract.
- A completed documented task response is accepted only in this shape:

  ```json
  {
    "data": {
      "task_id": "safe-provider-id",
      "status": "SUCCESS",
      "data": {"data": [{"b64_json": "..."}]}
    }
  }
  ```

- Decode only the fixed documented nesting. Do not recursively scan arbitrary provider objects.
  A queued task remains pending; a completed task without exactly one non-empty string `url` or
  `b64_json` remains a typed rejection. The alternate representation may be omitted or present as
  an empty string, but explicit null/non-string values and two non-empty representations remain
  rejected. Provider bodies, temporary URLs, prompts, and credentials stay inside the adapter.

### 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Creation payload has documented fields and direct `data[0].url` | Safely download and validate the 1024x1024 raster |
| Provider returns a valid `data[0].b64_json` compatibility response | Strictly decode and validate the same raster gates |
| Non-empty Base64 is not a valid representation | `ImageOutputValidationError(reason="image_output_representation_invalid")`; one durable output recovery, then catalog fallback |
| Task response has documented `data.data.data[0].b64_json` | Decode and validate the 1024x1024 raster |
| Task is queued/pending and has no result | Continue bounded polling |
| Completed task lacks one valid image representation | `ImageProviderRejectedError` with safe status/kind only |
| HTTP 200 declares JSON but body is not parseable JSON | `ImageProviderRejectedError(http_status=200, response_kind="json")` |

### 5. Good / Base / Bad Cases

- Good: the request explicitly asks for URL output and a signed URL follows the existing
  public-DNS and bounded-download rules.
- Base: a valid Base64 compatibility response decodes through the same size/signature validation.
- Bad: send an undocumented `aspect_ratio`, accept a result from arbitrary nested `data` objects,
  or expose the provider envelope while diagnosing a failure.

### 6. Tests Required

- Assert the Comfly payload includes `response_format="url"`, retains `size="1024x1024"`,
  and omits `aspect_ratio`.
- Assert invalid Base64 exposes only `image_output_representation_invalid`, never its raw value,
  and that URL/raster/security reasons remain terminal rather than entering output recovery.
- Mock the exact documented `data.task_id` and `data.data.data[0].b64_json` response; assert one
  task lookup produces a validated image with no URL download.
- Keep malformed JSON-envelope tests proving only status and response kind escape the adapter.

### 7. Wrong vs Correct

#### Wrong

```python
payload = {"model": model, "prompt": prompt, "size": "1024x1024", "aspect_ratio": "1:1"}
task_id = created["task_id"]
```

This retains an undocumented parameter and misses the documented nested task ID.

#### Correct

```python
payload = {
    "model": model,
    "prompt": prompt,
    "size": "1024x1024",
    "response_format": "url",
}
task_id = first_value(created, "task_id", "id")
result = extract_documented_task_image(completed)
```

The decoder accepts only known direct or documented nested image representations, then reuses the
normal bounded raster validation path.

### 8. Break-loop prevention: representation failure bypassed compensation

- **Root cause — cross-layer contract plus implicit assumption:** the adapter correctly classified
  strict Base64 decode failure as `ImageOutputValidationError`, but material orchestration attached
  its one-use compensation only to `ImageProviderRejectedError`. The recovery state machine
  implicitly treated every output-validation failure as a hard raster/security failure even though
  the adapter had already exposed a safe, discriminating representation reason.
- **Coverage gap:** adapter tests proved strict decoding and worker tests proved provider-rejection
  fallback independently, but no non-isomorphic test carried an invalid representation through the
  provider-to-worker boundary. Repeating provider-rejection fixtures could not reveal the missing
  classification edge.
- **Structural prevention:** only the exact allowlisted reason
  `image_output_representation_invalid` may consume the compatibility output-recovery counter. Its
  durable snapshot rehydrates `initial_error_code=image_output_invalid`, keeps the prompt/plan
  unchanged, and selects a distinct stable request fingerprint. All URL/address, redirect,
  media/signature, size, dimensions, identity, OCR parser, and integrity reasons remain terminal.
- **Regression prevention:** the required matrix pairs invalid Base64 with unsafe URL, bad address,
  media mismatch, oversize, bad signature, and wrong dimensions; it asserts first recovery,
  recovery success, second-failure catalog success, corrupt/missing/store terminal results, no raw
  sentinel projection, and no third provider call.

## Catching and logging

Visual retrieval distinguishes disabled, input-normalization failure, provider unavailable, invalid
output, identity mismatch, incomplete index, and catalog change. Material orchestration converts all of these to the bounded
`semantic_unavailable` audit state and runs the existing deterministic selector. It never retries a
provider query inside one material attempt and never substitutes a different vector space.

Catch exceptions only where code can translate, compensate, add structured context, or define an
API/process boundary. Do not catch `Exception` around ordinary business logic and continue with a
partial result. API and worker top-level boundaries may catch unexpected exceptions to log them,
mark state safely, and return/exit without leaking details.

Log an error once at the boundary that owns the failure. Inner layers should add typed context or
re-raise with `raise ... from exc`, not repeatedly log the same stack.

Cancellation and shutdown signals are not ordinary failures. Release claims or let leases expire,
record an interrupted attempt when possible, and allow graceful process termination.

## Avoid

- Returning HTTP responses from repositories or application services.
- Using `None` to mean not found, provider failure, veto, and parse failure interchangeably.
- Exposing raw exception messages to clients.
- Marking every LLM refusal or validation issue retryable.
- Swallowing an error and transitioning a run to success.
- Losing the run/job identifiers needed to correlate a failure.
