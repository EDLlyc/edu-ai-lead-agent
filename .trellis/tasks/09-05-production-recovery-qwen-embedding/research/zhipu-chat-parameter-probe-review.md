# Independent fixed-request chat probe review

## Decision and bound identity

GO for the default zero-call preflight, followed only on success and after main's independent
container/image/source/configuration gates by exactly one fixed nonprivate chat request.

Reviewed script SHA-256:
`a31b91d47ca089cbbb123cf930f946a7be98e7746fee37cae8781bc8fd91d291`.
Application source remains the exact deployed
`5c560da71bcbb61b765d3fe82c742cf2d5e676e1` and its 253-file source fingerprint.

This is a separate diagnostic, not a repeat of the already consumed original live canary.
That invocation made one successful embedding request and one rejected generation request, with
no audit or observed durable effects. Do not rerun its private/news inputs.

## Verified safety and compatibility

- Default preflight constructs the deployed structured-copy client but sends zero requests.
  Live execution requires a validated one-call flag/cap and this probe's exact non-secret
  configuration fingerprint. The original canary's different fingerprint is not interchangeable.
- The physical transport binds the entire fixed messages/parameter payload, current configured
  endpoint and `glm-5.2` model: disabled thinking, JSON-object output, temperature zero and
  2,048 output tokens. It charges before forwarding, rejects second attempts and accepts no
  alternate input, credential, endpoint, model or parameter CLI flags.
- Configuration explicitly rejects non-HTTPS, absent host, userinfo, query and fragment before
  client construction. Inner transport retries, ambient proxies and redirects are disabled.
  Production per-request timeouts remain bounded by an additional 60-second whole-probe deadline.
- The exact deployed raw/gzip reader caps both encoded and decoded responses at 32,768 bytes,
  including non-success responses. Streaming responses close on success and every failure.
  Only the frozen allowlisted `error.code` is projected; unknown/invalid codes become a fixed
  unknown category. Error messages, request IDs, arbitrary field names, bodies and content are
  never printed. Duplicate keys, booleans masquerading as integer codes and malformed JSON are
  rejected. The allowlist was checked against the official
  [Zhipu error-code reference](https://docs.bigmodel.cn/cn/api/api-code).
- Success is only the strict parsed object containing `ok: true`, represented in output by a
  boolean. Standard/structured logs are suppressed; sentinel privacy tests cover both success
  and error paths. No database, embedding, image, package or sending client is constructed.
- Main must independently bind runtime/image/environment/release identities and record the
  actual invocation. A supplied revision or secret-free fingerprint alone is not that proof.
  Timeout/unknown outcomes consume the one-call budget and do not authorize automatic repetition.

## Findings addressed during review

- Requested and verified an explicit typed secure-endpoint preflight gate and its negative tests.
  The deployed client constructor already rejected those unsafe URL forms; this makes the new
  diagnostic boundary explicit rather than relying on its later constructor failure.
- Requested and verified real streamed-body tests at the newly added transport-reader boundary:
  missing/oversized Content-Length, incremental overrun, valid gzip, expansion and truncated gzip,
  with closure and no raw-output projection in every case.
- No remaining code-level safety blocker was found. The reviewer made no production changes,
  provider requests, SSH connections, commits or deployments.

## Verification and interpretation

Independent exact-release tests: **51 passed** with network disabled. Scoped Ruff lint/format and
strict mypy passed. No database integration test is required for this probe because it has no
database path; the previous canary's eight real-database tests remain separate evidence.

A fixed-request pass proves only this one configured request was accepted. It does not prove
news generation or the cause of the earlier content-bearing rejection. A numeric parameter error
narrows its class but does not identify which field failed. Neither outcome proves restored
production delivery or authorizes a model/configuration change.
