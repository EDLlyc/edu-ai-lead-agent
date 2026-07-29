# Implement Authoritative-Source Acquisition and Evidence Ingestion

## Goal

Deliver the first production-shaped capability from technical report v0.3: a server-deployable
system that automatically collects the newest AI-centered technology articles and policies exposed
by eight approved authoritative sources every day and stores a queryable, auditable
evidence-candidate pool with cleaned full text, immutable snapshots, complete provenance,
idempotent writes, durable execution state, and visible failures.

## Product Value

This capability creates the factual input boundary for every later topic-selection and generation
stage. It replaces ad hoc browsing with a repeatable daily evidence feed whose records can be
traced back to the exact source response, collection run, parser version, and original URL.

## Confirmed Context and Constraints

- The task began from a Python 3.11/FastAPI/Pydantic v2 shell with PostgreSQL 16/pgvector, MinIO,
  and frontend API type generation. The current working tree now contains the acquisition domain,
  migrations, scheduler, worker, eight connectors, snapshots, and query API; this revised scope
  extends that implementation without rewriting its historical data.
- API, scheduler, and worker run as separate processes. PostgreSQL is the durable state source of
  truth; MinIO stores source payloads.
- The acquisition capability must operate without the company AI platform.
- The server default schedule is daily at 06:30 in `Asia/Shanghai`. The time and timezone remain
  configurable without code changes.
- A healthy scheduler must enqueue one scheduled run per business date. If it restarts after 06:30
  and the current day's run is missing, it must enqueue a bounded same-day catch-up run.
- "Newest" means the newest title-relevant items found within a bounded recent window publicly
  exposed by each approved entry point at collection time. This is a daily incremental feed, not
  continuous real-time monitoring and not a guarantee about when a source publishes its own
  content. A newer unrelated item never displaces an older relevant item within that window.

## Requirements

### R1 — Approved, versioned first-batch source registry

Persist stable source identity, display name, organization type, trust tier, allowed HTTPS hosts,
connector kind, collection entry point, cadence, timezone/language, enabled state, owner,
terms/robots review, rate policy, and connector/parser version. Source configuration must be
versioned so a changed endpoint or parser does not rewrite historical provenance.

The eight default-enabled first-batch sources are:

| Tier | Category | Source | Approved entry point |
|---|---|---|---|
| A | Government/policy | China Government latest policies | `https://www.gov.cn/zhengce/zuixin/` and its public JSON endpoint |
| A | Education institution | Beijing Normal University News | `https://news.bnu.edu.cn/` |
| A | Research organization | Chinese Academy of Sciences research progress | `https://www.cas.cn/syky/` |
| A | AI company first-party publication | SenseTime News | `https://www.sensetime.com/cn/news` |
| B | Technology media | Xinhua News technology | `https://www.news.cn/tech/` |
| B | Education media | Guangming Online education | `https://edu.gmw.cn/` |
| B | Science and technology media | Science and Technology Daily | `https://www.stdaily.com/` with approved section paths |
| B | Education media | China News Service education | `https://www.chinanews.com.cn/edu/` |

These eight sources are the complete acquisition scope for this capability. Adding a ninth source,
general web search, or arbitrary URL ingestion requires a separately reviewed source-registry
change; the system must not expand its crawl frontier automatically.

Tier B media may support discovery, context, and corroboration. When a media article identifies a
Tier A primary source, later evidence use must prefer and preserve the primary-source link. Tier C
sources are not part of this batch. A source can be disabled independently without a code change.

### R2 — Daily server operation and durable scheduling

- A dedicated scheduler creates the daily run at 06:30 `Asia/Shanghai`, with a configurable
  schedule and a database-enforced business key that prevents duplicate scheduled runs.
- Scheduler startup reconciles a missing current-day run after the configured time within a
  bounded catch-up window.
- A dedicated worker claims persisted jobs, records attempts and heartbeats, and resumes from
  durable state after restart.
- One failed, disabled, or changed source must not prevent the other sources from completing.
- Manual API triggering is supported for operations and testing, but API requests only enqueue
  work and never perform acquisition inline.

### R3 — Safe, bounded connector boundary

- Only source-registry-approved HTTPS hosts and paths may be requested.
- Enforce host and resolved-IP policy, block private/loopback/link-local/metadata destinations,
  validate every redirect hop, and limit redirects.
- Enforce connection/read/total timeouts, maximum response bytes, accepted content types,
  bounded concurrency, identifiable User-Agent, and conservative per-source request rates.
- Respect the recorded robots/terms decision. Never bypass login, CAPTCHA, paywall, anti-bot
  controls, or TLS verification.
- Connectors expose application-owned typed discovery and extraction results; source-specific
  HTML/JSON structures stay inside infrastructure adapters.

### R4 — Incremental collection and immutable snapshots

- Use source item IDs, canonical URLs, publication windows/cursors, ETag, and Last-Modified where
  each source supports them.
- Bound first-run and daily list depth so a source cannot create an unbounded backlog or response.
- Preserve each accepted list/detail response or canonical source payload in MinIO before deriving
  normalized evidence data.
- Record object key/URI, media type, byte size, SHA-256, safe response metadata, fetch time, source
  version, connector version, and parser version in PostgreSQL.
- Content-addressed snapshot keys must not allow different bytes to replace an existing object.

### R5 — Provenance-bearing evidence candidates

- Persist original/canonical URL, source and source-version IDs, trust tier, title,
  publication/fetch timestamps, language, extracted clean text, source item ID, content hash,
  acquisition run/job IDs, snapshot reference, and extraction metadata.
- Derived clean text never replaces the stored source snapshot.
- Exact duplicate handling may reuse a candidate or snapshot body, but every observation retains a
  link to the source, run, job, response outcome, and artifact it observed.
- Semantic deduplication, event clustering, LLM classification, scoring, and selection are later
  capabilities and must not be introduced here.

### R6 — Typed outcomes, retries, and observability

- Persist distinct outcomes for new, unchanged/not-modified, exact duplicate, transient fetch
  failure, permanent fetch failure, policy rejection, response-limit rejection, unsupported
  content, and parse failure.
- Retry only typed transient failures using bounded exponential backoff with jitter. Permanent,
  policy, content-limit, and parse outcomes must not blind-retry.
- Emit structured correlated events with service, source, run, job, attempt, connector/parser
  version, duration, byte count, result status, and safe error code.
- Expose per-source latest success, current health, success/failure counts,
  new/unchanged/duplicate/filtered counts, parse failures, duration, and retry count through an
  internal query surface.
- Full source bodies, credentials, cookies, signed object URLs, sensitive personal information,
  and raw exceptions must not appear in logs or API errors.

### R7 — PostgreSQL, MinIO, and migration contract

- Use SQLAlchemy 2 async typed mappings, asyncpg, and Alembic migrations against real PostgreSQL.
- Use UUID identifiers, UTC-aware instants, named constraints/indexes, short transactions, durable
  leases, and database-enforced uniqueness for idempotency.
- Store source payloads in MinIO and relational identity/state/provenance in PostgreSQL.
- Do not use SQLite integration tests or `Base.metadata.create_all()` as a migration substitute.

### R8 — Internal API and generated contract

Provide versioned internal endpoints to:

- list approved sources and their latest acquisition status;
- enqueue a manual acquisition run and return `202 Accepted`, a durable ID, and status URL;
- inspect run and per-source job state;
- list and retrieve evidence candidates with provenance and snapshot metadata.

The bounded candidate-list projection used by later workflow nodes must expose source slug/display
name, latest relevant title, publication time, original/canonical URL, candidate ID, and relevance
rule version. It must support selecting the current relevance-rule version so historical unfiltered
candidates remain auditable without entering the normal downstream queue. Candidate detail remains
the authoritative handoff for stored clean text, immutable snapshot metadata, and observation
provenance.

Responses use stable error envelopes and cursor/bounded pagination. Regenerate and commit OpenAPI
and frontend API types. A user-facing source-administration or evidence-browsing page is not part
of this capability.

### R9 — Deterministic verification and server-ready process shape

- Unit tests cover source-tier rules, URL/host/IP policy, redirects, state transitions, retry
  classification, schedule/catch-up calculation, hashes, and idempotency keys.
- Connector contract tests use controlled local fixtures for all eight sources and cover success,
  not-modified, redirect escape, timeout, oversized response, unsupported type, parser drift, and
  prompt-injection-like page text. Automated tests do not depend on live websites.
- Integration tests use real PostgreSQL and MinIO for migrations, snapshots, uniqueness, job
  claiming, retries, observations, and provenance queries.
- API, scheduler, and worker have independent entry points suitable for separate processes or
  containers, with graceful shutdown and restart-safe behavior.
- An end-to-end acceptance flow enqueues a run, executes source jobs, stores snapshots and
  candidates, exposes provenance through the API, and proves a repeated run is idempotent.

### R10 — Title-level technology relevance gate

- Evidence candidates must follow an AI-centered technology scope: artificial intelligence, large
  models/generative AI, machine/deep learning, agents, algorithms, computing power, AI chips,
  computer vision, speech/NLP, robotics/embodied intelligence, autonomous systems, drones, and
  brain-computer interfaces. AI-related laws, regulations, national/local plans, standards,
  governance rules, notices, funding/support measures, and industrial policies are explicitly in
  scope. General policy, education, culture, finance, lifestyle, and frontier science such as
  quantum, aerospace, biotechnology, or new energy are excluded unless the title explicitly
  connects them to AI, robotics, or intelligent systems.
- Relevance is decided from the discovered title before the detail request. The first version uses
  a deterministic, versioned, auditable topic vocabulary; it does not call an LLM, embedding model,
  or external classification service.
- Connectors scan a bounded recent discovery window and return up to the configured number of
  relevant items. The configured item limit is the maximum accepted relevant-item count, not a
  license to fill the quota with unrelated articles.
- A source with no relevant title in the bounded window succeeds with zero accepted items and a
  visible filtered/no-match count or outcome. It must not fail parsing and must not fall back to an
  unrelated article.
- Matching is Unicode/case normalized, supports Chinese and common English terminology, and records
  the relevance-rule version plus matched terms in candidate/observation metadata for audit.
- Existing historical candidates remain immutable. The new relevance rule applies only to jobs
  using a newly seeded source version or acquisition-rule version.

### R11 — Stable downstream handoff and LangGraph boundary

- This capability ends at acquisition, relevance filtering, extraction, immutable snapshotting,
  provenance, and query APIs for the eight approved sources. It does not summarize, cluster, score,
  select, or generate content.
- Later workflow nodes receive candidate IDs and use stored clean text/snapshot provenance as their
  normal input. The original URL remains available for citation, human verification, and controlled
  refresh; downstream nodes must not independently re-crawl arbitrary URLs as their default path.
- LangGraph is approved for the later AI orchestration layer where stateful branching, checkpointed
  retries, human review, summarization, clustering, selection, and generation are needed. The
  acquisition API/scheduler/worker remain framework-independent and do not add a LangGraph runtime
  dependency in this slice.

## Acceptance Criteria

- [ ] A clean PostgreSQL database upgrades to Alembic head, and the acquisition schema uses named
      constraints and only capability-owned tables.
- [ ] The source API returns all eight approved sources with the expected tier, entry point,
      enablement, version, and schedule metadata.
- [ ] With a healthy server, the scheduler creates exactly one daily scheduled run at 06:30
      `Asia/Shanghai`; two scheduler replicas cannot create duplicates.
- [ ] Starting the scheduler later the same day creates the missing bounded catch-up run exactly
      once; it does not backfill an unbounded history.
- [ ] The API returns `202` for an enqueued manual run without making a source-network request in
      the request handler.
- [ ] Concurrent workers claim a job once, maintain a lease/heartbeat, and recover safely after a
      simulated interruption.
- [ ] A newly published fixture item is collected on the next run, stored as an immutable MinIO
      snapshot, and represented by a PostgreSQL evidence candidate with complete provenance.
- [ ] Reprocessing unchanged or exact-duplicate content does not duplicate candidate/snapshot
      bodies and does retain a new observation where appropriate.
- [ ] Disallowed hosts/IPs, redirect escape, excessive responses, unsupported content, and parser
      failures terminate with typed, queryable outcomes.
- [ ] One source failure produces a partial run result while successful sources remain available.
- [ ] Logs and API responses contain no full source body, secret, cookie, signed object URL, or
      sensitive personal information.
- [ ] OpenAPI/frontend generated types, backend quality gates, real PostgreSQL/MinIO integration
      tests, and the end-to-end acquisition acceptance flow pass.
- [ ] A mixed fixture whose newest entries include both unrelated and relevant titles persists only
      the relevant items, never requests unrelated detail URLs, and preserves newest-first ordering
      among accepted items.
- [ ] A fixture with no relevant titles completes successfully with zero candidates and an
      auditable no-match/filtered result; it does not substitute an unrelated article.
- [ ] Candidate or observation provenance exposes the deterministic relevance-rule version and the
      normalized title terms that caused acceptance, without storing a model-generated score.
- [ ] The candidate list exposes source, relevant title, publication time, original/canonical URL,
      candidate ID, and relevance-rule version; candidate detail supplies stored clean text and
      snapshot provenance suitable for a later LangGraph node without another website request.
- [ ] No embedding, LLM, scoring, generation, image, social publishing, or product frontend
      behavior is introduced.

## Out of Scope

- Semantic deduplication, event clustering, model-based taxonomy classification, topic scoring,
  and Top-1 selection. A deterministic title allowlist is the only relevance mechanism in scope.
- Brand knowledge ingestion or retrieval; LLM, embedding, or image-generation integration.
- General web discovery, arbitrary-domain crawling, login/session automation, CAPTCHA bypass, or
  paywall circumvention.
- User-facing frontend pages for source administration or evidence browsing.
- Automated social-platform publishing or storage of social credentials.
- Provisioning a specific production host, public DNS/TLS/reverse proxy, organization SSO,
  external monitoring infrastructure, backups, or automated retention deletion. The process and
  container shape must be deployable later, but those environment-specific operations are separate
  work.
- LangGraph graph implementation, LLM prompts/models, checkpoint schema, human-review UI, and all
  downstream summarization/generation behavior. This task only preserves the typed handoff boundary.
