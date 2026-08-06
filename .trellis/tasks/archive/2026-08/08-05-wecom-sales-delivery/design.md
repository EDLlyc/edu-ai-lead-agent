# Technical Design: Enterprise WeChat Sales Delivery

## Boundary

The existing production path remains unchanged through `material_packages`. A new side-effect boundary starts only after `MaterialPackageModel.status=completed` and `review_status=approved`:

```text
approved material package
  -> API writes wecom_delivery_jobs
  -> wecom-dispatcher claims a job
  -> provider-neutral application port
  -> Enterprise WeChat HTTP adapter
  -> text message, then image message
```

The API never calls Enterprise WeChat, models, or MinIO during task creation. The dispatcher owns all external calls and uses the existing private `MinioImageStore` to read the already validated image.

## Components

- `app/application/ports/wecom.py`: provider-neutral token, media upload and message-send contracts plus bounded result types.
- `app/infrastructure/wecom/client.py`: HTTPS adapter for the three official APIs. It validates JSON shapes, caches the token in memory, redacts sensitive values, and maps provider outcomes to typed application errors.
- `app/application/services/wecom_delivery.py`: validates package prerequisites, computes stable idempotency fingerprints, enqueues jobs, claims leases, composes the text payload, reads the private image, persists message attempts and transitions job state.
- `app/api/v1/routes/wecom_deliveries.py`: recipient projection, enqueue/status/retry HTTP contracts only.
- `app/wecom_dispatcher_main.py`: independent polling process with optional auto-dispatch reconciliation and bounded concurrency.

## Configuration

The first version deliberately has one configured internal recipient rather than a public recipient-management API:

```text
WECOM_ENABLED=false
WECOM_CORP_ID=
WECOM_AGENT_ID=
WECOM_CORP_SECRET=
WECOM_DEFAULT_RECIPIENT_ID=
WECOM_DEFAULT_RECIPIENT_NAME=销售
WECOM_AUTO_DELIVERY_ENABLED=false
WECOM_REQUIRE_REVIEW_BEFORE_SEND=true
WECOM_POLL_SECONDS=2
WECOM_WORKER_CONCURRENCY=1
WECOM_LEASE_SECONDS=120
WECOM_HEARTBEAT_SECONDS=30
WECOM_MAX_ATTEMPTS=3
WECOM_REQUEST_TIMEOUT_SECONDS=15
WECOM_API_BASE_URL=https://qyapi.weixin.qq.com
```

The API exposes only `default` when the fixed recipient is configured. The raw `userid` stays in the deployment secret environment and is never copied to PostgreSQL. This is sufficient for the stated one-salesperson MVP and avoids introducing an unsafe home-grown encryption scheme; a future multi-recipient feature can add a proper secret-store-backed recipient table.

## Durable data model

`wecom_delivery_jobs` references `material_packages` with `RESTRICT` and stores:

- material package, recipient id, mode (`test` or `formal`), package version;
- stable request/content fingerprints;
- overall status and `text_status`/`image_status`;
- lease owner/token/expiry/heartbeat, attempt count, next attempt and safe last error;
- timestamps.

`wecom_delivery_attempts` references the job and stores message kind, attempt number, request fingerprint, provider request id, safe response code, result state, latency and timestamp. It never stores access tokens, Authorization headers, raw response bodies, media ids or source image URLs.

The unique key is `(material_package_id, recipient_id, mode, package_version, content_fingerprint)`, represented by a stable job request fingerprint. Retrying updates the same job; a new material package version creates a new job.

## State and retry rules

`queued -> running -> delivered` is the success path. If only one child message succeeds, the job becomes `partial`. A timeout around an external send becomes `delivery_unknown`; the job is not automatically retried. Explicit provider rate-limit/5xx/network failures that occur before a response are retryable up to `WECOM_MAX_ATTEMPTS` with bounded exponential backoff. Invalid credentials, invalid recipient, visibility/permission errors, malformed media, and all-invalid recipient responses are terminal `failed` states.

The dispatcher claims with `FOR UPDATE SKIP LOCKED`, sets a lease, and heartbeats while calls are in flight. It persists the completed child result before attempting the next child. A reclaimed lease checks already persisted child states and never repeats a delivered child.

## Official provider flow

1. Get or refresh a process-local application token.
2. For an enabled image child, load the private MinIO object and validate bytes/type/size. Convert only supported image formats if the local image adapter already provides that capability; otherwise fail safely because the official upload contract is JPG/PNG.
3. Upload the image as multipart field `media` with `type=image` and retain `media_id` only in local memory for the immediate send.
4. POST the text message with `enable_duplicate_check=1`.
5. POST the image message with the uploaded `media_id` and duplicate checking enabled.
6. Record bounded response metadata and discard the temporary media id.

## API contracts

```text
GET  /api/v1/wecom/recipients
POST /api/v1/material-packages/{package_id}/wecom-deliveries
GET  /api/v1/wecom-deliveries/{delivery_id}
POST /api/v1/wecom-deliveries/{delivery_id}/retry
```

Creation accepts `recipient_id`, `mode`, `include_copy`, and `include_image`; it returns `202` and a stable delivery id. Formal creation requires an approved package. Test mode is marked in the text and has an idempotency scope separate from formal mode. Retry is limited to retryable/unknown states after explicit operator action and never reopens a delivered job.

## Compatibility, rollout and rollback

- The migration is additive and does not alter existing package or selection rows.
- The new service is isolated behind a Compose profile and disabled by default. Existing acquisition/content services do not import the dispatcher entrypoint.
- Rollback is stopping the `wecom` profile and reverting the additive migration in a development database. Existing material packages remain usable; no provider-side message can be withdrawn by this integration.
- Real delivery requires the operator to set the four deployment values and enable the profile. Tests use `httpx.MockTransport`; no credential is needed for the normal test suite.
