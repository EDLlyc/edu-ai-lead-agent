# Logging and Observability Guidelines

## Initial contract

Emit machine-readable JSON logs from API, scheduler, and worker processes. The concrete library is
an implementation choice for the first slice (standard `logging` with a JSON formatter or
`structlog` are acceptable), but all modules must use the same configured interface. Update this
guide with the real configuration and call sites after that slice.

## Required fields

Every log event contains `timestamp`, `level`, `event`, `service`, `environment`, and
`application_version`. Add the identifiers relevant to the execution boundary:

- API: `request_id`, route template, method, status code, duration.
- Pipeline: `pipeline_run_id`, `stage`, `job_id`, `attempt`, `pipeline_version`.
- Source work: `source_id`, `article_id`, or `event_cluster_id` without logging full content.
- Model/provider calls: provider, capability, model, prompt version, duration, token/cost counts,
  request fingerprint, and safe provider request ID.
- Validation/audit: verdict, issue codes, claim coverage counts, and policy version.

Prefer stable event names and structured values:

```python
logger.info(
    "pipeline_stage_completed",
    extra={
        "pipeline_run_id": str(run.id),
        "stage": stage.value,
        "attempt": attempt,
        "duration_ms": duration_ms,
        "artifact_count": len(artifacts),
    },
)
```

Do not interpolate business data into the event name.

## Levels

- `DEBUG`: development diagnostics such as safe counts or ranking components. Disabled in normal
  production operation and still subject to redaction.
- `INFO`: lifecycle events, state transitions, schedules enqueued, stages completed, packages
  ready, and expected `no_topic` outcomes.
- `WARNING`: recoverable degradation, retry scheduling, missing optional metadata, nearing limits,
  or audit rejection that will be regenerated.
- `ERROR`: terminal job failure, exhausted retries, corrupted state, or dependency failure that
  prevents the requested operation. Include an exception stack only at the owning boundary.
- `CRITICAL`: broad integrity or availability threats requiring immediate intervention, not an
  alias for ordinary generation failure.

## Privacy and secret handling

Never log:

- API keys, cookies, authorization headers, database URLs, or social-platform credentials;
- full prompts/responses, complete fetched pages, embeddings, or raw HTML by default;
- minors' names, contact details, images, school/class identifiers, or other personal data;
- signed object-storage URLs or full internal storage credentials;
- raw model/provider payloads that can contain source content or sensitive configuration.

Log hashes, IDs, counts, byte lengths, classifications, and approved short excerpts instead. Any
debug-content logging must be explicitly gated, redacted, access-controlled, and disabled in
production. Typed settings and HTTP clients must redact secrets in their representations.

## Prompt injection and untrusted content

Fetched pages, social leads, filenames, model output, and source metadata are untrusted. Do not
emit them as event names or terminal-control text. Preserve content in access-controlled artifact
storage when needed for audit, and log only its ID/hash. Record detection results and policy codes,
not the malicious instruction itself unless a separately secured forensic workflow requires it.

## Metrics and auditability

Logs complement, but do not replace, durable run/audit records. Emit metrics for:

- scheduled versus completed runs, stage latency, queue age, lease expiry, and retry count;
- candidate count, eligible count, veto/no-topic rate, and repeated-topic blocks;
- claim evidence coverage, deterministic validation failures, and LLM audit rejection;
- provider latency, errors, token/image usage, and estimated cost;
- package-ready time and manual copy/download actions when collected lawfully.

Use correlation IDs to link logs to persisted artifacts. Record prompt, parser, scoring, model,
embedding, and policy versions in durable data as well as relevant events.

The copy/image recovery path uses bounded, queryable events such as
`material_package_image_quality_transition`, `material_package_image_attempt_finished`,
`material_package_image_fallback_requested`, and `material_package_image_fallback_ready`.
These events may include package/image IDs, attempt and repair counters, typed error codes,
fallback state, next action, asset ID, renderer version, dimensions, and byte size. They must not
include prompts, source/copy text, provider payloads, URLs, object keys, filenames/paths, image
bytes, or secrets. Quality warnings and fallback use are degradation events, not silent success;
the durable package snapshot remains the source of truth for the final state.

Controlled visual diversity adds the bounded
`material_package_image_diversity_retry_scheduled` event. It may contain package/image IDs, active
plan ordinal, retry count, policy version, candidate count, threshold/distance, and the controlled
decision code. It must not contain perceptual hashes, nearest object IDs, plan seeds, prompts,
reference paths, image bytes, provider bodies, or content text. The final warning is durable
artifact/package state; it is not inferred from log prose.

Topic-rerank invalid-output observation may include only run/context IDs, policy/provider/model,
the generic durable failure, safe prompt/request fingerprints, candidate count, usage/latency, and
bounded internal stage plus normalized validation `loc`/`type` values. Never log the system/user
message, candidate title/summary, completion content, response body, provider exception text, or
credential. The durable rerank row retains the generic `invalid_provider_output` category rather
than the internal diagnostic stage.

## Avoid

- `print()` in application code.
- Logging the same exception in every layer.
- Dynamic prose-only logs that cannot be queried reliably.
- Treating logs as the sole history of pipeline state.
- Logging content merely because the product is internal.
