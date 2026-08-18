# Zhipu Topic-Rerank Output Compatibility

## Goal

Make the optional Zhipu `glm-5.2` topic-rerank call reliably produce the project's strict,
bounded permutation contract while retaining deterministic fallback, historical replay identity,
and the rule that no provider prompt or response body is persisted or logged.

The user value is a model-assisted priority ordering that can actually be applied after the
deterministic eligibility threshold, instead of silently falling back because a provider-shaped
response differs from the adapter's self-confirming mock.

## Background and Confirmed Facts

- One explicitly authorized live call on 2026-08-18 used three synthetic candidates,
  `glm-5.2`, and `max_attempts=1`. The HTTP boundary returned, but the adapter classified the
  result as `invalid_provider_output`; deterministic order was preserved. No production database,
  service, configuration, or delivery path was touched.
- The current adapter sends `response_format={"type":"json_object"}` but its prompt describes
  field names only in prose. It does not include the exact JSON shape or the seven permitted
  `reason_codes` values. All completion-envelope, JSON-syntax, schema, and UUID failures collapse
  to `topic_rerank_schema_invalid` and lose post-response usage/latency.
- Zhipu's official chat-completion contract supports `json_object` output and recommends defining
  the expected JSON structure in the messages. Its structured-output guide performs schema
  validation client-side; it does not document a server-enforced `json_schema` response mode.
- GLM-5.2 supports `thinking={"type":"disabled"}` and deterministic sampling through
  `do_sample=false`. The existing structured-copy adapter already disables thinking for bounded
  JSON transformations.
- The repository already owns a bounded provider-JSON envelope scanner that accepts only one
  top-level object (pure JSON, one exact `json` fence, or bounded prose around one unique object)
  and still applies strict Pydantic validation afterward.
- `topic-rerank-v1` is already stored in immutable run snapshots. Changing its prompt or wire
  behavior in place would reinterpret historical replays.

## Requirements

### R1. Versioned provider request contract

- Introduce a new default rerank policy identity for the compatible GLM JSON contract; retain
  literal `topic-rerank-v1` as a supported historical policy.
- New-policy requests must send the officially supported `json_object` mode, disable thinking,
  disable sampling, retain the configured zero temperature and bounded output limit, and remain a
  single provider operation governed by the existing retry configuration.
- The new prompt must include the exact object/item structure, all allowlisted reason codes,
  exact candidate-count/permutation requirements, consecutive integer ordinals, the priority-group
  barrier, and an explicit no-Markdown/no-prose instruction.
- Literal v1 replays must retain their legacy prompt, payload, and exact-object parsing behavior.
  Unknown policy identities must fail before a provider request rather than silently borrowing
  either contract.

### R2. Narrow response compatibility without semantic relaxation

- Share the existing bounded one-object envelope scanner with topic reranking instead of copying
  or broadening it.
- The new policy may accept only the scanner's existing safe envelopes. It must still reject array
  roots, multiple objects/values, ambiguous fences, over-limit affixes, malformed JSON,
  non-standard constants, extra fields, unknown reason codes, string ordinals, blank/oversized
  explanations, invalid UUIDs, incomplete/duplicate permutations, and priority-group crossings.
- The model may only reorder already eligible candidates. It must never create candidates, scores,
  facts, evidence, or a threshold/veto override.

### R3. Safe diagnostics and fallback fidelity

- Distinguish at least completion-envelope, JSON-envelope, and strict output-schema failures using
  bounded internal issue codes and normalized `loc`/`type` diagnostics.
- Diagnostics may contain field paths, stable validation types, counts, fingerprints, token usage,
  and latency only. They must never contain raw provider content, provider exception text, prompts,
  candidate text, credentials, or response bodies.
- When a completion envelope is valid but its content is invalid, preserve the safe prompt
  fingerprint, usage counters, and latency in the deterministic fallback audit instead of replacing
  them with zeros.
- The public/durable failure category remains `invalid_provider_output`, and every invalid result
  must preserve the exact deterministic base order with no second model judge or schema-repair call.

### R4. One controlled post-fix validation

- After all local gates pass, make at most one non-retried (`max_attempts=1`) live Zhipu call using
  synthetic, non-business candidates and no database session.
- Print and record only the typed outcome, provider/model identity, safe order/fingerprints,
  usage/latency, and bounded diagnostic codes. Do not print or retain the prompt, completion,
  Authorization header, or response body.
- A valid result must be a complete permutation accepted by the same production adapter and domain
  validator. If the one call still fails, stop without another paid call and report the safe failure
  stage; do not claim compatibility success.

## Acceptance Criteria

- [x] AC1: New default snapshots use the new policy identity, while literal v1 metadata round-trips
  and selects the legacy prompt/payload/parser byte-for-byte at the behavioral contract level.
- [x] AC2: A provider-contract test proves the new payload contains `json_object`, disabled
  thinking, disabled sampling, zero temperature, and the configured output bound; the prompt names
  the exact schema and all seven allowlisted reason codes without exposing candidate data in the
  system message.
- [x] AC3: Pure JSON and the already-approved bounded compatibility envelopes yield the same strict
  model result; extra fields, unknown enums, string ordinals, arrays, multiple structures,
  malformed/oversized envelopes, bad UUIDs, invalid permutations, and group crossings fail closed.
- [x] AC4: Safe diagnostics distinguish completion, JSON-envelope, and schema failures and prove
  that secrets, candidate text, prompts, raw completions, and exception messages are absent.
- [x] AC5: Post-response invalid output persists the exact deterministic order plus the real safe
  prompt fingerprint, usage, and latency; public/API failure remains `invalid_provider_output`.
- [x] AC6: Focused unit/contract tests, strict typing, Ruff, the provider-free rerank eval drift
  check, the full backend gate, API contract drift, Compose render, diff hygiene, and secret scan
  pass without a migration or public schema change.
- [x] AC7: Exactly one post-fix synthetic live call is attempted with `max_attempts=1`. It either
  produces an accepted complete permutation or stops with a bounded safe diagnostic and no retry.
- [x] AC8: No production service, database, feature flag, scheduler, provider job, WeCom job,
  deployment, commit, or push is changed by the live validation.

## Out of Scope

- Deploying the fix or enabling LLM reranking on a server.
- Replaying or modifying an existing business run, news selection, content package, or delivery.
- Adding a database migration or changing the public API/OpenAPI response shape.
- Relaxing eligibility thresholds, vetoes, priority barriers, permutation completeness, or output
  field/enum validation.
- Persisting raw provider output or adding an unbounded schema-repair/model retry.
- General changes to copy generation, OCR, image generation, Agent Workbench, or MCP behavior.

## Technical Notes

- Preferred reuse boundary: extract the existing provider-JSON envelope scanner to a shared
  infrastructure helper and import it from both copy generation and topic reranking without
  changing copy behavior.
- The compatibility policy must be selected by the immutable request policy version, not by the
  currently configured model name alone.
- The existing deterministic selector and `TopicRerankModelResult`/domain permutation validator
  remain authoritative after parsing.
