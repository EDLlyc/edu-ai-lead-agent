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
  invalid credentials, or unsupported content.
- Before retrying an external side effect, inspect the persisted request fingerprint and provider
  request ID/result state.
- On exhaustion, store the terminal issue code, safe message, attempt history, and last stage;
  preserve prior successful artifacts for inspection.

Draft audit rejection may trigger a bounded regeneration attempt with typed issue codes and claim
IDs. It is not treated as a generic infrastructure retry.

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
