# Frontend Development Guidelines

## Status and source of truth

These documents are the initial implementation contract for a greenfield internal SPA. They are
derived from `技术报告.pdf` version 0.2 and the bootstrap decision record at
`.trellis/tasks/00-bootstrap-guidelines/research/technical-report-decisions.md`; no frontend
application exists yet.

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
