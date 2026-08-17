# Agent Workbench offline evaluation

This feature is the reproducible backend evidence for the local Agent Research Workbench. It grades
the fixed deterministic policy against the same canonical, read-only tool registry used by the
bounded Agent runner and the stdio MCP adapter. It never calls a provider, opens a network listener,
writes business data, or reads an evaluation oracle inside the policy.

## Architecture and boundaries

```text
cases.v1.jsonl ------------------------> deterministic grader
                                               ^
query only -> deterministic policy -> bounded runner -> TypedToolRegistry
                                                    |-> fixture evidence/event reader
                                                    |-> fixture brand reader
                                                    `-> existing deterministic copy validator

TypedToolRegistry -> app.agent_mcp_main -> MCP v2 stdio only
```

The JSONL loader keeps the oracle on the evaluator side. Only `query`, `fixture_scenario`, and the
normal fixture-backed application composition are used to run a case. Required tools, argument
constraints, expected citations, terminal class, and safety assertions are not passed to the model
adapter.

The fixture corpus uses synthetic UUIDs, an `example.edu.cn` URL, and short sanitized excerpts. It
contains no production identifiers, private brand documents, credentials, provider payloads, or
object-storage locations.

## Local commands

From the repository root, after installing the hash-locked backend development environment:

```bash
make agent-workbench-eval
make agent-portfolio-check
python -m app.agent_mcp_main
```

The first command runs the offline baseline and writes only volatile timing/token diagnostics below
the ignored `output/agent-workbench/` directory. The portfolio check additionally verifies canonical
report drift plus the focused backend and frontend contracts. Its direct evaluator equivalent is
`(cd backend && python -m evals.agent_workbench.runner --check)`. The MCP command reserves stdout for
protocol frames and supports stdio only; it rejects production and non-fixture provider configuration
before startup.

Use `--write-canonical` only when an intentional registry, dataset, policy, or evaluator contract
change has been reviewed. Canonical reports exclude timestamps, random run IDs, wall-clock latency,
and token counts so two equivalent runs are byte-stable.

## Dataset contract

`cases.v1.jsonl` contains at least 40 cases and at least six cases in every required category:

1. governed evidence search;
2. event detail;
3. brand-context retrieval and fact/brand separation;
4. deterministic copy validation;
5. multi-tool synthesis;
6. insufficient evidence, injection, side-effect, and unsupported-tool refusal.

Cases declare required, allowed, and forbidden tools; constraints over the trace's allowlisted
argument summary; allowed citation IDs; required fact IDs; an expected terminal class; a four-step
maximum; and explicit safety assertions. They deliberately do not contain an exact answer string or
recorded model turns.

## Deterministic metrics

The checked report includes:

- task success and failed case IDs overall and by category;
- exact tool-set rate plus tool-selection precision and recall;
- valid argument rate and unknown-tool count;
- claim-level citation precision and required-fact coverage;
- unsupported external-claim rate and brand-as-fact checks;
- refusal precision, recall, and accuracy;
- terminal accuracy and mean/P50/P95 model-step counts.

The ignored runtime diagnostic includes wall-clock P50/P95 latency and input/output/reasoning token
counts when the typed runner supplies them. Those values are operational observations, not canonical
drift inputs.

## What the score means

The deterministic baseline is authoritative for schema enforcement, read-only allowlisting,
budgeting, trace/citation invariants, evaluator reproducibility, and the behavior of this fixed
policy on the checked fixtures. It is **not** evidence of live LLM intelligence, provider quality,
production MCP deployment, autonomous browsing, or publishing capability. An optional live-model
track would require a separate explicit local opt-in and must remain non-blocking and uncommitted.
