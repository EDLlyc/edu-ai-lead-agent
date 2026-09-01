# Frontend Development Guidelines

## Status and source of truth

These documents are the implementation contract for the internal SPA. The repository now contains
an accessible brand-knowledge workspace and an internal material-package review workspace in
[`frontend/src/app/App.tsx`](../../../frontend/src/app/App.tsx) with generated API consumption,
multipart upload, status polling, activation/deactivation, and internal generation-context
diagnostics. The material workspace supports queued image generation, evidence and brand-binding
inspection, validation/audit display, copying text, image download, and safe JSON package download.
The contracts
are aligned with the editable
[`main.tex`](../../../main.tex) source and generated
[`技术报告-v0.3.pdf`](../../../技术报告-v0.3.pdf), version 0.3. The bootstrap decision record at
`.trellis/tasks/archive/2026-07/00-bootstrap-guidelines/research/technical-report-decisions.md`
preserves the version 0.2 starting decisions as historical context; version 0.3 and these specs
control where the old report differs. Material packages are implemented as a manual-use workflow;
automated social publishing remains prohibited.

The SPA also contains a date-oriented three-slot content-edition board. It consumes only the
generated `ContentEditionResponse`, always renders morning/noon/evening in stable order, and shows
disabled, missing, preparing, empty/unfilled, ready, failed, expired, delivered and unknown states
per independent item. It links to safe source and material-package resources, keeps polling in the
server-state hook only while enabled slots are incomplete, and provides no publishing controls.

The SPA additionally contains a feature-flagged IP digital-asset hub for one backend-unauthenticated
company intranet library. A versioned, tab-scoped presentation gate provides a local demo login page
without claiming verified identity or API protection. The hub supports controlled upload, cursor
browsing, multimodal/metadata search, verified preview/download, bounded ZIP selection, and optional
generation-to-library job polling.

React, TypeScript strict mode, Vite, TanStack Query, and generated OpenAPI types are implemented.

## Guidelines index

| Guide | Scope |
|---|---|
| [Directory Structure](./directory-structure.md) | Feature ownership, shared UI, app shell, and generated API code |
| [Component Guidelines](./component-guidelines.md) | Composition, props, styling, material-package UX, and accessibility |
| [Hook Guidelines](./hook-guidelines.md) | Custom hooks, TanStack Query, mutations, and browser effects |
| [State Management](./state-management.md) | Server, local, URL, and narrowly shared client state |
| [Type Safety](./type-safety.md) | Strict TypeScript, generated OpenAPI types, and runtime boundaries |
| [Local Agent Workbench UI](./agent-workbench.md) | Development-only generated-contract trace UI, safe citations, accessibility, and production tree-shaking |
| [Official-Account Editor Handoff](./official-account-editor-handoff.md) | Development-only approved-run gates, Xiaosai preview, rich clipboard, local downloads, and permanent no-publish truth |
| [Quality Guidelines](./quality-guidelines.md) | Tests, accessibility, generated-contract drift, and review gates |
| [Brand Knowledge Workspace](./brand-knowledge-workspace.md) | Implemented upload, status, activation, generation-context diagnostics, generated types, accessibility, and manual-only boundary |
| [IP Digital Asset Hub UI](./ip-asset-hub.md) | No-auth intranet gallery, upload, multimodal search, download, generation, accessibility, and safe resource URL contracts |

## Non-negotiable product boundaries

- The primary interface is an accessible internal material-package review and reuse experience.
- Show source links and generation/audit status rather than hiding provenance.
- Support copying text and downloading images with keyboard-accessible feedback.
- Show queued/running/failed/review-required package and image states without implying readiness.
- Show topic explanation, source/evidence bindings, brand bindings, validation, audit issues, and
  package version snapshots through the typed material mapper.
- Keep server state in the server-state client and ephemeral interaction state local.
- Generate API types from FastAPI OpenAPI; do not hand-maintain duplicate wire interfaces.
- Do not expose automated social publishing, social credentials, or misleading “publish” actions.

**Documentation language:** English.
