# Design: Freshness, Governance Readiness, and Compliant Acquisition

## 1. Design Intent

Preserve the existing immutable acquisition and governance contracts while making the handoff
between them explicit. The acquisition layer rejects stale or unprovable documents from the normal
candidate feed; the governance layer remains the only source of event projections; the content
scheduler waits for a terminal governance snapshot before capturing a topic cutoff; and a provisional
no-topic result can be superseded by a new immutable revision when later governance data becomes
available.

## 2. Data Flow

```text
approved source registry
        |
        v
safe HTTPS fetch -> list/detail snapshots -> freshness gate -> evidence candidates
        |
        v
terminal governance run -> immutable event versions
        |
        v
readiness-aware topic reconcile -> topic run revision/cutoff -> daily current decision
        |
        v
copy-generation reconciliation consumes only the current revision
```

Freshness is enforced twice for different ownership reasons: acquisition prevents new stale
documents from entering the ordinary feed, while deterministic topic scoring protects against old
historical event versions already present in the database.

## 3. Freshness Contract

Add a pure domain policy that receives an observed publication instant, an evaluation instant, and a
maximum age. It returns `fresh`, `stale`, or `unknown` with a stable reason code. The acquisition
executor evaluates discovery metadata before detail requests when possible. If metadata is missing,
it fetches the already bounded detail URL, lets the connector extract the publication instant, then
filters before `save_candidate`.

Filtered items still retain the source response snapshot and an append-only observation with safe
metadata (`freshness_rule_version`, `published_at`, `cutoff_at`, `reason`). No source body is added
to logs or error responses. The run/job filtered counters include freshness filtering separately from
title relevance so operators can tell why the source list was not accepted.

`CONTENT_FRESHNESS_WINDOW_DAYS=10` becomes part of the immutable topic scoring config metadata and
bumps the scoring version. Existing event versions remain queryable, but an event older than the
window receives the existing `stale_event` veto using the stored run cutoff.

## 4. Governance Readiness and Topic Revisions

### Readiness query

Add a repository-owned read model that finds the latest terminal acquisition run for the business
date and its governance run. It returns `not_ready` when acquisition is absent/non-terminal,
governance is absent, or any governance job is queued/running/retry-scheduled. It returns `ready`
for governance `succeeded` or `partially_succeeded` with a fresh UTC cutoff. The content scheduler
uses a bounded interval reconciliation while the date is due; it does not create a topic run with a
premature cutoff.

### Revision model

Extend topic-selection runs with an integer `revision` and a supersession relationship. Replace the
single date/profile run uniqueness with `(business_date, timezone, scoring_profile, revision)` while
preserving a database-enforced current-selection uniqueness invariant. Daily selection rows remain
immutable and gain `superseded_at`/`superseded_by_run_id`; queries resolve the current row only.

Normal enqueue creates revision 1 when no run exists. Recovery enqueue is allowed only when the
current decision is a no-topic result, readiness now has a later governed cutoff, and no recovery
revision is already queued/running for the same date/profile. It creates revision + 1 with a new
cutoff, then atomically marks the old current decision superseded when the new decision persists.

Selected topics cannot be replaced by this path. The old run, scores, and decision remain available
for audit. Copy reconciliation keys itself to the current run ID, so the old no-topic run cannot
create downstream work and the new run can create at most one work item.

## 5. Compliant Fetch Boundary

Pass the source's recorded crawl policy into `SourceProfile` and enforce it before each request.
Disallowed policy states produce a terminal policy observation. Manual-review sources remain enabled
only through their explicit registry approval and retain their lower request rate; no runtime code
tries to discover a workaround.

Extend the typed transient fetch error to carry a bounded retry delay derived from `Retry-After`.
Clamp it to the existing operational retry maximum, preserve jitter for absent/invalid headers, and
never retry permanent policy responses. Keep `trust_env=False`, no persistent cookies, no automatic
redirects, host/path/IP validation on every hop, response streaming bounds, and the stable User-Agent.

Persist the next source request slot on the source fetch lease. The worker reserves a slot before
each list or detail request, sleeps outside the database transaction, and releases ownership without
deleting the pacing watermark. This preserves the configured interval across separate jobs,
retries, worker restarts, and concurrent workers for the same source.

Do not add browser automation, proxy pools, fingerprint changes, CAPTCHA solving, login/session
handling, or arbitrary robots fetching that increases request volume. Source terms/robots decisions
remain versioned registry data and are observable in job outcomes.

## 6. Compatibility and Migration

- Bump the acquisition policy version and topic scoring version so new rules are distinguishable from
  historical runs.
- Add one Alembic migration for topic revisions/supersession and any required filtered-observation
  metadata/index changes. Existing rows receive revision 1 and remain current unless readiness
  recovery explicitly supersedes a provisional no-topic decision.
- Existing source versions and immutable snapshots are not rewritten. Existing topic API consumers
  continue receiving the current decision fields; revision/supersession fields are additive.
- The first deployment reconciliation may create one revision-2 recovery for the observed 2026-08-03
  early `all_vetoed` run, only after the terminal governance run is detected. No direct data patch is
  part of rollout.

## 7. Failure and Rollback

- If readiness lookup fails, content reconciliation remains queued and logs a safe dependency code;
  acquisition/governance continue independently.
- If freshness parsing fails, preserve the bounded snapshot and mark the observation filtered or
  parse-failed; never silently treat unknown dates as fresh.
- If the revision migration or recovery path fails, disable content scheduling while retaining
  acquisition/governance data; old topic decisions and all evidence remain readable.
- Rollback disables the new scheduler/recovery flags and deploys the previous image; migrations are
  forward-compatible and do not downgrade or delete historical rows.

## 8. Key Risks

- Strict unknown-date filtering may reduce candidate volume. This is intentional and visible through
  filtered counters; source-specific URL/date parsers can be added later under a new version.
- A 10-day window may leave no topic on quiet days. `no_topic` remains a valid safe outcome.
- Seven provider review results in the observed run are separate from crawler behavior. Improving
  output validation/prompt contracts is a follow-up unless focused tests show a regression caused by
  this change.
