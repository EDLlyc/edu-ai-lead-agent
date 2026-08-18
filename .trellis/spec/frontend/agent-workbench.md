# Local Agent Workbench UI

## Scenario: Development-only recruiter trace surface

### 1. Scope / Trigger

Use this contract for the local Agent Workbench panel. It visualizes one ephemeral deterministic or
explicitly local run; it is not a production business screen and must expose no publish, send,
enqueue, retry, or server-management action.

### 2. Signatures

- Feature: `frontend/src/features/agent-workbench/`.
- Wire source: `backend/openapi.agent-workbench.json` ->
  `frontend/src/lib/api/generated/agent-workbench-schema.d.ts`.
- API origin: exactly `http://127.0.0.1:8010`.
- UI opt-in: Vite development mode plus `VITE_AGENT_WORKBENCH_ENABLED=true`.
- Launcher: `make agent-workbench-ui` binds Vite to `127.0.0.1:5173` with `--strictPort`.

### 3. Contracts

- `api.ts` maps generated wire types to readonly view models; do not handwrite duplicate response
  interfaces or render transport objects directly.
- The UI supports idle, running, completed, refused, budget-exhausted, failed, and cancelled states.
- Claims render their own citation IDs; the visible citation catalog contains only entries used by
  claims. Links require the same public-HTTPS policy as the backend and otherwise render as text.
- Trace renders safe action/observation labels, tool/result status, counts, latency, and usage. It
  does not invent or display chain-of-thought, prompts, provider bodies, private paths, or secrets.
- Untrusted/model/source content is text only. Do not use `dangerouslySetInnerHTML`.
- The App uses a development-only lazy import. A production Vite build must contain no workbench
  navigation, title, route, panel marker, or runnable workbench chunk even if the flag is set.
- The stable design screenshot is generated from sanitized fixture data without
  backend/provider/network access and must be labeled as a checked fixture render, not a real run.
- Recruiter-facing runtime screenshots use the same development-only panel against real loopback
  Uvicorn and Vite processes. Playwright must type the checked case query and observe the actual
  POST to exact `127.0.0.1:8010`; route interception, response fulfillment, service workers, and a
  parallel trace renderer are forbidden. The saved typed JSON and screenshot share the browser run
  ID; a separate deterministic API probe may differ only in dynamic IDs/latency.

### 4. Validation & Error Matrix

| Condition | Required UI result |
|---|---|
| Production build or flag absent | Feature import/navigation absent |
| API base is not exact loopback HTTP port 8010 | Configuration rejects startup/use |
| Completed run | Show summary, claims, claim-bound citations, trace, and metrics |
| Refused/budget/failed/cancelled run | Explicit text status and safe guidance; no stale success |
| Unsafe citation URL | No clickable external link |
| Unknown safe backend code | Stable fallback label; do not expose exception text |
| New request cancels/obsoletes old request | Old response cannot replace current view |
| Reduced motion or keyboard-only use | No required motion; focus and announcements remain usable |

### 5. Good / Base / Bad Cases

- Good: a recruiter follows query -> selected tool -> bounded observation -> cited answer in one
  keyboard-accessible rail and can reproduce the fixture result locally.
- Base: a refusal explains evidence insufficiency and displays no orphan citations.
- Bad: importing the feature eagerly in production, accepting `localhost`/arbitrary API origins,
  rendering Markdown as HTML, presenting color-only status, or adding a “send/publish” button.

### 6. Tests Required

- Config/feature-flag tests reject every origin except exact loopback port 8010 and prove default
  absence plus local opt-in.
- API mapper/hook tests cover success, unknown code, stale response, cancellation, malicious text,
  unsafe URL, optional usage, and generated-contract consumption.
- Component tests cover all terminal states, claim/citation binding, trace/metrics, keyboard focus,
  aria-live, 44px targets, reduced motion, and axe checks.
- `make frontend-check` must pass both production and workbench OpenAPI drift, Prettier, ESLint,
  strict TypeScript, full Vitest, and production build.
- A production build with the workbench flag set must still prove the feature markers/chunk absent.
- The design-fixture screenshot remains network-free. Real evidence capture must use the actual
  generated-contract client and loopback API, prove exactly one browser POST per case, strip image
  metadata, and pass hash/link/privacy review.

### 7. Wrong vs Correct

#### Wrong

```tsx
import { AgentWorkbenchPanel } from "@/features/agent-workbench/AgentWorkbenchPanel";

return <AgentWorkbenchPanel />;
```

This ships the portfolio surface in the normal production bundle.

#### Correct

```tsx
const enabled = import.meta.env.DEV && isAgentWorkbenchEnabled(import.meta.env);
const AgentWorkbenchPanel = enabled
  ? lazy(() => import("@/features/agent-workbench/AgentWorkbenchPanel"))
  : null;
```

Keep the import behind both compile-time development mode and the explicit local feature flag.
