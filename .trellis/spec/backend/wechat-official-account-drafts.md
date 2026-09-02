# WeChat Official Account Draft Adapter

## 1. Scope / Trigger

Use this contract when changing the opt-in server-side adapter that stages finalized Official
Account V2 articles in the WeChat Official Account draft box. This boundary is distinct from
Enterprise WeChat (`WECOM_*`) and from the immutable local weekly exporter.

The boundary is default-off and `draft_only`. Development may opt in directly; production also
requires the explicit acknowledgement and minimum-week contract. The direct service may obtain a stable token,
upload article images, upload one permanent cover thumbnail, and create one draft per finalized
article. An independent, default-off Scheduler/Worker/CLI path may durably stage exactly the three
finalized live weekly roles through the same direct service. It has no FastAPI route, `freepublish`,
mass-send, homepage-pin, login, or browser-automation capability. Creating a draft is not
publication and must not advance `not_published`, `awaiting_manual_pin`, or `confirmed` operator
state.

## 2. Signatures

### Application port

```python
WeChatOfficialAccountDraftClient.upload_inline_image(
    image_bytes: bytes,
    media_type: str,
    filename: str,
) -> WeChatInlineImage

WeChatOfficialAccountDraftClient.upload_thumb(
    image_bytes: bytes,
    media_type: str,
    filename: str,
) -> WeChatThumbMedia

WeChatOfficialAccountDraftClient.add_draft(
    article: WeChatDraftArticleRequest,
) -> WeChatDraftCreated
```

### Local orchestration

```python
source = WeChatDraftLocalSource(
    directory=finalized_v2_directory,
    role="official_anchor",
    content_source_url=None,
    need_open_comment=False,
    only_fans_can_comment=False,
)

service = WeChatOfficialAccountDraftOnlyService(client=client)
receipt = await service.create_draft(source)
receipts = await service.create_weekly_drafts(
    (official_source, industry_source, application_source)
)
```

`create_weekly_drafts` accepts exactly the canonical three-role order and returns exactly three
independent `WeChatDraftReceipt` values. A receipt contains the safe role, Article/content
fingerprints, draft media ID, uploaded-body-image count, aware creation time, `mode=draft_only`,
and `not_published=true`. It is not a publication confirmation event.

### Durable process

```text
python -m app.wechat_official_account_draft_main enqueue-weekly WEEKLY_AGGREGATE_DIR
python -m app.wechat_official_account_draft_main reconcile [--once] [--maximum N]
python -m app.wechat_official_account_draft_main status JOB_UUID
python -m app.wechat_official_account_draft_main worker [--once | --drain] [--worker-id ID]
```

The CLI returns safe projections only: no artifact path or content, credentials, access token, or
raw provider media ID. It closes database/client resources in success, failure, and cancellation
paths. Default-off construction must not import into or alter the ordinary weekly DAG process.

## 3. Contracts

### Environment

| Key | Contract |
|---|---|
| `WECHAT_MP_ENABLED` | `false` by default; no ordinary dependency graph constructs a client |
| `WECHAT_MP_MODE` | Only `draft_only` |
| `WECHAT_MP_API_BASE_URL` | Exactly `https://api.weixin.qq.com` |
| `WECHAT_MP_APP_ID` | `SecretStr`; required only when enabled; never serialize or log |
| `WECHAT_MP_APP_SECRET` | `SecretStr`; required only when enabled; never serialize or log |
| `WECHAT_MP_REQUEST_TIMEOUT_SECONDS` | Bounded positive total/request timeout |
| `WECHAT_MP_MAX_IMAGE_BYTES` | Additional local source bound, at most 10 MiB |
| `WECHAT_MP_MAX_RESPONSE_BYTES` | Bounded from 1 KiB to 1 MiB; default 64 KiB |
| `WECHAT_MP_DRAFT_WORKER_ENABLED` | `false` by default; enqueue/reconcile/worker execution fails closed |
| `WECHAT_MP_DRAFT_AUTO_ENQUEUE_ENABLED` | `false` by default; enables inbox reconciliation and requires the worker |
| `WECHAT_MP_DRAFT_PRODUCTION_ENABLED` | `false` by default; production-only acknowledgement required by an enabled adapter/worker |
| `WECHAT_MP_DRAFT_MIN_WEEK_START` | Optional ISO Monday in development; required for production auto-enqueue |
| `WECHAT_MP_DRAFT_WEEKLY_INBOX_ROOT` | Process-local inbox root for finalized weekly aggregates |
| `WECHAT_MP_DRAFT_ARTIFACT_ROOT` | Process-local root for content-addressed staged weekly artifacts |
| `WECHAT_MP_DRAFT_POLL_SECONDS` | Bounded worker polling interval |
| `WECHAT_MP_DRAFT_LEASE_SECONDS` | Bounded lease duration longer than heartbeat interval |
| `WECHAT_MP_DRAFT_HEARTBEAT_SECONDS` | Bounded ownership-renewal interval |
| `WECHAT_MP_DRAFT_MAX_ATTEMPTS` | Bounded retry-attempt ceiling |
| `WECHAT_MP_DRAFT_RETRY_BASE_SECONDS` | Bounded deterministic retry base delay |

Enabled settings are accepted in development, or in production with the explicit production
acknowledgement. The acknowledgement is rejected outside production. Missing, blank,
whitespace-bearing, or control-bearing credentials fail during settings validation. `.env.example` contains empty
placeholders only; real credentials belong in ignored `.env` or deployment secret storage.

### Official HTTP contract

The infrastructure client owns these exact POST requests:

```text
/cgi-bin/stable_token
  JSON: grant_type=client_credential, appid, secret, force_refresh

/cgi-bin/media/uploadimg?access_token=TOKEN
  multipart: media=<JPG|PNG, strictly below 1 MiB>

/cgi-bin/material/add_material?access_token=TOKEN&type=thumb
  multipart: media=<JPEG, strictly below 64 KiB>

/cgi-bin/draft/add?access_token=TOKEN
  JSON: {"articles": [{"article_type": "news", ...exactly one article...}]}
```

Draft limits are title at most 32 characters, author at most 16, digest at most 120, content below
20,000 characters and at most 1 MiB UTF-8, `content_source_url` at most 1 KiB and safe HTTPS, and
provider media IDs at most 128 characters. `only_fans_can_comment=true` requires
`need_open_comment=true`.

All responses are byte-bounded, identity-encoded JSON objects. Reject duplicate keys,
non-standard constants such as `NaN`, non-integer `errcode`, malformed success fields, redirects,
and non-2xx responses. Never include the request URL, query token, credential, provider `errmsg`,
or raw response body in an exception or representation.

The process-local stable-token cache expires early from `expires_in`. Only explicit authenticated
WeChat token errcodes `40001`, `40014`, and `42001` invalidate the stale token and retry once.
Refresh is coalesced under a lock for the same stale token so concurrent failures cannot invalidate
a token another coroutine just refreshed. Bare HTTP 401/403 is a provider rejection, not proof of
a refreshable WeChat errcode. Any write timeout is `wechat_mp_outcome_unknown` and is never
automatically replayed.

`uploadimg` provider URLs are accepted only from the exact WeChat image hosts `mmbiz.qpic.cn` and
`mmecoa.qpic.cn`, without credentials, custom port, fragment, control characters, or HTML
delimiters. An official HTTP URL is normalized to HTTPS before application use; arbitrary HTTPS
hosts and sibling `qpic.cn` hosts are rejected.

### Local preparation and image derivation

Before the first token or write request, the application service loads every requested finalized
V2 child and verifies its manifest, ZIP, body hash, Article/content identities, canonical role,
passed/local-only release truth, file hashes, sizes, decoded dimensions, real non-symlink files,
and exact allowlisted HTML/media correspondence. The three-role method prepares all three children
before it uploads article 1.

The HTML allowlist is the existing inline WeChat fragment shape: `section`, `p`, `span`, `a`,
`img`, and `br`, with bounded registered attributes. Image `src` values must be unique safe
`assets/*` paths; external, `data:`, `blob:`, path-traversal, missing, duplicate, or unused media
fails preparation. The service replaces each exact local `src` once with the returned HTTPS
WeChat URL.

Original artifact bytes never change. An oversized inline raster is deterministically converted
to a metadata-free JPEG below 1 MiB without cropping or changing aspect ratio. The bound wide
cover is deterministically center-cropped to exact 47:20, converted to metadata-free JPEG, and
downscaled/quality-stepped below 64 KiB. Upload filenames and the aware receipt clock are validated
for all articles before any write.

### Immutable weekly handoff and durable execution

Enqueue accepts only a strict live weekly aggregate with the canonical three roles, finalized
release truth, and exact live provenance. Discovery is bounded and deterministic. The artifact
store copies the aggregate into an immutable content-addressed directory, then returns an opaque
reference; later loading resolves under the trusted root and rejects traversal, symlinks, and
identity drift. Database rows and safe projections store references/fingerprints, never local paths
or article content.

Revision `20260901_0042` adds one job row, exactly three role items, and append-only attempts.
Request identity includes the staged artifact fingerprint, exact AppID account fingerprint, item
presentation policy, and versioned draft-job policy. Concurrent enqueue is conflict-safe and
verifies the full persisted identity. Claims use `FOR UPDATE SKIP LOCKED`, leases, heartbeat, and
fencing tokens. The current child persists a side-effect-start checkpoint immediately before its
first provider write; completed roles are never replayed during resume.

Only typed known-safe transient failures may retry. Write timeouts, cancellation after a started
side effect, lease loss, and stale result persistence resolve conservatively to `outcome_unknown`
or the authoritative current terminal status. A stale worker must never mutate recovered state or
crash the process while resolving a rejected result. Downgrade removes empty tables but refuses
while durable audit rows exist.

Production auto-enqueue additionally binds an explicit authenticated minimum Monday. Both manual
enqueue and discovery reject a valid older manifest with `wechat_mp_draft_before_activation`
before copying an artifact, preparing content, creating a job, or constructing a provider client.
Discovery inspects the complete deterministic candidate set up to the hard scan ceiling, filters
old/invalid inputs, and only then applies the requested eligible limit; scan overflow fails closed.

The production runtime is an optional, portless `wechat-official-account-draft` Compose profile.
Its weekly DAG volume is mounted read-only at the configured inbox and its immutable staging tree
uses a separate writable named volume. The service shares the reviewed application image, waits
for migration, and is excluded from the ordinary production start/restore graph until an operator
atomically installs the production acknowledgement, minimum Monday, and worker/auto-enqueue flags.

## 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Adapter disabled, wrong mode/environment, or credentials incomplete | Fail closed before HTTP client use |
| Base URL differs from the exact official HTTPS origin | Settings/client construction fails |
| Child is not finalized V2, passed, local-only, or identity-consistent | `wechat_mp_draft_preparation_invalid`; zero calls |
| Third weekly child, its ZIP, filename, clock, HTML, or media is invalid | Reject all three before article 1 upload |
| Inline image cannot normalize below 1 MiB or thumb below 64 KiB JPEG | Preparation failure; zero calls |
| Provider image URL is off-host or syntactically unsafe | `wechat_mp_invalid_response` |
| JSON is duplicate-keyed, `NaN`, oversized, non-object, or malformed | `wechat_mp_invalid_response` without body leakage |
| Explicit `40001`/`40014`/`42001` for cached token | Coalesced forced refresh and exactly one replay |
| Second explicit token-invalid response | Terminal `wechat_mp_token_invalid` |
| Bare HTTP 401/403 or permission errcode | Safe provider rejection; no token replay |
| HTTP/provider rate limit or transient code | Typed retryable failure; no write replay inside adapter |
| Upload/thumb/draft transport timeout | `wechat_mp_outcome_unknown`; never auto-retry |
| Draft succeeds | Return safe receipt with `not_published=true`; operator state remains unchanged |
| Concurrent identical enqueue | One durable job with exactly three role items; both callers observe it |
| Lease loss or cancellation before any side effect starts | Safe retry/failure transition without provider replay |
| Lease loss, timeout, or cancellation after side effect starts | `outcome_unknown` or current terminal state; no replay |
| Resume after one or two successful roles | Reuse completed items; execute only remaining roles |
| Populated `0042` downgrade | Refuse without deleting durable audit data |
| Production adapter/worker without explicit acknowledgement | Settings fail before database/client construction |
| Production auto-enqueue without an ISO Monday cutoff | Settings fail before process construction |
| Valid aggregate older than the cutoff | `wechat_mp_draft_before_activation`; zero copy/job/provider calls |
| Matching inbox candidates exceed the hard scan ceiling | Fail the reconciliation scan closed |

## 5. Good / Base / Bad Cases

- Good: all three finalized children preflight locally, each body image is uploaded and rewritten,
  each independent thumb is uploaded, and three separate one-article draft payloads return three
  safe receipts without changing local artifacts or publication state.
- Base: `WECHAT_MP_ENABLED=false`; local fixtures, exporters, API, workers, and tests construct no
  client and make zero WeChat requests.
- Good: simultaneous requests observe the same invalid cached token and produce only one forced
  stable-token refresh before replaying against the shared replacement.
- Bad: combine the three weekly articles into one `articles` array, call `freepublish`, treat a
  draft media ID as a published URL, or advance the homepage-pin state machine.
- Bad: upload article 1 before validating article 3, silently mutate the exported cover, accept an
  arbitrary provider image host, log a query token, or replay an ambiguous write timeout.

## 6. Tests Required

- `httpx.MockTransport` contract tests assert exact methods, paths, query fields, multipart names,
  `force_refresh`, `article_type=news`, one-article payloads, limits, filename/media agreement, and
  official image URL normalization.
- Token tests assert early cache expiry, one explicit-invalid replay, concurrent refresh
  coalescing, terminal second invalid result, and no replay for bare HTTP 401/403.
- Response/error tests assert byte bounds, duplicate keys, `NaN`, invalid success fields,
  permission/rate/transient classification, timeout unknown state, and absence of AppID, AppSecret,
  token, provider body, host, and query URL in representations.
- Application tests build three finalized V2 children and assert all-three preflight, exact source
  rewriting, five media uploads per article where present, three independent drafts, safe receipts,
  deterministic inline/thumb normalization, metadata removal, 47:20 thumb ratio, and original tree
  byte immutability.
- Tamper tests cover the third child, ZIP corruption, symlinks, hash/size/dimension drift,
  external/data/duplicate images, unsafe HTML/style/filenames, invalid clock, wrong role order, and
  duplicate identities with zero fake-client calls.
- Worker/repository tests cover exact three-role idempotency, concurrent enqueue/claim,
  lease/heartbeat/fencing, stale recovery, side-effect checkpoints, retry versus unknown,
  cancellation, partial resume/no replay, safe status projection, CLI cleanup, and populated
  downgrade refusal on real PostgreSQL.
- Production tests cover acknowledgement/cutoff cross-validation, historical manual and automatic
  rejection, old-name starvation prevention, scan overflow, the portless optional Compose command,
  read-only inbox/writable artifact mounts, and exclusion from ordinary release service lists.
- Run focused Ruff, mypy, the adapter tests, V2/weekly/WeCom regressions, task validation, and
  `git diff --check`. Tests never use real credentials or a real network transport.

## 7. Wrong vs Correct

Wrong:

```python
# This creates partial side effects before the weekly input is known to be valid and confuses a
# draft with publication.
for source in weekly_sources:
    receipt = await service.create_draft(source)
    publication_state = "awaiting_manual_pin"
```

Correct:

```python
# The service preflights all three finalized children before its first provider request. A draft
# receipt remains explicitly unpublished.
receipts = await service.create_weekly_drafts(
    (official_source, industry_source, application_source)
)
assert all(receipt.not_published for receipt in receipts)
```
