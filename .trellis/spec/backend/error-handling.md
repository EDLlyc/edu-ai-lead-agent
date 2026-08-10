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

Before Pydantic validation, a structured-copy adapter may normalize only one bounded top-level JSON
object. Accepted envelopes are: a pure object, one `json` code fence containing only that object,
or bounded non-JSON prose around one uniquely balanced object. The scanner must handle escaped
quotes, backslashes, and braces inside JSON strings. Reject array roots, multiple objects, a second
JSON structure/value, unclosed or malformed JSON, ambiguous/multiple fences, non-standard JSON
constants, and over-limit envelopes. Parse only the extracted object; never deserialize surrounding
prose. Envelope compatibility does not relax Pydantic fields, claims, bindings, enums, or limits.

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

## Catching and logging

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
