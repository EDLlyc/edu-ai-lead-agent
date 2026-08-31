# Current-state evidence

- `backend/app/domain/agent_workbench.py:54-90` defines current model-turn, tool-call, timeout, input/result/trace byte and graph recursion limits.
- `backend/app/domain/agent_workbench.py:158-229` defines linear trace entries, usage and run validation, but no task/agent/event causal identity.
- `backend/app/application/services/agent_tools.py:68-90` rejects non-read-only or open-world Workbench tools and validates tool definitions before execution.
- `backend/app/agent_mcp_main.py:45,131` projects the exact four bounded read-only registry tools through MCP.
- `.trellis/spec/backend/agent-workbench.md` requires loopback-only execution, at most four calls, safe citations, bounded timelines and no raw model/tool persistence.
- Existing governance/copy/IP workers demonstrate leases, fencing, idempotent jobs and PostgreSQL integration; none currently provides a reusable Agent parent-budget ledger.

## Planning consequence

The first version must add a sibling shared governance core and adapters. It must not replace the Workbench public schema or reinterpret its deterministic fixture metrics. Weekly DAG is the first new durable consumer; IP anonymous telemetry is explicitly not a consumer.
