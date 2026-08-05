# Validation Record

## Automated gates

- Backend: 400 tests passed; Ruff format/lint and strict mypy passed.
- Frontend: API contract, Prettier, ESLint, strict TypeScript, 15 Vitest tests, and production build passed.
- Infrastructure: Compose rendered, Alembic upgraded to `20260804_0016`, and `make doctor` passed.
- Runtime: API health returned HTTP 200; acquisition, governance, content, PostgreSQL, and MinIO services were running after rebuild.

## Live image acceptance

- Provider: Comfly `gpt-image-2` at the configured HTTPS origin.
- Content-driven selection: approved local Sai Xiansheng/Xiaosai references selected by the manifest and deterministic selector.
- Successful output: `output/imagegen/sai-xiansheng-robotics-content-driven-small-v1.png`.
- Result: validated 1024x1024 PNG, visually inspected, with `具身智能`, a short learning line, `尝试`/`调整`/`进步`, and the approved brand-value line. The full Moments copy was not rendered.
- A later retry using the same default selection received a provider-side `provider_unavailable` response. No partial output was written; the earlier successful artifact remains the acceptance image.

## Image quality enforcement

- Deterministic image validation covers media type, raster signature, dimensions, byte limits, and the
  bounded visual-text allowlist.
- Configured OCR runs an exact-text check and rejects missing, unexpected, or duplicate editorial text;
  an unavailable OCR capability fails closed for the worker path that requires it.
- The provider-neutral visual audit records relevance/IP issue codes and cannot override deterministic
  failures. A failed image gets at most one targeted repair; a second failure becomes `review_required`.
- The material-package API and frontend expose image validation/audit state and repair count without
  exposing prompts, provider URLs, private object keys, or credentials. Social publishing remains out
  of scope.
