# Agent 预算权限追踪统一化：技术设计

## 1. Layer ownership

```text
domain/execution_governance
  identities, roles, event/artifact kinds, budget math, validation

application/ports
  governance repository, capability gateway, clock

application/services
  create run, allocate child budget, authorize tool, append event, register artifact

infrastructure/db
  atomic budget ledger + append-only safe event/artifact metadata

adapters
  Agent Workbench legacy trace projection
  weekly DAG node projection
```

Names may adapt to repository conventions, but the shared core must not import Workbench, weekly or IP modules.

## 2. Durable schema

Use explicit typed columns rather than an unbounded trace JSON blob:

- governed runs: run UUID, task ref, policy/version, status, root agent, frozen budget ceilings/usage, timestamps and fingerprint;
- agent allocations: agent identity, role, parent agent/event, depth, reserved ceilings/usage and status;
- trace events: event UUID, run/task/agent, per-agent sequence, parent event, closed event kind, safe target/provider/tool identifiers, numeric usage/duration/size, result/error code and timestamp;
- artifact metadata: opaque artifact ref, run/task/producer event, kind, media type, byte size, SHA-256 and lifecycle status.

Foreign keys keep every event/artifact in one run/task. Unique `(run_id, agent_id, seq_no)` and event UUID constraints prevent reordering/replay. No content-bearing payload column is permitted.

## 3. Budget ledger

Root ceilings are immutable. Child allocation uses one transaction and a conditional update that succeeds only when every requested dimension fits the parent's unreserved remainder. Completion returns unused reservation only through one terminal transition; retries use the same allocation and cannot mint new budget.

Token fields are nullable/known-state. Calls, elapsed time and bytes remain enforceable even when provider token usage is unknown. The gateway performs a pre-call reservation and post-call bounded reconciliation. Crossing the 70% delegation threshold disables new children but does not abort already allocated work.

## 4. Capability authorization

Capability definitions include stable name, read/write class, allowed roles, task-scope rule, artifact-scope rule, argument/result byte limits and timeout. The gateway resolves the current allocation and rejects before invoking the handler. Unknown role/tool/scope is deny-by-default.

Workbench registers its existing four tools as reviewer/worker-safe read-only capabilities through an adapter. Existing Workbench limits remain the stricter local ceiling where they are lower than shared policy.

## 5. Trace and artifacts

Events are state/usage metadata, not reconstructed conversations. `parent_event_id` must exist earlier in the same run and represent an allowed causal edge. Each child agent starts from the exact event that allocated it. Artifact production is a separate metadata row bound to the producing event; consumers reference the opaque ID and verify hash/size outside the trace store.

## 6. API compatibility

The existing Workbench response is produced by a pure adapter from governed events plus existing safe citation projections. Its current ordering, four-call semantics, error codes and byte bounds remain unchanged. New shared timeline/status resources are development-only and bounded by event count/bytes.

## 7. Rollout and rollback

Introduce a new versioned policy and additive tables from the implementation-time migration head. First run compatibility in shadow/adapter mode for Workbench tests, then enable as the weekly DAG requirement. Rollback disables new governed-run creation; existing safe rows remain readable. Downgrade must refuse if tables contain rows unless an explicitly documented destructive local-development path is authorized.

## 8. Failure and privacy

Budget or permission denial appends only a stable denial event if the event budget itself remains available; otherwise it returns a typed error without calling the handler. Sanitized identifiers are code-owned or opaque. Targeted tests and scans reject prompt/message/body/path/credential-like fields in schema, logs and responses.
