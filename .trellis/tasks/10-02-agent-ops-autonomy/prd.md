# 运维 Agent 进阶：告警自动诊断、修复 Agent 作为子 Agent、MCP 进阶

## Source request (2026-10-02, owner)

Follow-up to 10-02-agent-upgrade. Asked which agent techniques would add real value; three were
recommended and approved: "请你处理".

Constraints: real use only, every part tested; no production change without the owner's explicit
confirmation; production data read-only through `edu_ai_ops_ro`; no paid model runs in slot hours
(06:00–08:30, 11:00–13:30, 17:00–19:30 CST); alerts never go to the formal delivery group.

## Part D — alert diagnosis agent (watchdog)

When the delivery watchdog finds a slot that did not go out as planned, a read-only diagnosis
agent investigates with the ops tools (slot runs, copy runs, a copy run's issues, deliveries, day
trace) and ends with one structured report through a `report_diagnosis` tool: failing stage
(selection / copy / image / delivery / unknown), a short cause, the run ids it relied on, and a
suggested action from a closed set (wait, rerun_copy, rerun_delivery, manual_review, none). It
never acts: any rerun is only a suggestion marked "needs approval". The report is appended to the
alert text and the JSONL record. Bounded rounds/calls; a model failure leaves the plain alert.
Traces use the same GenAI-convention spans as the ops assistant.

Acceptance: scripted-model tests (diagnosis, model failure, limits, no write tools offered);
synthetic failure scenarios (copy blocked, delivery stuck, selection short, all fine) scored on
stage and action; one paid run after 19:30.

## Part E — repair agent as a sub-agent of the ops assistant

The ops assistant gets a `delegate_repair` tool: it hands an opened draft and its blocking issues
to the copy repair agent (its own tool loop and limits) and gets back the proposed change set.
Nothing is applied until the operator approves the whole change set (the same interrupt approval);
a denial is reported back. Sub-agent steps appear as a nested `invoke_agent` span. Trajectory
scenarios cover delegation.

## Part F — MCP: Streamable HTTP with auth, resources, prompts, elicitation

The ops MCP server can also be served over Streamable HTTP on loopback with a bearer token
(refuses to start without one or on a non-loopback bind unless explicitly allowed). It exposes the
day trace as a resource (template by date), a few diagnosis prompts, and asks the client for
confirmation through elicitation before a draft edit in the repair MCP server (decline/cancel →
structured refusal). stdio stays as is.

Acceptance: in-process client tests for HTTP auth (missing/wrong token refused), resources,
prompts, elicitation accept/decline/unsupported client.
