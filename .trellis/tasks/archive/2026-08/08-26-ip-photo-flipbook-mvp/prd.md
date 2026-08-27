# IP 图片翻页相册 MVP

## Goal

Let colleagues select existing Sai Xiansheng / Xiao Sai assets and turn them into an ordered,
responsive page-turning photo album inside the standalone IP asset site, without uploading the same
images again or leaving the current internal-library experience.

## Confirmed Facts

- The IP site is a React 19, TypeScript, Vite standalone application. It already gates
  `/ip-assets` and `/ip-assets/create` behind the demo login and does not mount them in the shared
  development console.
- The shared gallery already owns multi-select state, filters, favorites, ready-state eligibility,
  canonical names, safe preview URLs, and original image dimensions. The creation studio also owns
  an ordered image picker and source filters for all shared assets, favorites, uploads, and shared
  generated work.
- The reviewed `create-photo-flipbook-ui` repository is a Codex skill and React template, not a
  runtime service or drop-in website plugin. Its reusable renderer is based on `react-pageflip` and
  accepts an ordered page manifest with image URL, alt text, width, height, fit, padding, caption,
  and text.
- The external repository's structural validation and four renderer contract tests pass. Its
  bundled example uses Next/vinext/Cloudflare pieces that the IP site does not need.
- `react-pageflip@2.0.3` is MIT licensed and compatible with the current React application. The
  skill repository itself currently declares no license, so copying its source is not approved.

## Requirements

- Add a dedicated standalone album route under `/ip-assets`, protected by the existing feature flag
  and demo-login presentation gate and never mounted in the shared console.
- Let a user select two to twenty distinct ready shared IP assets from the existing gallery
  experience, then explicitly open the album builder. Reuse existing asset filters and favorite
  projections instead of creating a second asset-search contract. Selection may remain unbounded
  for the existing ZIP action, but the album action must explain and enforce its own 2–20 range.
- In the builder, show an editable local title and the selected order, allow reorder and removal,
  derive the first selected image as the cover, and keep meaningful alternative text from each
  canonical asset name.
- Render a responsive two-page desktop spread and a single-page mobile view with mouse, touch,
  previous/next buttons, and keyboard navigation. Provide visible page position, disabled states,
  reduced-motion behavior, and live feedback that does not rely only on animation or color.
- Use only safe resolved preview URLs and existing generated OpenAPI asset fields. Only `ready`
  shared assets may enter the album.
- Implement a project-native renderer around the MIT `react-pageflip` dependency. Do not copy the
  unlicensed external template, import its Next/vinext/Cloudflare runtime, or install the Codex skill
  as a production dependency.
- Keep the draft in application memory only. The ordered asset projection must not be placed in a
  query string, browser storage, database, or backend request. Refresh, tab close, direct route
  entry, and a missing/consumed draft return to a bounded recovery state that links back to the
  gallery.
- Do not invoke recognition, semantic search, download counting, or image-generation providers
  merely to build or view an album.

## Acceptance Criteria

- [x] From the shared IP gallery, a user can select an allowed number of ready images and activate a
      clearly labeled “制作翻页相册” action.
- [x] The album action accepts 2–20 ready shared images, while existing ZIP selection still works;
      fewer or more selections produce visible bounded guidance and no navigation.
- [x] The standalone album page receives only the in-memory safe asset projection, displays the
      selected images in explicit order, and allows title edit, reorder, and removal without
      mutating query-cache rows.
- [x] The first selected image acts as the cover; remaining images and any required blank/back-cover
      leaves render in deterministic order without stretching or unintended cropping.
- [x] Desktop, narrow-screen, mouse, touch, button, and keyboard navigation remain usable; current
      page and pending flip state are accessible, and reduced-motion preferences are respected.
- [x] Direct navigation without the demo marker shows the login page and restores only the safe
      album route; feature-disabled, refreshed, missing, consumed, or malformed drafts fail closed
      with a recovery link to the gallery.
- [x] Building and viewing the album creates no asset, generation job, provider request, download
      count, or other backend mutation.
- [x] Focused unit/component tests, accessibility checks, TypeScript, lint, formatting, dependency
      audit, production build, and one real browser smoke pass.

## Key Decisions

- The user approved an ephemeral preview MVP: no saved album, share link, or cross-refresh restore.
- The external skill is design/contract research only. The implementation is project-native and
  depends only on the MIT `react-pageflip` package.
- Two to twenty pages is the first-version album range. The first ordered image is the cover;
  reordering is also how a user changes the cover.
- Existing IP assets remain the only source of page images. Album building is not an AI operation.

## Out of Scope

- AI-generated album pages, generated captions, automatic layout planning, or modifying source
  images.
- PDF/video export, printing, background music, public Internet deployment, or social publishing.
- Replacing the gallery, creation studio, local profile, favorites, or existing download flow.
- Copying the external skill's unlicensed source verbatim.

## Completion Evidence

- Work commits: `0cb4698` (feature) and `c4278ce` (frontend contract).
- Independent verification passed ESLint, strict TypeScript, production build, dependency audit with
  zero vulnerabilities, and 222 frontend tests. Task-scoped Prettier and `git diff --check` passed;
  the only full-repository formatting failure belongs to an unrelated parallel official-account
  file.
- Real Chromium smoke selected three of 42 ready shared assets, built the album, edited the title,
  reordered the cover, turned pages by keyboard, verified the 390 px layout, and confirmed refresh
  returns to the recovery state without horizontal overflow or page errors.
- Database counts were identical before and after (`assets=45`, `jobs=5`, `queued/running=0`,
  `download_total=1`, `favorites=0`); no write request, Worker claim, or provider call occurred.
