# Agent 能力升级：修复 Agent 上线、LangGraph 人工审批、轨迹评测

## Source request (2026-10-02, owner)

Resume review found the agent work thin: the tool-using repair agent only runs in shadow (1 valid
case so far, blocked drafts are rare), the ops assistant is a local tool with its own approval
loop, and the copy pipeline's LangGraph graph has a single node. Owner: "好的，请你处理，如果技术上
需要提升，也请你处理，我找的是agent实习，agent的新鲜技术要多用。"

Principle: only real, tested, measurable changes; no technique added just for the name. Production
deploys still need the owner's explicit confirmation; no paid model runs in slot hours
(06:00–08:30, 11:00–13:30, 17:00–19:30 CST); production DB access stays read-only.

## Part A — repair agent online: agent first, full regeneration as fallback

Today a blocked draft 1 gets one full regeneration (draft 2). Change, behind
`COPY_REPAIR_MODE` (`regenerate` default | `agent_first`):

1. Draft 1 blocked by rules or the auditor → the repair agent edits a workspace copy of draft 1
   (bounded rounds and calls, exact-quote tools, scoped to the flagged claims/hook).
2. The agent's draft goes through the same gate in memory: deterministic rules, then the run's
   auditor and audit policy.
3. Accepted → persisted as draft 2 (`repair_of` = draft 1) with its audit; run accepted,
   `repair_count=1`, repair method `agent`.
4. Not accepted, agent error, or limits hit → nothing persisted from the agent; today's full
   regeneration runs as draft 2 exactly as now. The agent attempt (stop reason, rounds, tool
   calls, tokens, issue codes left) is kept in the run's safe metadata.

Acceptance: unit/integration tests for accept, fallback (gate fails, agent raises, provider
error), idempotent re-entry (draft 2 exists → no agent call), default mode unchanged; gate PASS;
offline replay of the shadow/eval cases shows the same accept decisions as the shadow gate.

## Part B — ops assistant on LangGraph with durable human approval

Rebuild the ops assistant loop as a LangGraph `StateGraph` (model node → tool node → loop) using
the same tool registry. Draft edits call `interrupt()` with a before/after preview; the operator
resumes with `Command(resume=...)`. A checkpointer (`AsyncPostgresSaver` on the local DB, in-memory
in tests) keeps each conversation as a thread, so a pending approval survives a restart and the
state history is an audit trail. Read tools still run at once; limits and context trimming stay.

Acceptance: tests with a scripted model for read → answer, edit → interrupt → approve/deny →
resume, restart between interrupt and resume (new graph, same checkpointer), limits.

## Part C — trajectory evaluation and step traces

- A scenario set for the ops assistant on fixture data (deterministic reader): expected tools,
  forbidden tools, facts the answer must contain, whether an approval must be requested.
- Metrics per model: task success, tool selection precision/recall, invalid-argument calls,
  rounds and tokens, approval-policy violations (an edit applied without approval must be 0).
- Each agent step is recorded with OpenTelemetry GenAI semantic-convention names
  (`invoke_agent` / `chat` / `execute_tool`, `gen_ai.usage.*`, `gen_ai.tool.name`); exported to
  OTLP when an SDK is configured, otherwise to JSONL.

Acceptance: deterministic tests for the scorers; one paid run outside slot hours with a report.

## Rollout

Part A ships as an overlay on the running image with `COPY_REPAIR_MODE=agent_first` in `.env`,
after the owner confirms. Parts B and C are local tools and evals; no production change.
