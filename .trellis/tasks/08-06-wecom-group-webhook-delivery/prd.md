# Add Enterprise WeChat group webhook delivery

## Goal

Deliver each eligible daily material package to a dedicated Enterprise WeChat group through the
official message-push webhook (the former group-robot route). The package contains the complete
parent-readable Moments copy and the generated brand image. Delivery remains an internal review/
distribution action; the system does not publish to Moments or any other social platform.

The selected route is group delivery, not a one-to-one Enterprise WeChat conversation. The
recommended operating setup is a dedicated group containing the owner and the target salesperson.

## Confirmed Background

- The existing self-built-application adapter and durable `wecom_delivery_jobs` workflow already
  support text-before-image delivery, child attempts, leases, bounded retries, idempotent enqueue,
  and safe provider error projection. This task must preserve that route as a fallback.
- The current self-built-app configuration requires CorpID, AgentID, CorpSecret, and a raw internal
  userid. A group webhook instead needs only outbound HTTPS access and a secret webhook key.
- The official endpoint is
  `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY`.
- The official message-push document is
  `https://developer.work.weixin.qq.com/document/path/91770`.

## Requirements

### R1. Provider selection and configuration

- Add an explicit provider setting that selects either the existing self-built application or the
  group webhook. Keep self-built-app behavior backward compatible.
- Add a secret group-webhook key setting. Build the official URL from the fixed official host and
  the key; do not accept arbitrary webhook URLs, log the key, expose it in API output, or persist it
  in PostgreSQL.
- Group-webhook mode must not require CorpID, CorpSecret, AgentID, userid, trusted IP, or an inbound
  HTTPS callback. It remains disabled unless the operator explicitly enables WeCom and automatic
  delivery.
- The existing recipient projection may continue to expose the safe logical id `default`; it must
  never expose the raw webhook key or a raw self-built-app userid.

### R2. Message content and limits

- Send the topic title and complete generated copy as one Markdown message. Preserve the copy's
  emoji and normal label lines, subject to the official 4096-byte UTF-8 Markdown limit.
- Keep the existing visible test marker for test-mode jobs.
- Send the image as a separate image message after the Markdown message. Do not use the webhook
  file-upload endpoint for images.
- Respect the provider's maximum of 20 pushed messages per minute. The dispatcher must not create
  an unbounded burst when multiple packages are queued.

### R3. Image handling

- Read the immutable private MinIO image and verify its stored size, checksum, media type, object
  key, and signature before any provider call.
- In group-webhook mode, prepare a bounded JPG/PNG payload no larger than 2 MiB. If the immutable
  source is already valid and within the limit, send it unchanged; otherwise perform a bounded,
  deterministic in-memory compression/downscale without modifying the original MinIO artifact.
- Send the prepared image's Base64 and MD5 of the raw prepared bytes. Do not persist the prepared
  bytes, webhook key, or any temporary provider credential.
- Reject malformed, unsupported, oversized, or uncompressible images with a stable local error and
  no provider side effect.

### R4. Queue, idempotency, and failure behavior

- Reuse the durable enqueue/dispatcher boundary. The API only creates or returns an idempotent job;
  only the independent dispatcher performs webhook calls.
- Preserve text-before-image ordering and persist the successful child before starting the next
  child. A text success plus image failure remains visible as partial or queued for an eligible
  retry.
- Keep the stable job and child fingerprints for audit/idempotency. Since the webhook API has no
  application idempotency field, a send timeout or ambiguous transport result must become
  `delivery_unknown` and must not be automatically resent.
- Retry only bounded, classified rate-limit or temporary HTTP/provider failures, up to the existing
  maximum. Invalid keys, malformed responses, unsupported payloads, and provider rejections become
  safe terminal errors.

### R5. Automatic operation

- When `WECOM_AUTO_DELIVERY_ENABLED=true` and the configured quality/review policy permits direct
  delivery, the dispatcher must discover eligible packages and enqueue formal jobs automatically.
- The implementation must support the user's no-manual-review rollout through the existing direct
  delivery policy (`WECOM_REQUIRE_REVIEW_BEFORE_SEND=false`) without removing quality validation or
  audit gates.
- Delivery still targets the configured group only and never calls a Moments publishing API.

### R6. Tests and documentation

- Add contract tests for webhook URL construction, Markdown payloads and byte limits, Base64/MD5
  image payloads, response classification, bounded response parsing, timeout handling, and secret
  redaction.
- Add service tests for provider selection, group-mode recipient semantics, image preparation,
  text-before-image ordering, idempotency, partial failure, and unknown timeout behavior.
- Update environment examples, Compose wiring, and the backend WeCom delivery specification.

## Acceptance Criteria

- [ ] A configured group-webhook dispatcher can send a Markdown copy followed by an image through
      the official webhook endpoint using only outbound HTTPS and the webhook key.
- [ ] The Markdown body is rejected before a provider call when its UTF-8 size exceeds 4096 bytes;
      the existing self-built-app route continues to use its 2048-byte limit.
- [ ] A source image above 2 MiB is either deterministically converted to a valid JPG/PNG at or
      below 2 MiB or ends in a stable local failure without changing the original artifact.
- [ ] The image request contains the prepared raw bytes' Base64 and MD5, and tests prove that no
      raw key, userid, token, media id, URL query credential, or provider body is logged or returned.
- [ ] Repeating the same package/version/provider/recipient/mode request returns the existing job;
      it does not create a duplicate durable job or an avoidable duplicate send.
- [ ] A provider timeout produces `delivery_unknown` and no automatic resend; a text-success/image-
      failure path persists the text success and exposes the unresolved image.
- [ ] `WECOM_AUTO_DELIVERY_ENABLED=true` plus direct mode can run without manual approval, while
      existing copy/image validation and audit gates remain enforced.
- [ ] Existing self-built-app contract/unit tests remain green, new webhook tests are green, and
      `docker compose config --quiet` renders with blank placeholder credentials.
- [ ] No database migration is needed; the existing delivery tables and API response contract stay
      compatible and contain only safe logical recipient identifiers.

## Out of Scope

- Replacing or removing the existing self-built Enterprise WeChat application adapter.
- One-to-one chat delivery, member lookup, group membership management, inbound callbacks, trusted
  IP/domain configuration, or server-side webhook administration.
- Webhook file/voice/news/template-card messages.
- Automatic publishing to朋友圈, enterprise WeChat Moments, or any external social platform.
- Persisting a compressed derivative as a new material artifact; the original package image remains
  the source of truth.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
