# Agent Workbench real portfolio evidence — implementation result

## Frozen baseline

- Source HEAD: `f5cd8de936a57dfd61c01101b7cb2a2412b2eb25`
- Workbench OpenAPI SHA-256:
  `dadf04e138d390940d42b48ad025eedd9f281c4f1b3294f04e8cace821808ad3`
- Canonical 42-case report SHA-256:
  `654378a55837dad6f8cdb986af00c3d24f203e8ad58bf4723270166b02879788`
- Existing checked design-fixture screenshot SHA-256:
  `85e9712e58500154931d7d7fefa4718314b083e0bce5b0a81602b544665b819c`
- Unrelated user changes under `reports/**` and the separate 08-18 task were preserved and excluded.

## Deterministic real-run evidence

- Capture: `docs/portfolio/runs/agent-workbench/f5cd8de936a5-20260818T063838Z/`
- Captured UTC: `2026-08-18T06:38:38Z`
- Manifest SHA-256:
  `13f3147d90a955f282c7b7abe8a220ca001c85a8dc3ee3d9efbc956e51229f74`
- Stable overview SHA-256:
  `a62e617947a9c1de290fa822c6852c23a0573bfee1384eefde6c2e302fef3352`
- Three browser-linked JSON/screenshot runs and three direct HTTP probes passed exact
  terminal/tool/citation/claim/step semantic comparison.
- Multi-tool: `completed`, 4 model decisions, 3 read-only tools, 2 citations, 11 trace steps.
- Copy validation: `completed`, 2 model decisions, 1 `validate_copy`, 0 citations, 5 trace steps.
- Safety refusal: `refused`, 1 model decision, 0 tools, 0 citations, 2 trace steps.
- Playwright observed one POST per case to `127.0.0.1:8010`; API interception is `none` and service
  workers were blocked. Both `8010` and `5173` were released after capture.

## Live Zhipu boundary

Implementation and tests were ready, and the main/root session executed the single authorized
command once:

```bash
make agent-portfolio-live-zhipu-preflight
make agent-portfolio-live-zhipu-capture
```

The attempt started at `2026-08-18T06:41:06Z` and returned
`real browser capture failed before evidence verification`. It was not rerun. The reserved output
contains only a safe attempt ledger/failure projection; no typed response or screenshot was
preserved, so terminal, tool, provider/model, usage, and latency fields remain unverified and are
not used as portfolio evidence. Uvicorn/Vite/Playwright cleanup passed, both loopback ports were
released, and configured-credential plus generic private-path scans passed.

## Verification status

- Independent Trellis review self-fixed three capture-tooling gaps: verification now recomputes
  typed response/probe/network/summary/overview semantics and confines every artifact to its own
  capture directory; the authorized live command accepts only the official Zhipu API root and
  hides validation inputs/credentials; the Playwright child now has a 120-second deadline and
  explicit process-group teardown on timeout or interruption.
- Focused capture harness and checked-ledger tests: 22 passed.
- Deterministic real loopback capture and artifact verification: passed.
- Canonical deterministic eval: 42/42 passed; canonical report and registry hash stayed stable.
- Focused backend Agent/API/model/MCP/capture tests: 81 passed.
- Focused frontend Workbench/App tests: 70 passed.
- Full frontend gate: OpenAPI drift, Prettier, ESLint, strict TypeScript, 112 tests, and production
  Vite build passed.
- Backend formatting, Ruff lint, and strict mypy across 170 source files passed.
- Full backend suite: 1,052 passed with no provider/live execution.
- Production build with the Workbench flag set contained no Workbench title, route, action, or
  component marker. Production OpenAPI, Workbench OpenAPI, `api_main`, Dockerfile, and Compose were
  unchanged.
- Deterministic manifest hashes/relative paths, Markdown links, configured-credential scan,
  generic private-path scan, PNG metadata scan, and `git diff --check` passed.
- Remaining external action: none. GitHub push, Pages, deployment, production DB/WeCom, and another
  live provider call remain explicitly out of scope.
