# IP 创作交互反馈与素材筛选

## Goal

Make the IP creation studio feel responsive and trustworthy: every meaningful click should produce
visible, accessible feedback, reference selection should be obvious, and colleagues should be able
to narrow eligible creative references by shared library, favorites, their uploads, or their shared
AI outputs without weakening the existing personal-material boundary.

## Background and Confirmed Facts

- The generation path is real and currently configured for `comfly` with `gpt-image-2`. The API
  reports generation available, the database contains a succeeded generation, and the current
  preview also has one queued job.
- API availability proves provider configuration, not that the separately deployed generation
  worker is currently online. The local preview launched API and Vite only, so the queued job has no
  active consumer. This task must explain queue semantics honestly and must not invent worker
  liveness or percentage progress.
- The studio currently polls queued/running jobs every two seconds and stops at terminal state. It
  renders a textual output state, but most interaction announcements are visually hidden and only
  the pressed button—not the whole asset card—shows reference selection.
- The shared gallery already projects the current profile's favorite state. The personal endpoint
  already supports `favorite`, `uploaded`, and `generated` sources with cursor pagination. No new
  database table or API route is required for the requested filters.
- Generation references remain limited to one to three distinct `ready`, shared assets. A current
  profile's unshared/private generation is intentionally not eligible in this iteration.

## Requirements

### R1 — Honest generation feedback

- Distinguish waiting-for-input, submitting, queued, running, succeeded, failed, and status-read
  error states in visible text and non-color-only styling.
- Immediately acknowledge a successful enqueue. Queued copy must say that the request is stored and
  is waiting for the independent background generation service; it must not claim that the model is
  already running.
- Running copy may say that the model is generating. Do not display fake percentages, estimated
  completion times, provider request IDs, credentials, or raw provider errors.
- Explain near the generation action that “generation available” means the model interface is
  configured and jobs are processed by an independent worker. Do not add a false online indicator.
- Keep the existing idempotent retry and terminal polling behavior. Generation-disabled mode must
  leave reference filtering, personal shelves, favorites, and downloads usable.

### R2 — Visible and accessible click feedback

- Adding a reference immediately marks the entire card as selected, shows its `01`–`03` ordinal and
  a check/text indicator, updates the filmstrip, and produces a visible `aria-live` confirmation.
- Removing or reordering a reference, switching a material source, favoriting/unfavoriting, sharing,
  downloading, and submitting generation must each produce an appropriate visible response.
- When three references are selected, further add controls remain disabled and the page explains
  the three-reference limit; existing remove/reorder actions remain available.
- Buttons have a restrained pressed/loading response and selected cards have a clear border/surface
  change. Motion is decorative only and must be disabled under `prefers-reduced-motion`.
- Feedback must not rely only on color, animation, or a toast that assistive technology cannot read.

### R3 — Reference-source filters

- Add a compact, keyboard-accessible source filter above “选择创作素材” with these options:
  `全部素材`, `我的收藏`, `我的上传`, and `我的共享 AI 作品`.
- `全部素材` continues to use the shared gallery query. Profile-scoped filters use the existing
  personal collection endpoint and show only assets that are both `ready` and shared.
- Choosing a profile-scoped filter without a valid browser-local profile opens the existing honest
  profile setup dialog and does not invent an empty token or silently change the active filter.
- The text search applies to the active source. Search/filter changes never clear already selected
  references; a selected reference may remain in the filmstrip even when hidden by the current
  filter.
- Show explicit loading, empty, error, and load-more states for the active source. Empty personal
  filters explain that only shared, generation-eligible assets are shown.
- Favorite mutations must refresh both the active filter and the rest of the feature caches without
  placing the raw profile token in query keys, URLs, logs, or visible output.

### R4 — Compatibility and verification

- Preserve the dedicated `/ip-assets/create` route, the shared-console isolation, existing teal/clay
  editorial layout, responsive behavior, profile boundary, safe previews, ordered 1–3 references,
  private-by-default outputs, and explicit sharing.
- Add component/hook coverage for each filter, profile gating, visible feedback, selected-card
  ordinals, selection persistence across filters, three-item limit guidance, honest queued/running
  wording, pagination, failure states, accessibility, and reduced motion.
- Perform a local browser smoke with controlled/no-cost job status. Do not start the real worker or
  invoke the provider without separate explicit authorization.

## Acceptance Criteria

- [x] AC1: every reference add/remove/reorder and favorite/filter/generation action has immediate
      visible feedback and an accessible announcement.
- [x] AC2: selected reference cards visibly carry their stable `01`–`03` order, and a fourth
      reference is disabled with an explicit limit explanation.
- [x] AC3: the picker switches among all, current-profile favorites, uploads, and shared AI outputs;
      every displayed candidate is shared and ready.
- [x] AC4: profile-scoped filters gate through the existing local-profile dialog and never expose or
      query-key the raw token.
- [x] AC5: text filtering and cursor load-more work in the active source while selections survive
      source/search changes.
- [x] AC6: queued output says it is durably waiting for the independent background service; running
      output says generation has started; no fake worker-online or percentage claim appears.
- [x] AC7: succeeded/failed/status-error/disabled states remain terminally correct, and unchanged
      submit retries retain their idempotency key.
- [x] AC8: focused frontend tests, strict TypeScript, lint/format, accessibility checks, production
      build, relevant contract checks, and local browser smoke pass without a real provider call.

## Out of Scope

- Starting or supervising the real generation worker, spending provider credits, or processing the
  currently queued job.
- Worker heartbeat/liveness infrastructure, queue position, progress percentages, duration
  estimates, cancellation, retry controls, or an operations dashboard.
- Using private/unshared assets as generation references, changing backend access rules, or adding a
  new API/schema/migration.
- New taxonomy facets, folders, batch generation, image editing, prompt history, or authentication.
