# Frontend Development Guidelines

## Status and source of truth

These documents are the initial implementation contract for a greenfield internal SPA. The
repository now contains an accessible environment-verification shell in
[`frontend/src/app/App.tsx`](../../../frontend/src/app/App.tsx), but no material-package feature or
product API consumption. The contracts are aligned with the editable
[`main.tex`](../../../main.tex) source and generated
[`技术报告-v0.3.pdf`](../../../技术报告-v0.3.pdf), version 0.3. The bootstrap decision record at
`.trellis/tasks/archive/2026-07/00-bootstrap-guidelines/research/technical-report-decisions.md`
preserves the version 0.2 starting decisions as historical context; version 0.3 and these specs
control where the old report differs. Rules for material packages remain the target for the first
product vertical slice.

The first vertical slice targets React, TypeScript in strict mode, and Vite. It must update these
guides with real component, hook, generated-client, and test paths after implementation. A task
that changes an initial default must record the decision before editing the specs.

## Guidelines index

| Guide | Scope |
|---|---|
| [Directory Structure](./directory-structure.md) | Feature ownership, shared UI, app shell, and generated API code |
| [Component Guidelines](./component-guidelines.md) | Composition, props, styling, material-package UX, and accessibility |
| [Hook Guidelines](./hook-guidelines.md) | Custom hooks, TanStack Query, mutations, and browser effects |
| [State Management](./state-management.md) | Server, local, URL, and narrowly shared client state |
| [Type Safety](./type-safety.md) | Strict TypeScript, generated OpenAPI types, and runtime boundaries |
| [Quality Guidelines](./quality-guidelines.md) | Tests, accessibility, generated-contract drift, and review gates |

## Non-negotiable product boundaries

- The primary interface is an accessible internal material-package review and reuse experience.
- Show source links and generation/audit status rather than hiding provenance.
- Support copying text and downloading images with keyboard-accessible feedback.
- Keep server state in the server-state client and ephemeral interaction state local.
- Generate API types from FastAPI OpenAPI; do not hand-maintain duplicate wire interfaces.
- Do not expose automated social publishing, social credentials, or misleading “publish” actions.

**Documentation language:** English.
