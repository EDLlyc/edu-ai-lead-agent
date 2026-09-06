# Independent opt-in error-observation review

## Decision

GO for a fresh zero-call preflight with `--capture-provider-error-codes`, then exactly one
separately authorized instrumented live invocation after main's renewed runtime/configuration,
copy-version and protected-state checks. This is not an automatic retry of the previous script.

Reviewed revised script SHA-256:
`344f404cc46a3a71fdbadd2bd855ed01e1ccfad6c0bb45f1f089946c5582174c`.
Earlier review hashes and result artifacts remain historical and unchanged.

## Diff-focused findings

The reviewed change adds the default-false capture flag, explicit v2 observation schema/mode,
an allowlisted per-stage business-code map, a small pure JSON-code projector, and bounded
non-2xx body observation inside the existing capped transport. CLI handling only adds the flag.

- The source/configuration gates, selector and evidence/brand loaders, read-only database engine,
  model factories, embedding/query input, generation/audit payloads, deterministic rules and
  no-repair/no-send paths remain unchanged. The request-byte parity regression verifies that
  adding observation does not change the content-bearing requests.
- Default invocations still permit zero calls, retain the original mode/schema and do not read
  non-success bodies. Success response handling is also unchanged. The additive false/empty
  observation report fields disclose no additional private data.
- The new path uses the already reviewed deployed raw/gzip response reader with a 32,768-byte
  bound. It closes the response on success or failure, records only an allowlisted numeric
  business code, and returns the original status with empty content and no copied headers.
  Unknown codes, duplicate keys, non-finite JSON, boolean/nested codes and malformed JSON become
  a fixed unknown category; provider messages, request IDs, private fields and body text never
  enter the report.
- A parity regression binds the duplicated standalone-stdin allowlist to the separately reviewed
  fixed-request probe. That allowlist was checked against the
  [official Zhipu error-code reference](https://docs.bigmodel.cn/cn/api/api-code).
- Physical budget checks still precede forwarding: at most one embedding, one generation and one
  audit request, three total. Failed/unknown outcomes consume the budget. Observation cannot
  grant a retry; flagged-response cap tests retain the original one-per-stage restriction.
- No additional database/session authority, production write, package or sending path exists.
  The earlier eight real PostgreSQL safety tests remain applicable; no redundant database rerun
  was needed for this response-observation-only change.

## Findings fixed and verification

Review caught one new-test Ruff `RUF005` list-concatenation issue; the implementer replaced it
with list unpacking before handoff. No runtime safety blocker was found.

- Independent exact-deployed-source provider-free suite: **87 passed**, network disabled.
- Scoped Ruff lint and formatting: pass.
- Strict mypy for the diagnostic: pass.
- New cases cover unchanged request bytes/default behavior, explicit observation identity,
  official-code parity and redaction, real raw/chunked/gzip bounds, response closure and caps.

The reviewer made no provider request, SSH connection, production write, restart, deployment or
commit. Main owns recording the single actual invocation and independent before/after evidence.

## Interpretation

The successful fixed nonprivate control establishes only that the configured model/parameters
can accept that control. It does not establish the cause of the original news-bearing HTTP 400.
This instrumented invocation may identify a business-error class; do not infer an exact offending
parameter without evidence. A content-safety refusal authorizes neither content-filter evasion
nor rewriting private inputs to bypass it. Preserve the code and stop if this invocation fails.
No diagnostic outcome substitutes for fresh formal terminal delivery and duplicate verification.
