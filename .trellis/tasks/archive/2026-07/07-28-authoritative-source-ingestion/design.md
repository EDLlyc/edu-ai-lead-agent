# Design: Authoritative-Source Acquisition and Evidence Ingestion

## 1. Design Intent

Build one secure, end-to-end acquisition slice rather than eight unrelated scrapers. Source
differences are isolated behind versioned connector profiles while scheduling, network policy,
snapshotting, provenance, idempotency, API contracts, and observability remain shared.

The current Trellis task remains the implementation target instead of becoming a parent with
separate persistence/connector/API child tasks. Those parts share one migration, state machine,
connector contract, and end-to-end acceptance flow; splitting them before the contracts exist
would create integration-only partial deliveries. `implement.md` still introduces explicit review
and rollback gates between foundation, connectors, runtime, and API work.

## 2. Runtime Architecture and Boundaries

```text
                         PostgreSQL (durable truth)
                       /            |             \
  FastAPI API --------/        Scheduler          Worker pool
  list/enqueue/query           due-run reconcile  claim/heartbeat/retry
                                                   |
                                                   v
                                      Safe HTTPS fetch boundary
                                        |                 |
                                  source connector     MinIO snapshots
                                        |
                                        v
                        title relevance gate (AI-centered)
                                        |
                                        v
                              evidence candidate + observation
                                        |
                              typed API handoff (candidate ID)
                                        |
                       later LangGraph workflow (separate task)
```

- `app.api_main` owns HTTP routing, schemas, request correlation, and application-service
  dependencies. It never fetches source content or starts a scheduler thread.
- `app.scheduler_main` owns time-based reconciliation only. It calculates the current business
  date, enqueues a missing durable run, and exits/repeats safely under database uniqueness.
- `app.worker_main` polls and claims durable jobs, renews leases, executes acquisition outside a
  database transaction, persists results in short transactions, and handles graceful shutdown.
- `app/domain` owns source tiers, run/job/outcome enums, state-transition rules, typed source items,
  hashes, and idempotency-key rules without FastAPI, SQLAlchemy, HTTPX, or MinIO imports.
- `app/application` owns enqueue, claim/execute, persist-result, complete-run, and query use cases.
  It depends on ports for repositories, storage, fetch, clock, ID generation, and connectors.
- `app/infrastructure` owns SQLAlchemy repositories, MinIO, safe HTTP, source-specific adapters,
  scheduling integration, and process wiring.
- `app/schemas` owns Pydantic v2 request/response/configuration models. ORM models are never reused
  as API schemas.
- LangGraph is a downstream consumer, not an acquisition runtime dependency. It may orchestrate
  later summarization, clustering, selection, generation, checkpoints, and human review by reading
  candidate IDs through the API; it does not replace scheduler/worker leases or safe fetching.

## 3. Proposed Backend Layout

```text
backend/
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/<revision>_create_acquisition_schema.py
├── app/
│   ├── api/
│   │   ├── dependencies.py
│   │   └── v1/routes/{sources,acquisition_runs,evidence_candidates}.py
│   ├── application/
│   │   ├── ports/{clock,connectors,repositories,snapshot_store}.py
│   │   └── services/{enqueue_runs,execute_acquisition,query_acquisition}.py
│   ├── core/{config,errors,logging,security}.py
│   ├── domain/{entities,enums,state,value_objects}.py
│   ├── infrastructure/
│   │   ├── db/{models,repositories,session}.py
│   │   ├── ingestion/
│   │   │   ├── connectors/
│   │   │   ├── extraction.py
│   │   │   ├── fetcher.py
│   │   │   ├── registry_seed.py
│   │   │   └── source_profiles.py
│   │   └── storage/minio_snapshot_store.py
│   ├── schemas/{common,sources,acquisition,evidence}.py
│   ├── api_main.py
│   ├── scheduler_main.py
│   └── worker_main.py
└── tests/{unit,contract,integration,fixtures}/
```

Small shared modules may be combined when that improves cohesion. No generic `utils.py` is added.

## 4. Configuration Contract

All values are validated settings and environment-overridable. The implementation will add at
least:

- `ACQUISITION_SCHEDULE_HOUR=6`
- `ACQUISITION_SCHEDULE_MINUTE=30`
- `ACQUISITION_CATCHUP_HOURS=12`
- `ACQUISITION_POLL_SECONDS`
- `ACQUISITION_WORKER_CONCURRENCY`
- `ACQUISITION_LEASE_SECONDS`
- `ACQUISITION_HEARTBEAT_SECONDS`
- `ACQUISITION_MAX_ATTEMPTS`
- `ACQUISITION_MAX_RESPONSE_BYTES`
- `ACQUISITION_CONNECT_TIMEOUT_SECONDS`
- `ACQUISITION_READ_TIMEOUT_SECONDS`
- `ACQUISITION_TOTAL_TIMEOUT_SECONDS`
- `ACQUISITION_MAX_REDIRECTS`
- `ACQUISITION_USER_AGENT`
- `ACQUISITION_FIRST_RUN_ITEM_LIMIT`
- `ACQUISITION_DAILY_ITEM_LIMIT`
- `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY` as redacted secrets distinct from Compose-only names.

Settings validate that heartbeat is shorter than lease duration, retry counts and byte limits are
bounded, schedule values are valid, production does not use placeholder MinIO credentials, and
the User-Agent is identifiable. API, scheduler, and worker load the same settings class.

## 5. Source Registry and Connector Contract

### 5.1 Versioned registry

`sources` stores stable identity and operational enablement. Immutable `source_versions` records
hold fetch/parser policy. Historical jobs and snapshots point to the exact source version used.
Changing an entry point, tier, allowed host, rate policy, or parser creates a new version.

The initial registry is deterministic seed data applied by an idempotent application command or
migration-adjacent seed step, not by external requests inside an Alembic migration. The seed uses
stable source UUIDs/slugs and creates a new version only when the configuration fingerprint
changes.

### 5.2 Initial profiles

| Connector key | Tier | List shape | Incremental signal | Detail extraction |
|---|---:|---|---|---|
| `gov_cn_policy_v1` | A | Public JSON plus policy list | ETag, Last-Modified, item URL/date | Source-specific policy selectors, generic fallback |
| `bnu_news_v1` | A | Static HTML | ETag, Last-Modified, known item/cursor | Static article selectors, trafilatura fallback |
| `cas_research_v1` | A | Static dated HTML links | Known item/date overlap | CAS content selectors, trafilatura fallback |
| `sensetime_news_v1` | A | Next.js-rendered HTML links | Numeric item ID, content hash | Structured page data/trafilatura fallback |
| `xinhua_tech_v1` | B | Static dated `/c.html` links | Item path/date, content hash | Xinhua article selectors, trafilatura fallback |
| `gmw_education_v1` | B | Compressed static dated links | Item path/date, content hash | Guangming main-text selector, fallback |
| `stdaily_tech_v1` | B | Approved static section pages | Item ID/date, sitemap/list overlap | Technology Daily article selectors, fallback |
| `chinanews_education_v1` | B | Static education channel/subsections | Item ID/date, content hash | China News article selectors, fallback |

### 5.3 Typed connector boundary

Connectors receive a `SourceVersion`, previous cursor/validators, and bounded collection policy.
They return application-owned values such as:

- `FetchedResponse`: final validated URL, status, selected safe headers, media type, bytes, hash,
  and fetch time;
- `DiscoveredItem`: source item ID, URL, optional title/publication time, list snapshot reference;
- `ExtractedDocument`: title, clean text, publication time, language, canonical URL, extraction
  metadata, and parser version;
- `CollectionCursor`: validators and last-seen item/date information.

Adapters do not write SQL or objects directly. The application service controls snapshot-before-
normalization order and persistence.

### 5.4 AI-centered title relevance policy

Connectors parse and order a bounded recent discovery window without making product relevance
decisions. The application layer applies one shared, versioned `TitleRelevancePolicy` before any
detail request, then accepts up to the configured relevant-item limit.

The initial vocabulary covers direct AI/model/agent/learning/algorithm terms, AI infrastructure
such as computing power and AI chips, vision/speech/NLP, robotics/embodied intelligence,
autonomous systems/drones, and brain-computer interfaces. General frontier-science terms are not
sufficient by themselves unless the same title explicitly connects them to AI, robotics, or an
intelligent system. Policy-document wording such as plans, measures, regulations, standards,
governance, notices, and support policies is accepted when the same title also contains a direct AI
or intelligent-technology term. Matching uses Unicode normalization and ASCII case folding,
returns the exact matched terms, and has a stable rule version.

The discovery scan limit is separate from the accepted-item limit. A connector can therefore skip
newer unrelated headlines and still find a relevant item lower in the bounded list. Missing-title
items are rejected conservatively after duplicate image/text anchors have had a chance to merge.
When no title matches, the job succeeds with zero candidates and a durable filter summary; it does
not fetch an unrelated detail page or raise parser drift.

## 6. Persistence Model

All identifiers are UUIDs and instants are UTC `TIMESTAMPTZ`. Text state fields use domain enums
plus named check constraints so state changes do not require PostgreSQL enum rewrites.

| Table | Purpose and important constraints |
|---|---|
| `sources` | Stable slug/display identity, enabled flag, owner; unique `slug` |
| `source_versions` | Immutable tier, hosts, paths, entry point, connector/parser/relevance-rule versions, schedule/rate/robots policy, config fingerprint; unique `(source_id, version)` and `(source_id, config_fingerprint)` |
| `source_cursors` | Current ETag/Last-Modified/item/date cursor per source version with optimistic version; unique `source_version_id` |
| `acquisition_runs` | Scheduled/manual trigger, business date/timezone, acquisition version, status and aggregate new/unchanged/duplicate/filtered counts; unique non-null scheduled business key |
| `acquisition_jobs` | One source-version job per run, state, available time, attempt count, lease owner/expiry/heartbeat, error and new/unchanged/duplicate/filtered counters; unique `(run_id, source_id)` |
| `acquisition_attempts` | Append-only attempt timing, result/error code, safe request ID, byte/count metrics |
| `source_fetch_leases` | Short-transaction per-source fetch exclusion across concurrent runs/workers; unique `source_id`, expiring lease |
| `source_snapshots` | Immutable list/detail snapshot metadata and content-addressed MinIO key; unique `(bucket, object_key)` and content identity |
| `evidence_candidates` | Versioned normalized source document with URL/item/title/text/hash/parser metadata; unique source identity/content keys that permit later revisions |
| `source_observations` | Append-only run/job/item outcome linking the observed snapshot and candidate, including unchanged/duplicate/not-modified outcomes; idempotent observation key |

Core foreign keys and states remain relational. Flexible, source-specific extraction/response
metadata may use bounded JSONB after removing cookies, authorization, set-cookie, signed URLs, and
unbounded bodies.

## 7. State Machines and Concurrency

### Run states

`queued -> running -> succeeded | partially_succeeded | failed | cancelled`

- `partially_succeeded` means at least one source succeeded and at least one source ended in a
  terminal failure. Disabled sources are recorded as skipped and do not cause failure.
- Run completion is derived in one application service after all jobs are terminal.

### Job states

`queued -> running -> succeeded`

`running -> retry_scheduled -> running` for retryable outcomes only.

`queued | running | retry_scheduled -> failed | cancelled` for terminal or administrative ends.

State transition functions validate expected current state. Claims use `FOR UPDATE SKIP LOCKED` in
a short transaction, set a lease owner/expiry, and commit before network/object-store calls.
Heartbeats update only a job owned by the same lease token. Expired running jobs are reclaimable;
attempt and idempotency records prevent duplicated persisted results.

Per-source fetch leases prevent overlapping manual and scheduled runs from simultaneously hitting
the same source. They expire automatically after a worker crash.

## 8. Scheduling Semantics

APScheduler runs only inside `scheduler_main` as a wake-up mechanism. PostgreSQL, not APScheduler
memory, decides whether work exists.

At startup and on the cron trigger:

1. Convert the injected/current clock to `Asia/Shanghai` or configured IANA timezone.
2. Calculate today's scheduled instant.
3. If now is before it, do nothing.
4. If now is after it but within `ACQUISITION_CATCHUP_HOURS`, insert the scheduled run using a
   unique business key and create one job for each enabled source version.
5. If the insert conflicts, treat it as an expected already-enqueued result.
6. Do not automatically create historical runs older than the catch-up window.

Two scheduler instances can execute the same calculation; database uniqueness yields one run.

## 9. Safe HTTP Boundary

`SafeHttpFetcher` is the only module allowed to perform source HTTP requests.

- Accept only HTTPS and normalized hostnames from the trusted source version.
- Reject userinfo, fragments, non-default/approved ports, IP-literal hosts, ambiguous hostnames,
  and paths outside the optional approved prefixes.
- Resolve all A/AAAA answers asynchronously and reject non-global, private, loopback, link-local,
  multicast, reserved, unspecified, and known cloud-metadata addresses.
- Disable automatic redirect following. Validate and resolve each `Location` before the next hop;
  reject scheme downgrade, host escape, missing/invalid location, and excess redirects.
- Stream response bytes into a bounded buffer while hashing. Abort when the configured maximum is
  exceeded; do not rely only on `Content-Length`.
- Accept only configured JSON/XML/feed/HTML/text media types, using conservative sniffing only when
  the server omits a type.
- Never persist or log request cookies, `Set-Cookie`, authorization, proxy authorization, or
  signed query parameters. The client does not maintain a cookie jar.
- Apply total/connect/read/write/pool timeouts and bounded worker concurrency. A per-source rate
  policy is enforced in addition to the database fetch lease.

Because URLs originate from an operator-approved registry rather than an arbitrary API parameter,
allowlist validation is the primary SSRF control; DNS/IP and redirect validation remain defense in
depth. Automated tests inject a resolver and HTTP transport so they stay offline and deterministic.

## 10. Snapshot, Extraction, and Idempotency Flow

For each list or accepted detail response:

1. Fetch through `SafeHttpFetcher` outside a database transaction.
2. Compute SHA-256 while streaming and build a content-addressed object key such as
   `source-snapshots/sha256/<first-two>/<hash>`.
3. Store/verify the immutable object through the MinIO port. The official synchronous MinIO
   client runs behind an explicit `asyncio.to_thread` boundary.
4. Persist snapshot metadata in a short idempotent transaction.
5. Parse a bounded discovery window, normalize titles, apply the versioned relevance policy, and
   persist/log a safe filter summary. Rejected items never cause a detail request.
6. For each accepted item, store the immutable detail response and run source-specific extraction.
7. Persist or reuse the evidence candidate by stable source item/canonical URL/content identity;
   extraction metadata records relevance rule version and matched terms.
8. Append an observation linking run, job, source version, outcome, snapshot, candidate, and safe
   relevance metadata.
9. Advance the source cursor from the newest discovered list item after accepted results and the
   filter summary are durable, even when zero relevant items were accepted.

An object write followed by a database failure may leave an unreferenced content-addressed object;
retries safely reuse it. Automated garbage collection is deferred, and no referenced snapshot is
deleted in this slice.

List scanning uses a configurable item limit and a publication/date overlap so late edits are not
missed. A known item stops deeper traversal only after the overlap/minimum page policy is met.

## 11. API Contract

All routes live under `/api/v1`:

- `GET /sources` — bounded list with active version and latest source health/count projection.
- `POST /acquisition-runs` — optional approved `source_ids`; creates a manual run and returns
  `202`, run resource, and `Location`/status URL. A client idempotency key may be accepted and
  database-enforced.
- `GET /acquisition-runs/{run_id}` — run status, aggregate counts, timestamps, trigger, and links.
- `GET /acquisition-runs/{run_id}/jobs` — per-source job state, safe outcome/error code, attempts,
  and counts.
- `GET /evidence-candidates` — cursor pagination with source and publication/fetch filters.
- `GET /evidence-candidates/{candidate_id}` — normalized metadata plus snapshot metadata and
  observation provenance. It does not expose object credentials or signed URLs.

The candidate list is the lightweight downstream queue and returns candidate ID, source slug and
display name, title, publication time, original/canonical URL, and relevance-rule version. A later
LangGraph node retrieves candidate detail for stored `clean_text` and snapshot provenance. It uses
the original URL as a citation/verification link rather than re-downloading the page during normal
execution. Normal downstream reads pass `relevance_rule_version=ai-title-v1` so legacy candidates
created before the title gate do not enter the AI workflow; omitting the filter keeps historical
records queryable for audit.

Central exception handlers map typed errors to the stable `{ "error": ... }` envelope. API list
queries select projections and avoid lazy-loading/N+1 behavior. OpenAPI is regenerated and the
frontend consumes generated types even though no new product page is built.

## 12. Observability and Privacy

One structlog configuration is shared by all three processes and emits JSON in production.
Correlation fields include `request_id`, `acquisition_run_id`, `job_id`, `attempt_id`, `source_id`,
and connector/parser versions. Stable event names cover enqueue, claim, heartbeat, fetch result,
retry, terminal failure, snapshot persistence, candidate observation, and run completion.

Durable tables provide the operational query surface; logs are not the job ledger. Source list
responses expose the latest-success and aggregate health projection. Metrics exporters and alert
infrastructure are deferred, but event/count fields are designed to support them.

Redaction tests cover settings representations, error envelopes, URL query stripping, headers,
cookies, raw HTML, and prompt-injection-like content.

## 13. Deployment, Migration, and Rollback

- Add a backend container build and Compose services for one-shot migrations, API, scheduler, and
  worker. Only the API may bind a loopback host port; scheduler and worker expose no public port.
- Application services depend on healthy PostgreSQL/MinIO and completed bucket/migration steps.
- Each process uses `restart: unless-stopped` and handles termination signals without marking
  interrupted work successful.
- Migrations are explicit and deterministic; process startup never calls `create_all()`.
- Rollback during development can stop scheduler/worker first, disable source records, then roll
  back application code. The initial schema downgrade may drop only acquisition-owned tables when
  data loss is explicitly accepted in non-production testing.
- Production rollback defaults to forward-fixing while preserving tables and MinIO objects.
- Public ingress, host provisioning, TLS termination, authentication/SSO, backups, and external
  alerts are documented as deployment prerequisites but are not implemented here.

## 14. Verification Design

- Pure unit tests use injected clocks, resolvers, transports, ID generators, and fixed jitter.
- Eight source fixture sets contain list and detail snapshots with expected item IDs, dates,
  canonical URLs, extraction results, and parser versions.
- Fetcher contract tests use an injected HTTPX transport/stream and fake public DNS answers; they
  never weaken the production loopback/private-IP policy.
- PostgreSQL integration tests run Alembic to head, test competing claims and uniqueness, and never
  substitute SQLite.
- MinIO integration tests verify object bytes/hash/metadata, same-content reuse, and refusal to
  associate a hash key with different content.
- The end-to-end test uses controlled connectors but real PostgreSQL and MinIO, then queries the
  ASGI API and repeats the run to prove idempotency/provenance.
- Live checks against the eight websites are an opt-in smoke command only, conservative and not
  required for deterministic CI.

## 15. Important Trade-offs and Deferred Items

- PostgreSQL polling/leases are selected over Redis/Celery because current throughput is small and
  PostgreSQL is already the durable state source. A queue can be introduced after measured need.
- The official synchronous MinIO client is wrapped at an explicit thread boundary instead of
  selecting an unofficial async client; concurrency is bounded to protect the thread pool.
- One JSON connector plus shared HTML machinery and eight versioned profiles avoids eight copies
  of networking/idempotency logic while preserving source-specific selectors.
- Exact duplicate handling is included; semantic similarity and cross-source event grouping are
  deliberately deferred.
- Media citations are retained, but automatic traversal from a Tier B article to every cited Tier
  A source is deferred until a later evidence-linking capability.
- LangGraph is selected for the later stateful AI workflow, not for deterministic acquisition.
  Keeping the handoff at the versioned evidence API prevents graph retries/model changes from
  issuing duplicate website requests and lets acquisition operate when AI services are unavailable.
