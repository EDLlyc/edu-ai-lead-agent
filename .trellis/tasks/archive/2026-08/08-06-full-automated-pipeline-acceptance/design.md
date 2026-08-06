# Technical Design

## Execution Boundary

This is an operational acceptance task, not a product implementation. It invokes the existing
`backend/app/preview_run.py` entry point against `http://127.0.0.1:8000`. That runner creates a
unique preview ID and chooses an unused future business date, then calls the same public API
boundaries and workers used by the deployed pipeline.

The acceptance remains isolated from the current daily production decision by its different
business date and `preview` scoring profile. It never mutates database records outside normal APIs
and never calls the Enterprise WeChat delivery endpoints.

## Data Flow

```text
preview runner (unique preview ID + unused business date)
  -> acquisition API -> acquisition worker -> PostgreSQL + immutable source snapshots
  -> governance API -> governance worker -> governed candidates/events
  -> topic-selection API -> content worker -> selected | no_topic
  -> copy-generation API -> content worker -> validation -> audit -> accepted | typed terminal
  -> material-package API -> content worker -> visual selector -> image provider
  -> image safety validation -> private MinIO -> material package
  -> local API image download -> 1024x1024 PNG verification
  -> redacted manifest and image in output/preview/<preview-id>/
```

The runner stops after any terminal upstream outcome. `no_topic` is reported as a normal result;
`review_required` and `failed` preserve error codes and do not become successful downstream
artifacts.

## Evidence and Privacy

The final report will use manifest fields and local API projections only: run/package IDs, statuses,
versions, validated image dimensions, source title/link, selected topic, copy, and audit/validation
summaries. Provider responses, credentials, signed URLs, access tokens, and internal MinIO object
keys remain out of terminal output, artifacts, and Git.

## Preview Audit Projection Repair

`_quality_snapshot` is the single normalized projection for validation and audit records. Its status
derivation must use this precedence when `status` is absent:

1. `passed=true` or `passed=false` becomes `passed` or `failed` for deterministic validation.
2. Otherwise, `accepted=true` or `accepted=false` becomes `accepted` or `rejected` for LLM audit.
3. Otherwise, retain the caller-provided default status.

The normalized payload continues to retain `passed` and `accepted` separately. This is a pure
presentation correction: it does not change persisted audit results, validation behavior, workflow
control flow, API responses, or any external side effect. A focused unit test will assert both audit
boolean values and manifest placement to avoid a future ambiguous UI state.

## Verification and Failure Policy

- Verify Compose and API health before spending model budget.
- Execute with a bounded stage timeout. The runner writes a redacted manifest on every terminal
  path, including unexpected safe failures.
- Read the manifest and query the relevant local API resources after the runner returns. Validate
  the local PNG signature and dimensions when an image is present.
- Check the WeCom delivery API/job store only to confirm no job was created; do not invoke delivery.
- If an expected contract is broken, retain the result as evidence. A repair requires a new planning
  decision rather than direct database edits or unreviewed changes during this run.

## Rollback

No rollback is needed for normal durable test records; they are traceable local development data.
Do not delete them, run `compose down -v`, downgrade migrations, or overwrite output from prior
previews. If a command is interrupted, retain its manifest and inspect the recorded terminal state.
