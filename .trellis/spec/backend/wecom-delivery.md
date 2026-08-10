# Enterprise WeChat Sales Delivery

## Contract status

This is the implemented contract for the Enterprise WeChat delivery boundary. It supports the
existing self-built-application route for one configured internal sales user and the official group
webhook route for one configured group. Eligibility is either `completed + approved` in
review-required mode or a validated `awaiting_manual_use`/`completed` package in direct mode. It
does not publish to a personal or enterprise WeChat Moments feed, expose a public recipient API, or
regenerate content.

## 1. Scope / Trigger

Apply this contract when changing any of the following:

- `wecom_delivery_jobs` or `wecom_delivery_attempts` schema and migrations;
- the delivery API, dispatcher, Enterprise WeChat adapter, or MinIO image read path;
- `WECOM_*` settings, Compose wiring, retry behavior, or sensitive-field logging.

The side-effect boundary starts only after the package is eligible for delivery. The API writes a
durable job; only `wecom_dispatcher_main.py` performs provider calls.

## 2. Signatures

### API

```text
GET  /api/v1/wecom/recipients
POST /api/v1/material-packages/{package_id}/wecom-deliveries
GET  /api/v1/wecom-deliveries/{delivery_id}
POST /api/v1/wecom-deliveries/{delivery_id}/retry
```

The create request is:

```json
{
  "recipient_id": "default",
  "mode": "formal",
  "include_copy": true,
  "include_image": true
}
```

The create endpoint returns `202` and a durable `id`/`Location`. The response projection may
contain status, child message states, attempt count, timestamps, and a safe error code. It must
not contain a raw Enterprise WeChat `userid`, `access_token`, `media_id`, provider response body,
or MinIO bucket/object key.

### Database

`wecom_delivery_jobs` stores:

- package ID, configured projection recipient ID, mode, package version, and content fingerprint;
- unique request fingerprint, include-copy/image flags, overall status, and text/image states;
- attempt count, next-attempt time, lease owner/token/expiry, heartbeat, safe last error, and times.

`wecom_delivery_attempts` stores message kind, attempt number, stable child request fingerprint,
safe provider request ID/error code, result state, bounded latency, and creation time. It never
stores raw bodies, tokens, temporary media IDs, or image URLs.

### Application and provider ports

```python
enqueue_wecom_delivery(...) -> WeComDeliveryJobModel
retry_wecom_delivery(...) -> WeComDeliveryJobModel
build_wecom_text(package, mode, max_bytes) -> str
WeComDeliveryExecutor.execute_next(worker_id) -> bool
WeComApiClient.upload_image(bytes, media_type, filename) -> UploadedMedia
WeComApiClient.send_text(recipient_id, agent_id, content, request_fingerprint) -> SendResult
WeComApiClient.send_image(recipient_id, agent_id, media_id, request_fingerprint) -> SendResult
WeComDeliveryClient.send_image_bytes(
    recipient_id, agent_id, image_bytes, media_type, filename, request_fingerprint
) -> SendResult
```

## 3. Contracts

### Environment

| Key | Contract |
|---|---|
| `WECOM_ENABLED` | `false` by default; enables configuration validation and delivery API use |
| `WECOM_API_BASE_URL` | Exactly `https://qyapi.weixin.qq.com` |
| `WECOM_DELIVERY_PROVIDER` | `self_built_app` (default) or `group_webhook` |
| `WECOM_CORP_ID` | Server-side non-blank identifier when enabled |
| `WECOM_AGENT_ID` | Positive application ID when enabled |
| `WECOM_CORP_SECRET` | Server-side secret; never log or persist |
| `WECOM_GROUP_WEBHOOK_KEY` | Secret webhook key required only for `group_webhook` |
| `WECOM_DEFAULT_RECIPIENT_ID` | Raw configured userid; server-side only, never an API field |
| `WECOM_DEFAULT_RECIPIENT_NAME` | Internal display label, default `销售` |
| `WECOM_AUTO_DELIVERY_ENABLED` | Requires `WECOM_ENABLED`; default `false` |
| `WECOM_REQUIRE_REVIEW_BEFORE_SEND` | Defaults to `true`; when `false`, direct mode accepts validated packages without a manual review decision |
| `WECOM_MAX_ATTEMPTS` | Bounded from 1 to 10 |
| `WECOM_REQUEST_TIMEOUT_SECONDS` | Bounded request timeout; send timeout is an unknown outcome |

The `wecom` Compose profile is opt-in. With `WECOM_ENABLED=false`, the dispatcher logs one safe
disabled event and does not create a database engine or an HTTP client. Group Markdown is bounded
at 4096 UTF-8 bytes and group image bytes at 2 MiB. The group adapter uses the official
`/cgi-bin/webhook/send?key=KEY` endpoint without redirects and enforces the documented 20 messages
per minute process-local window.

### State and side effects

The normal state path is `queued -> running -> delivered`. A text-success/image-failure path is
`partial`; a provider send timeout is `delivery_unknown`. A retryable rate-limit or temporary
failure queues the same job with bounded backoff. Explicit operator retry may reopen `failed`,
`partial`, or `delivery_unknown`, but never `delivered`.

Text is sent before image. A successful child state is persisted before the next child is called;
lease recovery therefore skips a delivered child. Image delivery reads the private MinIO object,
checks size, SHA-256, and PNG/JPEG signature. The self-built-app adapter uploads temporary media;
the group adapter sends a bounded Base64/MD5 payload. Temporary media IDs are discarded after the
self-built-app call.

The text payload contains the complete copywriting only; the material-package topic title is kept
for internal/package display and is not automatically prefixed to the Enterprise WeChat message.
Test mode adds a visible test marker. The self-built-app message types enable the official
duplicate-check fields; the group webhook payloads use only their documented Markdown and
Base64/MD5 fields. The stable application fingerprint is persisted for job/attempt identity; the
provider request never receives secrets or an invented idempotency field.

In review-required mode, enqueueing and automatic reconciliation require `completed + approved`.
In direct mode, they accept `awaiting_manual_use` or `completed` packages unless explicitly
rejected. Direct mode still requires copy validation to pass, copy audit to be accepted, image
validation to pass, and any configured image audit to be accepted before a job is created.

Automatic reconciliation is a candidate scan, not a broad package-status retry loop. It excludes
any package that already has a durable delivery job, restricts the scan to the current business
date, applies the persisted direct-mode quality and immutable-image predicates before the enqueue
attempt, and retains the enqueue guard as the final race-safe authority. The current business date
is computed from the dispatcher clock in `Settings.business_timezone`; the candidate query joins
`material_packages.run_id` to the typed `copy_generation_runs.business_date` column. It must not
use package creation time or a mutable topic snapshot to decide whether a package is today's
package. PostgreSQL candidate predicates compare JSONB fields by literal value (for example, JSON
boolean containment) so malformed legacy snapshot values are excluded rather than raising a cast
error. A typed conflict caused by a state race is logged once per package and bounded readiness
state in the dispatcher process; a later readiness change may be evaluated again.

### Security boundary

The adapters use HTTPS, the official host allowlist, bounded response parsing, no redirects, and
typed provider errors. Self-built-app access tokens are cached only in the dispatcher process. Raw
userid values are read only from settings and passed to the self-built-app adapter; the API and
database use `default`. Group webhook keys are bearer credentials and never appear in logs, errors,
API responses, or durable delivery rows.

## 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| WeCom disabled or fixed recipient missing | API returns stable conflict; no job is created |
| Unsupported recipient ID or mode | Stable conflict/validation result; no provider call |
| Package missing or not eligible for the configured delivery policy | Not found/conflict; no job is created |
| Eligible package belongs to another business date | Candidate scan excludes it; no job is created or sent automatically |
| Review-required package is not approved, or direct package is explicitly rejected | Conflict; no job is created |
| Direct package copy validation/audit or configured image quality gate fails | Conflict; no job is created |
| Image requested but artifact is not succeeded or metadata is invalid | Conflict; no provider call |
| Duplicate package/version/recipient/mode request | Return the existing job ID; do not add a row |
| Token invalid response | Invalidate process-local cache and refresh once; a second invalid result is terminal |
| HTTP 429 or bounded temporary provider error | Retry with bounded backoff until max attempts |
| Send timeout or ambiguous transport result | Mark child and job `unknown`/`delivery_unknown`; never auto-resend |
| Invalid recipient, invalid credentials, unsupported media, or malformed provider response | Terminal safe error; no raw provider text in API/logs |
| Text succeeds and image fails | Persist text success and mark job `partial` or queued for an eligible retry |
| Dispatcher lease expires | Reclaim with `FOR UPDATE SKIP LOCKED`; skip already delivered children |

## 5. Good / Base / Bad Cases

- Good: an approved completed package in review-required mode, or a validated
  `awaiting_manual_use` package in direct mode, produces one stable formal job; the dispatcher
  sends text then image, both child attempts are durable, and the job becomes `delivered`.
- Good: after a deployment, a valid package from yesterday remains queryable for audit but is not
  selected by today's automatic reconciliation.
- Base: WeCom remains disabled in local Compose; API exposes no recipient and dispatcher remains
  idle without needing credentials.
- Good: a text-success/image-timeout result is visible as `partial` or `delivery_unknown`, and an
  operator can explicitly retry only the unresolved child.
- Bad: the API calls Enterprise WeChat or MinIO while creating the job, stores raw `userid` in a
  job row, retries a timeout automatically, or bypasses direct-mode quality gates.
- Bad: an image is uploaded without checking the immutable MinIO descriptor, or a provider body,
  token, media ID, secret, or signed URL is written to logs or response JSON.

## 6. Tests Required

- Contract tests with `httpx.MockTransport` assert official token caching, one-time token refresh,
  bounded multipart upload, duplicate-check text/image payloads, response-code classification,
  malformed/oversized response rejection, and no sensitive value in representations/errors.
- Service tests assert text composition, UTF-8 byte limits, strict approval, direct-mode package
  eligibility and quality vetoes, image descriptor checksum/signature validation, and safe default
  settings.
- PostgreSQL integration tests upgrade a clean database to `20260807_0019`, assert both delivery
  tables and constraints, and compare `Base.metadata` without SQLite.
- Dispatcher/service tests must assert text-before-image ordering, persistence before the second
  child, partial failure, bounded retry, unknown timeout terminal state, lease heartbeat, and
  idempotent enqueue.
- Automatic-reconciliation tests assert the PostgreSQL candidate query's durable-job exclusion,
  current-business-date join, direct quality predicates, malformed/missing JSONB snapshots, and
  bounded race-skip logging. Include a timezone-boundary test with a fixed UTC clock.
- Compose checks run `docker compose config --quiet` and build the `wecom-dispatcher` image without
  credentials. A real provider send is opt-in and must never be part of the default test suite.
- `scripts/doctor.sh` and migration-head assertions must be updated whenever the Alembic head moves.

## 7. Wrong vs Correct

### Wrong

```python
await wecom_client.send_text(...)
await session.commit()
```

This performs an external side effect inside the API request/transaction and cannot safely recover
from a timeout or concurrent submission.

### Correct

```python
await enqueue_wecom_delivery(session=session, ...)
# The independent dispatcher later claims the durable job, calls the provider outside a DB
# transaction, and persists each child result under its lease.
```

The correct flow preserves the configured manual-review policy, idempotency, auditability, and the
distinction between a confirmed failure and an unknown provider outcome.

## Common Mistakes

### Persisted JSON metadata must be compared by value

JSONB values loaded from PostgreSQL are fresh Python objects. Validate required fields with value
comparisons such as `==`/`!=` or explicit field checks; identity checks such as `is`/`is not` can
reject valid persisted image metadata and incorrectly block delivery.

### Provider HTTP logs must not contain authenticated URLs

`httpx` and `httpcore` request logs can include the full token endpoint URL. Keep those loggers at
`WARNING` or higher and emit only the adapter's redacted structured events. Never log access-token
query strings, secrets, raw provider bodies, or signed object URLs.

### Enterprise WeChat targets must be real application-visible user IDs

`WECOM_DEFAULT_RECIPIENT_ID` is an internal `userid`, not a display name. The user must be in the
self-built application's address-book visibility scope. A provider recipient/configuration error
such as `60020` is terminal until the ID or visibility scope is corrected; it must not be treated
as a successful send or retried indefinitely.

### Automatic reconciliation must be date-scoped

The dispatcher polls frequently, so a status-only candidate query can rediscover every historical
package that has no delivery row. That is a duplicate-send risk after a migration or a fresh
dispatcher start. Derive today's date with `Settings.business_timezone` and filter through the
typed `CopyGenerationRunModel.business_date` relation before applying delivery quality predicates.

```python
business_date = clock().astimezone(ZoneInfo(settings.business_timezone)).date()
statement = (
    select(MaterialPackageModel)
    .join(CopyGenerationRunModel, CopyGenerationRunModel.id == MaterialPackageModel.run_id)
    .where(CopyGenerationRunModel.business_date == business_date)
)
```

Do not substitute `MaterialPackageModel.created_at` or an unvalidated JSON snapshot field: those
values describe storage history, not the business date assigned to the content run.

## 8. Group Webhook Provider

### 8.1 Scope / Trigger

Apply this contract when `WECOM_DELIVERY_PROVIDER=group_webhook` or when changing the group-webhook
adapter, its image preparation path, or its provider-specific settings.

### 8.2 Signatures

```text
WeComGroupWebhookClient.send_text(
    recipient_id: str,
    agent_id: int | None,
    content: str,
    request_fingerprint: str,
) -> SendResult

WeComGroupWebhookClient.send_image_bytes(
    recipient_id: str,
    agent_id: int | None,
    image_bytes: bytes,
    media_type: str,
    filename: str,
    request_fingerprint: str,
) -> SendResult

prepare_group_webhook_image(bytes, media_type, max_bytes=2*1024*1024)
    -> PreparedGroupImage(body, media_type)
```

### 8.3 Contracts

- Copy uses `{"msgtype":"markdown","markdown":{"content":CONTENT}}`.
- Image uses `{"msgtype":"image","image":{"base64":BASE64,"md5":MD5}}`; MD5 is calculated
  over prepared raw bytes before Base64 encoding.
- The logical API recipient remains `default`; no userid, AgentID, or CorpID is included in either
  webhook payload.
- JPG/PNG source bytes are verified against the immutable package descriptor. A source above 2 MiB
  is deterministically compressed/downscaled in memory; the original MinIO object is unchanged.
- The adapter enforces a process-local window of at most 20 actual message attempts per 60 seconds.
  429/temporary responses are bounded-retryable; timeout or ambiguous transport results are
  `delivery_unknown` and are not automatically resent.
- `WECOM_GROUP_WEBHOOK_KEY` is a SecretStr deployment value. It must not appear in settings reprs,
  logs, exceptions, API responses, job rows, or task artifacts.

### 8.4 Validation & Error Matrix

| Condition | Required result |
|---|---|
| Group provider enabled without a key | Settings validation fails before dispatcher startup |
| Markdown exceeds 4096 UTF-8 bytes | Stable invalid-input result; no provider request |
| Image is unsupported, malformed, over safe raster bounds, or cannot fit 2 MiB | Stable invalid-input result; no provider request |
| Provider returns non-zero webhook code | Safe provider rejection/rate-limit/temporary code; raw body omitted |
| Webhook send times out or transport outcome is ambiguous | `delivery_unknown`; no automatic resend |
| More than 20 messages are queued in one dispatcher process | Calls wait for the window instead of bursting |

### 8.5 Good / Base / Bad Cases

- Good: one Markdown message and one valid Base64/MD5 image message are sent in order to the fixed
  webhook endpoint, with no self-built-app fields.
- Base: blank/default configuration leaves WeCom disabled and does not require a group key.
- Bad: placing the webhook key in a URL log, using `upload_media` for an image, silently truncating
  Markdown, or retrying a timeout automatically.

### 8.6 Tests Required

- Contract tests assert fixed host/path, key query construction without representation leakage,
  Markdown byte limits, image Base64/MD5, response classification, and timeout non-retry.
- Image preparation tests assert immutable source bytes, safe raster bounds, deterministic fitting,
  and JPG/PNG signatures.
- Dispatcher/service tests assert provider selection, logical group recipient, text-before-image
  ordering, bounded rate window, and compatibility with the self-built adapter.

### 8.7 Wrong vs Correct

#### Wrong

```python
await client.send_text(..., access_token=webhook_key)
await client.send_image(..., media_id=uploaded_media_id)
```

The group webhook has no access-token message API and its image contract is inline Base64/MD5.

#### Correct

```python
await group_client.send_text("default", None, markdown, text_fingerprint)
await group_client.send_image_bytes("default", None, body, "image/png", filename, image_fingerprint)
```
