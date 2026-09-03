# Agent retrieval live paired A/B

This opt-in, development-only compatibility canary compares the existing Agent with two reader
compositions:

- `raw_query`: the current `PostgresAgentKnowledgeReader`;
- `rewrite_rrf_rerank`: the current `EnhancedAgentKnowledgeReader` with one Zhipu rewrite,
  weighted RRF, and one Zhipu rerank.

The Agent model, temperature, prompt, typed registry, PostgreSQL snapshot, Alibaba multimodal brand
embedding identity, run limits, and twelve Codex-Seed questions remain fixed. The four copy/safety
cases are negative controls; only the eight evidence/event/brand/multi-tool cases enter retrieval
uplift metrics.

## Safety boundary

- Run commands from the repository root so `.env` resolves consistently.
- `preflight` reads PostgreSQL in a repeatable-read, read-only transaction and makes zero provider
  calls. It freezes private dataset/oracle artifacts below ignored `output/evals/agent-retrieval-ab`.
- `live` requires the exact v3 compatibility acknowledgement and a preflight-bound v3 manifest. It
  rejects dataset, database, registry, provider, or source drift.
- The frozen evaluation design still contains 12 cases × 2 arms × 3 repetitions, but this v3
  authorization executes exactly the first paired A/B canary only. Its hard boundary is 2 Agent
  attempts, 8 Agent decisions, and at most 4 planner, reranker, or Alibaba embedding requests.
- Each attempt preserves the production-consistent four model turns and four tool calls. Scheduled
  cells 1-2 are one mandatory A/B compatibility pair. The runner stops after cell 2 whether the pair
  passes or fails; it never continues the remaining 70 cells under this authorization.
- Each evidence/brand namespace freezes at most three qrels, so the strict `Recall@3 == 1` canary is
  attainable rather than structurally impossible.
- Any failed canary is recorded without a retry. A passed canary remains compatibility evidence
  only; neither outcome can support a retrieval-uplift claim.
- Attempts are invoked once. Existing attempt files block reruns; an ambiguous executor failure
  records a terminal failure and stops the remaining schedule.
- No server, publisher, crawler, migration, or business write path is imported by this package.

## Commands

```bash
make agent-retrieval-live-ab-preflight \
  OUTPUT=output/evals/agent-retrieval-ab/agent-ab-YYYYMMDD \
  RUN_REF=agent-ab-YYYYMMDD VALID_ON=2026-09-02

make agent-retrieval-live-ab-run \
  OUTPUT=output/evals/agent-retrieval-ab/agent-ab-YYYYMMDD \
  ACKNOWLEDGEMENT=I_AUTHORIZE_AGENT_RETRIEVAL_COMPATIBILITY_CANARY_V3
```

Every authorization revision uses a new run directory and manifest. The incomplete v1 and v2
evidence is immutable and must never be resumed, converted, or overwritten by v3.

The private dataset, oracle, and per-attempt ledgers may contain local identifiers and must not be
committed. `metrics.json` and `paired-report.md` are aggregate-safe projections, but remain local
evidence until explicitly reviewed. The report always states that labels are Codex Seed, the sample
is exploratory, and monetary cost is unknown without a separately frozen price sheet.
