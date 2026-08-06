# Technical Design: Enterprise WeChat Group Webhook Delivery

## Architecture

The group webhook is a second provider behind the existing durable delivery boundary:

```text
material package
    -> API enqueue (safe logical recipient: default)
    -> wecom_delivery_jobs / attempts
    -> wecom dispatcher claim + lease
    -> provider adapter selected from settings
    -> HTTPS webhook: Markdown, then image
```

The API never calls Enterprise WeChat. The dispatcher keeps provider side effects outside database
transactions and persists each child result before starting the next child. No migration is needed:
the existing job identity already includes package version, logical recipient, mode, content
fingerprint, and message-kind flags.

## Boundaries and Contracts

### Configuration

Add:

- `WECOM_DELIVERY_PROVIDER=self_built_app|group_webhook`, defaulting to the current
  `self_built_app` for compatibility;
- `WECOM_GROUP_WEBHOOK_KEY`, represented as `SecretStr`, required only when the group provider is
  enabled;
- provider-specific group limits with defaults of 4096 Markdown bytes and 2 MiB raw image bytes.

The fixed host remains `https://qyapi.weixin.qq.com`; the adapter appends the secret key as a query
parameter only at request time. Settings validation branches by provider: self-built-app retains
its CorpID/AgentID/CorpSecret requirements, while group mode does not require those values or a raw
recipient userid. `WECOM_DEFAULT_RECIPIENT_NAME` remains a safe display label for the configured
group.

The existing global defaults remain conservative. Automatic direct delivery is an explicit deploy-
time combination of `WECOM_ENABLED=true`, `WECOM_AUTO_DELIVERY_ENABLED=true`, and
`WECOM_REQUIRE_REVIEW_BEFORE_SEND=false`; blank/default local configuration remains inert.

### Provider port

Keep the current self-built-app methods (`upload_image` and media-id `send_image`) for compatibility.
Add a provider-neutral `send_image_bytes(...)` delivery method used by the executor:

- the self-built-app client validates the bytes, uploads temporary image media, then sends the
  returned media id;
- the group client validates/prepares the bytes and sends the webhook image JSON directly.

Both clients implement the existing safe `send_text(...)` result projection. The executor does not
know provider-specific credentials or payload shapes.

### Group webhook adapter

Implement a settings-bound `WeComGroupWebhookClient` under the WeCom infrastructure boundary. It:

1. validates the fixed HTTPS host, secret key shape, bounded timeouts, retry count, and response
   size;
2. sends `POST /cgi-bin/webhook/send?key=KEY` with either:
   `{"msgtype":"markdown","markdown":{"content":CONTENT}}` or
   `{"msgtype":"image","image":{"base64":BASE64,"md5":MD5}}`;
3. disables redirects and parses only bounded JSON;
4. maps HTTP/provider codes to the existing safe retry/rejection/unknown error types;
5. exposes only a bounded provider request id/response code, never the key or raw body.

The `recipient_id` and `agent_id` arguments remain part of the shared delivery call shape for the
existing executor but are ignored by the group adapter after the application has validated the
logical `default` recipient. They are never sent in the webhook payload.

### Image preparation

The executor first verifies the immutable MinIO descriptor and source bytes exactly as it does for
the existing provider. A group-specific bounded preparation helper then:

- returns valid PNG/JPEG bytes unchanged when they are already within 2 MiB;
- otherwise decodes a bounded raster, rejects excessive dimensions/pixels and malformed data, then
  applies deterministic JPEG quality/downscale steps until the output is within 2 MiB;
- preserves transparency as PNG when possible and converts only when needed to meet the limit;
- returns the prepared media type and bytes without mutating or re-storing the source artifact.

The adapter computes Base64 and MD5 from the returned prepared bytes. The two-megabyte check applies
to raw bytes before Base64 expansion, matching the official contract.

### Dispatcher selection

The existing `wecom_dispatcher_main.py` creates the group client when the provider setting is
`group_webhook`; otherwise it creates the current self-built-app client. Both use the same executor,
MinIO read path, lease recovery, automatic reconciliation, and shutdown lifecycle.

## State and Failure Semantics

- Markdown is sent before the image and each success is committed before the next side effect.
- HTTP 429/5xx and explicitly temporary provider codes use the existing bounded backoff.
- A send timeout or ambiguous transport failure is `delivery_unknown`; it is not automatically
  retried because the webhook has no caller-supplied idempotency key.
- A successful Markdown plus failed image remains partial or queued according to the existing job
  state machine. A later retry skips the delivered Markdown child.
- A duplicate enqueue returns the existing job by request fingerprint. Provider payloads do not
  claim an invented idempotency feature.

## Compatibility and Rollback

- No database or public API schema change is required.
- Existing self-built-app settings and tests stay valid; provider selection defaults to that adapter.
- Rollback is configuration-only for an operational issue: switch the provider back to
  `self_built_app` or disable WeCom, then stop the dispatcher. Code rollback does not require data
  migration.
- The group webhook key is supplied only through a permission-restricted deployment environment or
  secret manager. It is never committed to `.env.example`, task notes, logs, or screenshots.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Webhook sends are not exactly-once | Stable durable fingerprints, duplicate enqueue protection, and unknown timeout state; no automatic resend after ambiguity |
| Generated PNG exceeds 2 MiB | Deterministic bounded conversion/downscale with a terminal local failure if it cannot meet the limit |
| Markdown content exceeds 4096 bytes | UTF-8 byte validation before the provider call; no silent truncation of the complete copy |
| A key leaks through an authenticated URL | SecretStr, fixed host, no URL logging, and redaction tests |
| Group route accidentally requires self-built credentials | Provider-specific settings validation and configuration contract tests |
