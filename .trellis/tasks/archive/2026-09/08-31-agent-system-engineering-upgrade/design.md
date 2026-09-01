# Agent 系统检索、编排与治理升级：技术设计

## 1. Architecture

```text
Child A: IP retrieval V3
  IP metadata rank + multimodal rank -> versioned weighted RRF
  -> offline evaluator -> anonymous daily counters

Child B: Agent governance foundation
  typed causal identities + budget ledger + capability gateway + artifact metadata
  -> Workbench compatibility adapter

Child C: weekly three-article DAG
  existing weekly selector/builders + Child B governance
  -> durable static DAG -> existing immutable weekly aggregate
```

The parent contains no business service. It freezes cross-child boundaries, execution order and the final integration matrix.

## 2. Dependency order

1. IP retrieval V3 is implemented and committed independently.
2. Agent governance adds shared contracts and a Workbench adapter.
3. Weekly DAG consumes the committed governance contract and existing weekly artifact code.
4. Parent integration verifies migration chain, contract compatibility and privacy separation.

No two child implementations may concurrently edit migration head, `models.py`, OpenAPI or generated frontend types.

## 3. Cross-child contracts

- Retrieval telemetry is business aggregate data, not Agent trace data.
- Agent governance exposes typed domain/application interfaces; consumers never parse generic JSON event payloads.
- Weekly DAG stores only safe identities/checkpoints and references existing article artifacts; it never embeds article bodies or media bytes in trace rows.
- All version switches are explicit. V2 retrieval and current Workbench/weekly projections remain rollback-compatible.

## 4. Compatibility and rollout

- Each child introduces its own feature/config version and can be rolled back before the next child starts.
- Each child creates a migration from the actual current head and updates migration compatibility/Doctor in the same work commit.
- Existing public API schemas change additively or remain behind development-only resources.
- No deployment, provider call, production index rebuild or social side effect is part of the parent task.

## 5. Final integration gate

The parent passes only after all child work commits exist, task-local checks pass, the migration history is single-headed, the Workbench compatibility suite remains green, the weekly DAG consumes the shared governance implementation, and privacy scans prove IP aggregate metrics and Agent trace contain disjoint allowed fields.
