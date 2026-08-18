# Public Agent Portfolio Evidence

## Repository state (refreshed 2026-08-18)

- Codeup `origin` remains the authoritative write source. GitHub is a one-way backup destination and must never trigger production.
- Public GitHub `EDLlyc/edu-ai-lead-agent` still resolves to `main=4148acb581434c07ae1c08398c94e879acf00ef9`.
- Local `HEAD=f5cd8de936a57dfd61c01101b7cb2a2412b2eb25` is 69 commits ahead of the public GitHub branch and 12 commits ahead of Codeup `origin/main=cf4e429c037e18d2ef71dc71d5d4a93bbf90404b`.
- The public GitHub tree contains no `agent_workbench`, `agent_mcp`, `backend/evals/agent_workbench`, or `docs/portfolio` paths; a recruiter cannot currently inspect the completed Workbench.
- The Workbench itself is one coherent feature commit, `b886a06 feat(workbench): add local agent research portfolio`, containing the bounded runner, typed registry, MCP, eval, API, UI, tests, docs, and screenshot.
- Re-running `make agent-portfolio-check` on local `main` passes:
  - deterministic eval 42/42;
  - 59 focused backend Agent tests;
  - 66 frontend feature/App tests;
  - Agent OpenAPI and generated TypeScript drift checks.

## Prospective public-tree baseline

- `deploy/release/release_tool.py scan-committed-secrets` passes for all 1032 scanner-eligible files at local commit `f5cd8de936a57dfd61c01101b7cb2a2412b2eb25`.
- The largest committed object is a 2.7 MiB portfolio/report PDF; there is no GitHub 100 MiB object blocker in the current tree.
- The release scanner is necessary but not sufficient for publication. A dedicated portfolio audit must additionally inspect:
  - personal names/contact details and teacher/client identifiers;
  - internal hostnames, server aliases and private filesystem paths;
  - report/document text extracted from PDF/DOCX, not only raw bytes;
  - screenshots and image metadata;
  - authenticated URLs, fixture credentials and secret-shaped test literals;
  - ignored and untracked files to prove they are not part of the push.
- The exact public candidate must be the committed Codeup-derived tree after portfolio changes, not an uncommitted workspace snapshot.

## Existing reusable seams

- `make agent-portfolio-check` is the canonical fixture-only gate and already avoids production DB/provider calls.
- `PY_RUN` is overridable, so GitHub Actions can install the hash-pinned dev lock and invoke `make PY_RUN=python agent-portfolio-check` without Conda.
- `docs/portfolio/agent-workbench.md`, the checked screenshot, OpenAPI, generated TS schema, cases, and canonical report already provide the source material for a public landing page.
- The React workbench uses the real generated contract and supports fixture mode. A public static page may render checked fixture trace data, but must be labeled as a replay; the real interactive API remains a local loopback demo.
- The current UI screenshot generator is provider/database/network-free and can be reused for a short demo capture pipeline.
- Yunxiao already defines one-way GitHub backup semantics. GitHub Actions must remain independent: read-only CI and Pages are allowed, but no workflow may push Codeup, build/push production images, or deploy production.

## Recommended public architecture

1. **Root recruiter entry**: concise bilingual summary, inline screenshot, architecture, verified metrics, honest limits, three-minute review path.
2. **Static Pages artifact**: generated only from committed, sanitized fixture/canonical data; no API keys, remote model, production backend, or business mutation. It is a portfolio replay, not the live Workbench.
3. **Local one-command demo**: reuse the independent loopback API and real UI in deterministic fixture mode. Add orchestration/cleanup so one command starts both and one command stops them; keep current two-terminal commands as low-level fallbacks.
4. **Read-only public CI**: `permissions: contents: read`; no secrets; setup pinned Python/Node; hash-pinned Python lock + `npm ci`; run the canonical portfolio gate. Pages deployment is a separate least-privilege workflow and requires explicit repository configuration/approval.
5. **Live-model eval track**: provider-neutral and opt-in, outputs a separate non-canonical report with model identity, repeat count, latency/token/cost diagnostics, failure taxonomy and raw-provider-body exclusion. CI never runs it. Paid execution remains a later explicit authorization gate.
6. **Publication gate**: compare exact Codeup/local/GitHub SHAs; scan the full prospective tree and extracted documents; verify Pages/CI workflows contain no privileged trigger; present exact push refspec and commit for user approval.

## External references

- GitHub Docs: repository README should explain why a project is useful and how to use it.
- GitHub Pages custom workflows publish a prebuilt artifact through `actions/upload-pages-artifact` and `actions/deploy-pages`; deployment requires explicit `pages: write` and `id-token: write`, so it must be separate from the read-only CI job.
- GitHub recommends adding a recognizable open-source license when others should be allowed to use, modify and distribute the code. License choice remains a user-owned legal/product decision.
- Current Agent internships emphasize LangGraph, Function Calling, MCP/A2A, evaluation, FastAPI/database and full-stack visualization. The existing Workbench already covers most application-engineering requirements; public evidence and live-model evaluation are the highest-value gaps.
