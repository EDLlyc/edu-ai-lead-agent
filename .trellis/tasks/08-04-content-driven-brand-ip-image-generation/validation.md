# Validation Record

## Automated gates

- Backend: 382 tests passed; Ruff format/lint and strict mypy passed.
- Frontend: API contract, Prettier, ESLint, strict TypeScript, 15 Vitest tests, and production build passed.
- Infrastructure: Compose rendered, Alembic upgraded to `20260804_0015`, and `make doctor` passed.
- Runtime: API health returned HTTP 200; acquisition, governance, content, PostgreSQL, and MinIO services were running after rebuild.

## Live image acceptance

- Provider: Comfly `gpt-image-2` at the configured HTTPS origin.
- Content-driven selection: approved local Sai Xiansheng/Xiaosai references selected by the manifest and deterministic selector.
- Successful output: `output/imagegen/sai-xiansheng-robotics-content-driven-small-v1.png`.
- Result: validated 1024x1024 PNG, visually inspected, with `具身智能`, a short learning line, `尝试`/`调整`/`进步`, and the approved brand-value line. The full Moments copy was not rendered.
- A later retry using the same default selection received a provider-side `provider_unavailable` response. No partial output was written; the earlier successful artifact remains the acceptance image.

## Known remaining scope

- Image-specific OCR exact-text validation and a provider-neutral visual relevance/IP audit with one targeted repair are not implemented in this task. The current acceptance uses deterministic request/output validation plus manual visual inspection; the image stays non-sendable until the existing manual review boundary is satisfied.
