# 公众号每周三篇确定性 DAG：技术设计

## 1. Static graph

The graph is code-owned and versioned:

```text
schedule
  -> select_roles
      -> official_anchor.build_article -> plan_media -> render_handoff -> validate_child
      -> industry_trend.build_article -> plan_media -> render_handoff -> validate_child
      -> application_case.build_article -> plan_media -> render_handoff -> validate_child
  -> aggregate
  -> finalize
```

Graph construction validates unique IDs, allowed node/role combinations, all dependencies and acyclicity at import/test time. There is no planner model and no runtime edge mutation.

## 2. Persistence

Add typed weekly DAG tables from the implementation-time migration head:

- run: opaque run/task ID, week start, schedule/selection/DAG versions, input fingerprint, status, aggregate artifact ref/fingerprint and timestamps;
- node: stable node key/kind/role, status, dependency fingerprint, attempt count, lease owner/expiry/fencing token, safe input/output artifact refs, safe error code and timestamps.

The graph edges remain code-owned; the database does not accept arbitrary JSON edges. Unique run identity enforces once-per-week/version. Completed node outputs are immutable checkpoints.

## 3. Scheduler and worker

The scheduler calls the existing pure due function and idempotently enqueues one run plus all static nodes. A separate worker claims one ready node with `FOR UPDATE SKIP LOCKED`; readiness requires every code-owned dependency to be successful. Lease heartbeats and fencing follow existing worker patterns.

At most three branch nodes may run concurrently. Aggregate/finalize are exclusive per run. Retryable failures release only the failed node after backoff; terminal failure blocks descendants. Explicit retry resets a failed node and its incomplete descendants but never a successful sibling branch.

## 4. Handler adapters

Each node handler calls existing weekly/V2 services and returns only safe typed references/fingerprints:

- selection stores the strict existing selection projection;
- article/media/render nodes reference existing durable snapshots or local artifact identities;
- validation calls the existing V2/weekly child validators;
- aggregate calls the existing aggregate builder/writer unchanged;
- finalize binds the aggregate fingerprint and ready status.

Content/media bytes stay in their existing artifact owners, not node rows.

## 5. Governance integration

Run creation allocates one governed root. Every node maps to a governed agent/node identity and causal start/finish events. The three branch start events share the selection completion parent; each downstream event points to its own prior node. Deterministic nodes record zero model tokens truthfully.

Capabilities are closed handlers, not general tools. The worker must pass governance authorization and budget reservation before calling a handler. Artifact refs registered by one node are required inputs for the next.

## 6. Status API/CLI

Expose development-only enqueue, bounded run status and explicit retry. Status lists nodes in code-owned order with role, state, attempts, safe error, timing and artifact readiness. It never returns body text, prompts, provider responses, media paths or internal lease owner.

No new end-user frontend is required for MVP; the existing official-account panel may later consume the status resource after API stability.

## 7. Compatibility, rollout and rollback

The existing one-shot fixture/live CLIs remain callable as test or operator tools. The DAG feature defaults off until migrations and worker are present. Disabling the scheduler/worker leaves existing artifacts readable. Downgrade refuses while durable DAG rows exist unless local rows are explicitly cleared; it never deletes weekly child artifacts.

## 8. Failure boundaries

No partial aggregate is written. Stale workers cannot commit. A successful checkpoint is never silently recomputed. Any identity, hash, mobile, release, publication or visual-distinctness mismatch becomes a stable terminal code. No WeChat/WeCom client is constructible from DAG composition.
