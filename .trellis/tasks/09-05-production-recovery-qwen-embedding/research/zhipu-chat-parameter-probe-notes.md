# Fixed-request Zhipu chat parameter probe

## Why this additional diagnostic exists

The first reviewed live no-send canary returned embedding HTTP 200 and six brand hits, then
generation HTTP 400 (`provider_request_rejected`). Its actual prompt was 24,238 characters,
below the configured local 40,000-character limit. No audit was called; independent before/after
observations found no durable production effects. This new probe does not rerun that news input.

It submits only the fixed nonprivate instruction `Return exactly this JSON object: {"ok":true}`
using the deployed `_ZhipuStructuredCopyClient`. Model `glm-5.2`, disabled thinking,
`response_format=json_object`, temperature 0 and max_tokens 2048 are unchanged. Attempts are
diagnostically capped at one. No database, embedding, image, package or sending client is created.
The constructor itself is exercised in the default zero-call preflight.

## Identity and execution

Main must independently bind the exact content-worker container ID, immutable image digest,
OCI revision/release markers and protected environment before execution. The script checks all
253 loaded application Python files against the same exact `5c560da` source SHA-256 as the
earlier canary. The new configuration fingerprint is intentionally chat-only and is not the
earlier full-copy canary fingerprint. It excludes secrets; protected environment identity remains
an operator responsibility. No endpoint/model/account override is supported.

Stream the reviewed script to the verified consumer's `python -B -` stdin. Exact dry-run argv:

```bash
python -B - --expected-release 5c560da71bcbb61b765d3fe82c742cf2d5e676e1
```

After independent review and a successful zero-call result, main may make the single separately
reviewed fixed-request call by adding:

```text
--live-one-call --max-http-calls 1
--expected-config-sha256 <exact config_sha256 from this probe's dry run>
```

The physical transport requires that exact URL and payload; it rejects changed messages,
parameters or endpoints and any second request. Redirects, proxies and transport retries are
disabled. A 60-second total deadline and the production request timeouts apply. Unknown outcomes
consume the call and never authorize an automatic repeat.

## Safe response observation

The existing deployed bounded gzip/raw response reader handles all statuses, capped at 32,768
bytes. A non-2xx body is read only in memory before the ordinary copy client discards it. Only
`error.code` from the frozen official business-code allowlist is retained. Unknown codes, malformed
JSON, duplicate JSON fields and wrong types map to `other_code`; message, request ID, other fields
and raw body are never emitted. Success content is never printed: only a parsed object with exactly
one key `ok` and literal boolean `true` yields `strict_ok=true`. Logs are suppressed.

The main session verified the allowlist on 2026-09-05 against
[Zhipu's official error-code reference](https://docs.bigmodel.cn/cn/api/api-code). Do not infer
that GLM-5.3 migration constraints also apply to GLM-5.2. A 121x code can narrow a parameter/model
problem; 1261 indicates upstream prompt-length handling and 1301 content handling. Other returned
codes may identify access, quota or temporary service problems; preserve the code without guessing.

`fixed_request_passed` proves only that this one fixed request was accepted by the same configured
model/parameters. It does not prove news generation, content-specific causation, image delivery,
or restored production. Failure of the fixed request does not by itself identify the offending
parameter. This probe authorizes no configuration change or repeated paid calls.

## Validation

```bash
PYTHONPATH=/tmp/edu-ai-recovery-release.w7Btpe/backend conda run --name edu-ai \
  pytest .trellis/tasks/09-05-production-recovery-qwen-embedding/research/test_zhipu_chat_parameter_probe.py \
  -q -o asyncio_mode=auto
MYPYPATH=/tmp/edu-ai-recovery-release.w7Btpe/backend conda run --name edu-ai \
  mypy --strict --follow-imports=silent \
  .trellis/tasks/09-05-production-recovery-qwen-embedding/research/zhipu-chat-parameter-probe.py
```

Implementer validation: 51 provider-free cases pass against exact deployed-source imports;
scoped Ruff formatting/lint and strict mypy pass. No product/configuration edits, provider calls,
SSH, production actions or commits were performed by this implementer. Independent review and
actual production results remain owned by main.
