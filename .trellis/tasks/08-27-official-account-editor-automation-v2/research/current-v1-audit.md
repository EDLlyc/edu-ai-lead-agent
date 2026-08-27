# Current V1 audit for V2 planning

## Evidence

- Mandatory manual approval: `backend/app/application/services/official_account_editor_handoff.py:234-260`.
- Context images grouped only by section and emitted before blocks:
  `backend/app/domain/official_account_editor_handoff.py:212-237`.
- Mechanical first-substring emphasis: `backend/app/domain/official_account_editor_handoff.py:586-601`.
- Fixed 26px title and 110px TOC cards: `backend/app/domain/official_account_editor_handoff.py:417-466`.
- Runtime and bundle always record mobile `not_run`:
  `backend/app/application/services/official_account_editor_handoff.py:402-404` and
  `backend/app/api/v1/routes/official_account_local.py:314`.
- Clipboard workbench has no rich-copy fallback while standalone preview uses selection/`execCommand` fallback:
  `frontend/src/features/official-account-local/clipboard.ts:7-31` and
  `backend/app/application/services/official_account_editor_handoff.py:57-74`.

## Accepted output observations

- Existing local output:
  `output/official-account-editor-handoff-xiaosai-20260827-v2/wechat-editor-handoff-f990aed59b374666/`.
- Manifest roles: body ordinals 0--2 and one cover; no context image.
- Article: four sections of 426--443 text characters, 51 paragraph tags, three body images and four identical deep-blue
  callout cards.
- Sidecar Playwright report binds fixture fingerprint, passes 320/430 overflow and three image loads, and records zero
  external requests; ZIP's own mobile record remains `not_run`.

## Compatibility decision

V1 was intentionally manual-only and is already committed. V2 must therefore be additive. A machine release is a new,
truthful release kind derived from durable quality inputs; it is not an auto-created human review and cannot override an
existing rejection.

## External-call boundary

V2 default tests, fixture, renderer, export and browser acceptance construct no model, Embedding, image-generation,
news-fetch, WeChat or WeCom client. Live AI/provider integration remains a separate opt-in acceptance path and is not
required to prove the deterministic editor handoff.
