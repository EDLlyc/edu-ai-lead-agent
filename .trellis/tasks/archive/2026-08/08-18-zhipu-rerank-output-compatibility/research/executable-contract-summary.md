# Executable Contract Summary

This bounded summary exists so implementation/check agents receive the relevant contracts without
truncating the large Agent-pipeline and quality specifications.

## Structured Zhipu request

Source: `.trellis/spec/backend/agent-pipeline.md:456-579`.

- Every constrained Zhipu structured-output request uses
  `thinking={"type":"disabled"}` and `response_format={"type":"json_object"}`.
- Deep thinking is disabled so reasoning does not consume the bounded JSON completion budget.
- Invalid JSON/schema remains terminal `invalid_provider_output`; a content policy cannot downgrade
  it.
- Provider-contract tests inspect request bodies. Automated tests never make a live provider call.
- Provider/model identity must match the immutable claimed configuration before persistence.

## Topic-rerank invariants

Source: `.trellis/spec/backend/topic-selection.md:87-101,166-173,192-213`.

- Reranking runs after deterministic eligibility and may reorder only the capped eligible pool
  within hard priority groups.
- Output is a strict complete permutation with 1--3 allowlisted reason codes and one bounded
  explanation per candidate.
- Any parsing/provider/permutation/barrier failure returns the exact deterministic order.
- Audit stores only safe order, reason, fingerprint, usage, latency, outcome, and failure identity;
  prompts/provider bodies are forbidden.
- Provider-free eval measures fixture contract conformance, not live editorial quality.

## Provider error and privacy invariants

Sources: `.trellis/spec/backend/error-handling.md` and
`.trellis/spec/backend/logging-guidelines.md`.

- Validation diagnostics contain only bounded normalized `loc` segments and Pydantic `type` values.
  Never include validation messages, inputs, raw content, prompts, bodies, or exception strings.
- The approved provider JSON compatibility envelope is exactly one bounded top-level object: pure
  JSON, one exact `json` fence, or bounded non-JSON affixes around one uniquely balanced object.
  Arrays, multiple structures, ambiguous fences, non-standard constants, and malformed/over-limit
  content are rejected.
- Logs may record provider/model, prompt version/fingerprint, duration, token counts, safe request
  ID, and typed errors. They must not record prompt/response content, raw provider payloads, source
  text, URLs, object paths, or secrets.
- Schema failures are non-transient and are not blindly retried.

## Required quality gates

Source: `.trellis/spec/backend/quality-guidelines.md:13-23,99-104,235-243,319-325,347-368,911-920`.

- Preserve domain/application independence from FastAPI, SQLAlchemy, and provider SDKs.
- Use local fakes or recorded provider contract fixtures without secrets.
- Run focused tests first, then the final backend gate (`make backend-check`).
- Run deterministic API contract drift when a provider-facing implementation changes; no public
  schema drift is expected here.
- `docker compose config --quiet`, `git diff --check`, and credential/raw-content scans must pass.
- Live checks are explicit opt-in operations, never part of automated tests, and must be bounded to
  the user's authorized call count.
