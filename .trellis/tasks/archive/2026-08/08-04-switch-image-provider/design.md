# Design: OpenAI-Compatible Comfly Image Provider

## 1. Design intent

Switch the active image-generation route from the exhausted ToAPIs-specific protocol to the
OpenAI-compatible gateway at `https://ai.comfly.org`, while preserving the existing durable image
port, private storage rules, request-fingerprint identity, output validation, fake provider, and
manual-use-only material-package boundary.

The provider adapter owns all HTTP and response-shape interpretation. Application services continue
to depend only on `ImageGenerator` and `ImageGenerationResult`; no Comfly or OpenAI response type
crosses the infrastructure boundary.

## 2. Data flow

```text
accepted copy draft
        |
        v
API reserves provider/model-aware fingerprint in PostgreSQL
        |
        v
content-worker claims lease
        |
        v
OpenAI-compatible adapter -> POST /v1/images/generations
        |                         |
        |                         +--> direct data[].url or data[].b64_json
        |                         +--> bounded task response -> GET /v1/images/tasks/{task_id}
        v
validate bytes/media type/dimensions -> immutable private MinIO object
        |
        v
versioned material package for manual review/copy/download
```

The worker remains the only process that crosses the image-provider boundary. API handlers only
reserve durable work. Database transactions never hold an outbound HTTP request.

## 3. Provider adapter contract

### 3.1 Configuration

Add an active `comfly` provider mode while retaining `disabled`, `fake`, and `toapis` for explicit
rollback/offline use:

- `IMAGE_PROVIDER_MODE=comfly`
- `COMFLY_BASE_URL=https://ai.comfly.org`
- `COMFLY_API_KEY` from the local ignored `.env` or deployment secret store
- `IMAGE_MODEL=gpt-image-2`
- Existing image attempt, timeout, provider-window, download-bound, prompt-version, pipeline-version,
  and reference-asset settings remain authoritative.

Validate the Comfly URL as HTTPS with a hostname, no userinfo, query, or fragment. The active local
value is exact `https://ai.comfly.org`; do not accept the documentation origin as a provider URL.
Validate the key as non-blank and free of line breaks. Never include its value in exception text,
structured logs, tests, or task artifacts.

### 3.2 Request

`OpenAICompatibleImageGenerator` sends:

```json
{
  "model": "gpt-image-2",
  "prompt": "<validated bounded prompt>",
  "size": "1:1",
  "aspect_ratio": "1:1",
  "image": ["data:image/png;base64,<bounded reference bytes>"]
}
```

The `image` field is omitted when no reference is supplied. The adapter checks the encoded request
bound before sending. It does not send a private MinIO URL, provider upload URL, or unbounded raw
reference. If the provider rejects the model/reference field, the attempt becomes a typed terminal
diagnostic rather than silently dropping the approved reference.

### 3.3 Response normalization

Accept exactly one image from one of these bounded shapes:

- synchronous `data[0].url`: validate HTTPS, host policy, content type, byte bound, and 1024x1024
  dimensions before returning the port result;
- synchronous `data[0].b64_json`: strict base64 decode within the byte bound, then apply the same
  raster validation;
- an opaque safe task ID with a queued/in-progress status: poll the documented
  `/v1/images/tasks/{task_id}` route within the existing provider window, then apply the same
  result extraction once complete.

Provider IDs are accepted only when they match the existing safe identifier grammar. URLs, raw
response bodies, and arbitrary nested output are never persisted. A result from another provider or
an unallowlisted host fails closed.

### 3.4 Error matrix

| Condition | Result |
|---|---|
| 401/403 or explicit invalid-token response | non-retryable provider authentication error |
| quota/balance exhaustion | non-retryable `image_provider_quota_exhausted`, body redacted |
| 429 or bounded transient 5xx | retry with bounded backoff/`Retry-After` |
| timeout/network failure | retry within provider window, then typed timeout/unavailable |
| invalid JSON, missing data, multiple/unsafe output | non-retryable provider rejection/review-required |
| URL is non-HTTPS, wrong host, redirects, or wrong media/dimensions | output validation failure |
| reference data exceeds request bound or is unsupported | non-retryable reference/output validation failure |

The adapter must not retry authentication, quota, malformed output, unsafe output, or unsupported
reference failures.

## 4. Lifecycle and durable identity

- `api_main.py` and `content_worker_main.py` create an owned `httpx.AsyncClient` for `comfly`.
- `create_image_generator()` selects the adapter by mode; fake mode remains network-free.
- The persisted provider label is `comfly`. Provider/model/prompt/pipeline/reference identity remains
  part of the existing fingerprint, so a provider switch cannot reuse a ToAPIs artifact silently.
- Existing failed `toapis` image rows remain immutable historical failures. The switch does not
  rewrite or re-label them, and it does not add a direct database repair. A new accepted draft/run
  creates a new Comfly fingerprint. Requeueing an old accepted draft across the existing
  `run_id,draft_version_id` uniqueness boundary is a separate controlled feature.

## 5. Verification and rollout

1. Run unit/contract tests with `httpx.MockTransport` for auth, payload, base64, URL, task polling,
   retries, output validation, and redaction.
2. Put the supplied key only in local `.env`; never stage it.
3. Rebuild `content-worker` and verify startup logs contain only provider mode/model metadata.
4. With the key, call `/v1/models` and assert `gpt-image-2` is available. Do not print the model
   response body.
5. Run one bounded image smoke using the approved reference asset. Save it only to a local ignored
   output path or through the existing protected package path; do not present a failed/fake result
   as live success.
6. Run the full quality gate and inspect `git diff --check` plus staged-path secret checks.

Rollback is configuration-only: set `IMAGE_PROVIDER_MODE=toapis` with the old secret/base URL, or
`fake` for offline operation. No migration is required.

## 6. Risks and deferred items

- The public response schema is incomplete. Live capability and one bounded generation are required
  before the provider is considered ready.
- The provider may return a CDN URL whose hostname is not the API origin. The first implementation
  fails closed unless the URL host is explicitly configured/validated; it must not broaden downloads
  to arbitrary hosts.
- Existing failed ToAPIs rows cannot be safely converted in place because image artifacts enforce
  one row per run/draft. A dedicated requeue/versioning task is needed if old drafts must be retried.
