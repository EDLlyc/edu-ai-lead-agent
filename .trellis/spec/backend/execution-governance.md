# Execution Governance

This specification defines the project-owned runtime boundary for Agent work, deterministic DAG
nodes, tools, model calls, budget allocation, safe causal tracing, and artifact lineage. The policy
version is `execution-governance-v1`. It supplements the product-specific Agent Workbench and
pipeline specifications; it does not replace their public contracts.

## Scenario: Governed Agent or deterministic DAG execution

### 1. Scope / Trigger

Use this contract whenever project code:

- starts an Agent run or a deterministic DAG batch/node;
- delegates work to a child agent or node;
- invokes a model or registered capability under a runtime budget;
- records execution events or artifact lineage; or
- exposes a bounded execution timeline or aggregate usage projection.

The shared core is additive. Existing Agent Workbench HTTP, MCP, tool, citation, loopback, and eval
wire contracts remain unchanged and are projected into this core through the pure Workbench
adapter. Product analytics such as anonymous IP-search funnel counters are not execution events and
must not enter this ledger.

### 2. Signatures

The domain and service signatures are owned by these modules:

```python
# app.domain.execution_governance
ExecutionIdentity(run_id: UUID, task_id: str, agent_id: str)
BudgetLimits(
    elapsed_ms: int,
    model_turns: int,
    input_tokens: int,
    output_tokens: int,
    tool_calls: int,
    tool_result_bytes: int,
    artifact_bytes: int,
    max_children: int = 0,
    max_depth: int = 1,
    allow_child_agents: bool = False,
)
BudgetUsage(
    elapsed_ms: int = 0,
    model_turns: int = 0,
    input_tokens: int | None = 0,
    output_tokens: int | None = 0,
    tool_calls: int = 0,
    tool_result_bytes: int = 0,
    artifact_bytes: int = 0,
    child_count: int = 0,
)
CapabilityDefinition(
    name: str,
    access: CapabilityAccess,
    allowed_roles: frozenset[ExecutionRole],
    timeout_ms: int,
    max_argument_bytes: int,
    max_result_bytes: int,
    task_scoped: bool = True,
    artifact_scoped: bool = False,
)
CapabilityRequest(
    identity: ExecutionIdentity,
    role: ExecutionRole,
    capability_name: str,
    target_task_id: str,
    parent_event_id: UUID,
    argument_bytes: int,
    artifact_ids: tuple[UUID, ...] = (),
    expected_input_tokens: int = 0,
    expected_output_tokens: int = 0,
    model_turns: int = 0,
    tool_calls: int = 1,
    expected_artifact_bytes: int = 0,
)

# app.application.services.execution_governance
ExecutionGovernanceService.create_run(...) -> tuple[AllocationSnapshot, SafeExecutionEvent]
ExecutionGovernanceService.allocate_child(...) -> AllocationSnapshot
ExecutionGovernanceService.append_event(draft: SafeEventDraft) -> SafeExecutionEvent
ExecutionGovernanceService.produce_artifact(...) -> tuple[SafeExecutionEvent, ArtifactMetadata]
CapabilityGateway.invoke(request, handler) -> GovernedCapabilityResult[T]

# app.application.ports.execution_governance
ExecutionGovernanceRepository.reserve_budget(...) -> BudgetReservationSnapshot
ExecutionGovernanceRepository.reconcile_budget(...) -> BudgetReservationSnapshot
ExecutionGovernanceRepository.complete_allocation(...) -> bool
ExecutionGovernanceRepository.list_timeline(
    *, run_id: UUID, limit: int = 200, max_bytes: int = 128 * 1024
) -> tuple[SafeExecutionEvent, ...]
```

Migration `20260831_0039` owns five additive PostgreSQL tables:

| Table | Key / purpose |
|---|---|
| `execution_governed_runs` | Run identity, immutable root limits, policy version, request fingerprint, terminal status |
| `execution_agent_allocations` | `(run_id, task_id, agent_id)`, role, parent, depth, limits, used and reserved counters, next sequence |
| `execution_trace_events` | Event UUID, allocation identity, per-agent sequence, causal parent, safe counters/status |
| `execution_artifacts` | Opaque artifact metadata bound to its producer event and agent |
| `execution_budget_reservations` | Capability reservation and exact-once reconciliation ledger |

There is no new public HTTP API or environment variable in this version. PostgreSQL remains the
source of truth and uses the existing async session factory.

### 3. Contracts

#### Identity and causal events

- `run_id` is a UUID. `task_id` and `agent_id` are opaque safe references of 1–128 characters.
- A root allocation starts with `run_started` at `seq_no=0` and no parent. Every other event has a
  parent. Each agent's sequence is contiguous and allocated while its row is locked.
- Cross-agent causality is expressed only by `parent_event_id`; wall-clock completion order is not a
  causal contract. A child allocation's first event is `node_started` and must point to the parent
  event recorded on that allocation.
- Parent events must belong to the same run and task and have a kind allowed for the child kind.
  Artifact metadata must match the producer event's run, task, agent, event ID, and artifact ID.
- Event kinds are closed: run/node start/finish/fail, model/tool request/result,
  `artifact_produced`, `budget_denied`, and `permission_denied`.
- `input_tokens=None` or `output_tokens=None` means provider usage is unknown. Never fabricate a
  count. Once an allocation's accumulated token value becomes unknown, later positive reservations
  for that token dimension fail closed.

#### Budgets and delegation

- Root limits are frozen when the run is created. A lowercase 64-character SHA-256 request
  fingerprint is unique and provides idempotent replay. Concurrent identical creation requests
  return the existing compatible allocation; a conflicting identity, role, or limit set is
  `invalid_event`.
- Budget dimensions are elapsed milliseconds, model turns, input/output tokens, tool calls, tool
  result bytes, artifact bytes, child count, and depth. All limits and usage are non-negative;
  elapsed limit is positive.
- Capability execution first reserves the maximum bounded vector under a row lock. Reservation is
  separate from actual usage. Reconciliation atomically subtracts reserved values and adds bounded
  actual values exactly once. A retry must use the same identity and values.
- A running allocation with an unreconciled capability reservation or running child cannot become
  terminal. This prevents parent release while work can still consume budget.
- Child allocation atomically reserves its complete ceiling from the parent. Completion releases
  that ceiling and adds the child's actual usage plus one completed child. Concurrent children
  cannot oversell any dimension.
- Child agents are disabled by default. When explicitly enabled, `max_children > 0` and
  `max_depth > 0` are required. Default maximum depth is 1; the non-configurable system hard maximum
  is 2. Delegation is rejected once any bounded parent dimension reaches 70% used plus reserved.
- Exhaustion and denial never create new budget, and retrying does not reset counters.

#### Capability authorization and execution

- `CapabilityRegistry` is non-empty, lexically sorted, unique, and closed. An unknown name is denied.
- The gateway validates active allocation, stored role, role allowlist, task scope, access class,
  artifact scope, argument size, and budget before invoking the handler.
- Orchestrator/planner cannot invoke `business_write`. Reviewer cannot invoke `plan` or
  `business_write`; it may read and check. Worker receives only the capability and artifact scope
  required by its node.
- Authorization and reservation denials happen before the handler. Timeout, cancellation, and
  handler exception reconcile the reservation with bounded observable usage and append a safe
  failure event. Raw exceptions and provider bodies are not projected.
- Capability timeouts are positive and have a non-configurable hard maximum of 900,000 ms. A
  registry should choose the smallest bound that covers its operation; the weekly persisted
  long-form article boundary is the explicit 15-minute exception, with its internal provider wait
  kept below that outer bound. Timeout remains a cancellation and reconciliation boundary, not a
  promise that an external side effect can be replayed.
- Result, token, model-turn, or artifact usage beyond the reservation is capped during
  reconciliation and then rejected with a stable denial. Oversized output is never returned as a
  successful governed result.

#### Safe trace and artifacts

- Trace fields are an allowlist: opaque identity, closed enums, safe target/provider/model/error
  names, counts, durations, byte sizes, hashes, parent IDs, and lifecycle state.
- Never store messages, prompts, chain-of-thought, provider bodies, credentials, database URLs, raw
  arguments/results, private object keys/paths, IP/UA, or user profile tokens.
- Artifact rows contain only opaque reference identity, kind, media type, byte size, lowercase
  SHA-256, lifecycle status, and producer binding. Content and image bytes stay in their owning
  storage system.
- Timeline queries require `1 <= limit <= 200` and `1 <= max_bytes <= 131072`. They return a causal
  topological order and stop before exceeding the serialized byte limit. Broken causality fails
  closed.
- Populated governance tables cannot be destructively downgraded. Operators must explicitly migrate
  or preserve data before reversing migration `0039`.

#### Workbench compatibility

`workbench_budget_limits`, `workbench_capability_definitions`, and
`project_workbench_result` are pure compatibility projections. They preserve the four existing
read-only tools and existing public responses. Do not route Workbench requests through a new public
endpoint or change MCP schemas merely to expose governance metadata.

### 4. Validation & Error Matrix

| Condition | Stable result | Handler runs? |
|---|---|---:|
| Unknown capability | `capability_unknown` | No |
| Request role differs from allocation or is not allowlisted | `role_forbidden` | No |
| Planner/orchestrator business write or reviewer plan/write | `write_forbidden` | No |
| Target task differs from allocation task | `task_scope_forbidden` | No |
| Required artifact missing, inactive, or from another run/task | `artifact_scope_forbidden` | No |
| Argument exceeds capability maximum | `argument_too_large` | No |
| Used + reserved + requested exceeds any dimension | `budget_exhausted` | No |
| Child agents disabled | `recursion_disabled` | No child created |
| Depth exceeds allocation or hard maximum 2 | `depth_exhausted` | No child created |
| Any parent dimension is at least 70% used + reserved | `delegation_threshold_reached` | No child created |
| Child limit reached | `child_limit_exhausted` | No child created |
| Allocation is terminal, has an active child, or has an open reservation | `allocation_not_active` | No / cannot terminate |
| Capability timeout | `capability_timeout` plus reconciled usage | Handler cancelled |
| Caller cancellation | cancellation re-raised plus safe `capability_cancelled` event | Already cancelled |
| Handler raises | `capability_failed` plus reconciled usage | Already started |
| Result bytes exceed capability maximum | `result_too_large` after bounded reconciliation | Already started |
| Model/token/artifact result exceeds reservation | `budget_exhausted` after bounded reconciliation | Already started |
| Duplicate identity, mismatched replay, bad parent/kind, non-contiguous/cross-run event, duplicate artifact/reservation | `invalid_event` | No further effect |
| Unknown artifact during artifact production/scope lookup | `unknown_artifact` or scoped denial, depending on call boundary | No further effect |
| Invalid fingerprint, safe name/ref, media type, SHA, negative value, or query bound | Construction `ValueError` | No |

Database `IntegrityError` is an infrastructure detail and must not escape this boundary; known
concurrency or uniqueness conflicts map to `invalid_event`.

### 5. Good / Base / Bad Cases

- Good: A worker reserves one tool call and 64 KiB output, the handler returns 8 KiB, reconciliation
  moves 8 KiB and one call into used counters, and a `tool_result` points to its `tool_requested`
  event.
- Good: A deterministic DAG node records zero model turns and zero tokens, produces an artifact
  metadata row, then allows downstream work to use that artifact through same-run/task scope.
- Base: A provider omits token usage. Persist `None`, keep locally observable time/call/byte usage,
  and do not claim an exact token total.
- Base: Eight concurrent calls create the same compatible request fingerprint. Exactly one run/root
  event is persisted and all callers observe the same root allocation.
- Bad: A reviewer is given a write capability in its prompt. The prompt is irrelevant; the gateway
  rejects the invocation before the handler.
- Bad: A child is created after a parent reaches 70% in one budget dimension, or two children reserve
  the same remaining budget concurrently. Both cases fail closed; the ledger is never oversold.
- Bad: A terminal status is written while a reservation remains open. Completion is rejected until
  that reservation is reconciled.
- Bad: An event references a parent in another run or an artifact claims a producer event from
  another agent. Persistence rejects it as `invalid_event`.

### 6. Tests Required

- Unit/domain: safe identity/name construction, immutable serialization, non-negative vectors,
  unknown token representation, role/access rules, closed registry ordering, depth defaults and
  hard maximum, delegation threshold, event/artifact shape, and bounded Workbench projection.
- Gateway: assert unknown capability, role, write, task, artifact, argument, and budget denial occurs
  before the handler; assert timeout, cancellation, exception, oversized result, token, and artifact
  paths reconcile once and emit only stable safe metadata.
- PostgreSQL integration: assert concurrent identical run creation replays one row; concurrent child
  and capability reservations cannot oversell; reservation reconciliation is idempotent; allocation
  cannot terminate with open work; per-agent sequence remains contiguous; duplicate/cross-run/broken
  parent and producer bindings fail closed without leaking `IntegrityError`.
- Migration: upgrade from `0038` creates all five tables and constraints; empty downgrade removes
  them; populated downgrade refuses; repository/ORM metadata and Alembic head remain `0039`.
- Privacy: scan schema, serialized events, timeline responses, errors, and representative logs for
  forbidden content fields and secret-like values.
- Compatibility: Workbench OpenAPI drift, MCP official-SDK transport, loopback behavior, four-tool
  registry/limits, citations, model contracts, offline eval, Agent portfolio backend tests, and
  Workbench frontend tests remain green.
- Quality: task-scoped Ruff, format, mypy, PostgreSQL tests, and `git diff --check` must pass. Full
  repository failures must be proven unrelated before they are excluded.

### 7. Wrong vs Correct

#### Wrong

```python
# Prompt-only authorization, direct handler call, and accounting after the fact can oversell.
if "reviewer" in system_prompt:
    return await tools[request.capability_name](raw_arguments)

allocation.used_tool_calls += 1
allocation.used_tool_result_bytes += len(raw_result)
trace.append({"prompt": prompt, "result": raw_result, "error": repr(error)})
```

#### Correct

```python
definition = registry.get(request.capability_name)  # closed-world lookup
authorize_capability(definition, request)           # role/task/access/size before handler
reservation = await repository.reserve_budget(
    identity=request.identity,
    reservation_id=reservation_id,
    requested=bounded_maximum,
)
try:
    result = await bounded_handler()
finally:
    await repository.reconcile_budget(
        identity=request.identity,
        reservation_id=reservation.reservation_id,
        actual=bounded_safe_usage,
    )
# Persist only SafeExecutionEvent and ArtifactMetadata allowlisted fields.
```

The reservation must be durable before execution, and all terminal paths must reconcile it. The
gateway—not the prompt—owns authorization and fail-closed behavior.
