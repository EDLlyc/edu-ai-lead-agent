# Local creation comparison verification

## Scope

The first roadshow improvement only: existing studio at `/ip-assets/create`, with a
submission-bound reference → brief → output spread and original-image enlargement.
No backend, OpenAPI, provider, deployment, publishing, or sharing behavior is added.

## Browser evidence

`capture-comparison.mjs` reads the latest successful generation from the local PostgreSQL
container and reads its reference/output originals from the local MinIO container. Original
lengths and SHA-256 hashes are checked against persisted metadata before browser use.

- Source task: `ipg_beb012e405484b7f8ae1`, created 2026-08-27.
- The original request asks for a suit, tie and leather shoes; the actual reference and
  generated output are kept together. Nothing is newly generated for this verification.
- API transport and browser profile are simulated inside an isolated Playwright context;
  the script intercepts the generation request and replays the existing successful job.
- No real generation, profile creation, share, download-count, or database mutation is sent.
- Current Docker bridge DNS cannot resolve MinIO from the API container. For screenshot
  preparation only, use `mc cat` inside MinIO's own namespace. This task does not repair
  or restart the running infrastructure and does not certify the live stack as healthy.

Verified in Chromium at desktop 1600px and mobile 390px:

- Actual images decoded, named comparison section visible.
- Editing the next brief leaves the completed comparison unchanged.
- Enlarge opens, Escape closes, and focus returns to the originating image button.
- Mobile document width equals viewport width: 390px, no horizontal overflow.
- No page errors or unexpected API requests; zero real mutation requests.

Artifacts (ignored local output, not public uploads):

- `output/ip-creation-comparison/comparison-desktop.png`
- `output/ip-creation-comparison/comparison-mobile.png`
- `output/ip-creation-comparison/comparison-zoom.png`
- `output/ip-creation-comparison/verification.json`

The images are screenshots of real historical media replay, not evidence of a new live run.

## Quality gates

- Generated OpenAPI frontend contract drift check: passed.
- Frontend TypeScript + Vite production build: passed.
- Focused component tests: 43 passed across `IpAssetCreationPage.test.tsx` and
  `IpAssetOriginalPreview.test.tsx`; includes immutable receipt, stale-result rejection,
  original-media safety, private transport/cleanup, keyboard behavior and axe checks.
- Implementer targeted ESLint and strict TypeScript: passed.
- Scoped `git diff --check`: passed.
- Independent reviewer found no substantive product-code defect and requested no changes;
  its final repeated gate is recorded in the task's check note.

## Handoff boundary

Initial visual handoff was local and uncommitted. The user's follow-up explicitly confirmed
committing only the seven frontend files, related spec and task records to local Git, followed
by normal task archival/journal bookkeeping. No remote push or deployment is authorized.
Keep unrelated dirty files untouched. The original source/output images remain ignored local
artifacts, not public repository assets.
