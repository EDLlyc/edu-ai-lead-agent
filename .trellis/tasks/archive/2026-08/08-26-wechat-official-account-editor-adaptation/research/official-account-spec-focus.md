# Focused official-account handoff contract

This planning extract prevents the long project specs from being truncated during Trellis context
injection. The linked project specs remain authoritative and must be consulted before edits.

## Frozen historical behavior

Source: `.trellis/spec/backend/official-account-editorial-repackage.md`.

- Historical Article/render/media/export version families and fixture golden bytes are immutable.
  New behavior uses a new exact identity and dispatch; it does not edit old constants or reuse an
  old version string with new bytes.
- Current V10 re-export reads persisted PostgreSQL/MinIO truth and makes zero provider/source calls.
  It must remain independent from article generation, audit, embedding, image generation, news
  fetching, WeChat, WeCom and publish clients.
- The current polished bundle owns 1--5 body images, 0--2 news-context images and one separate
  cover. It uses relative assets and a deterministic ZIP and remains `simulation=true`,
  `local_only=true`, `copy_ready=false`, and `published=false`.
- Historical copy-ready mode rejects a context image whose rights status is
  `publish_permission_unverified`; review output remains available. The new editor-handoff direct-use
  policy is additive and cannot relax that existing branch.
- Recovered historical runs must render/export from their persisted version identity and snapshots;
  current default configuration must not reinterpret them.

## New handoff-specific behavior

Source: this task's `prd.md` and `design.md`.

- A run must be ready, simulated, deterministically valid, model-audit accepted, and bound to an
  immutable approved review before copyable artifacts are served.
- The user explicitly chose to retain context images with
  `publish_permission_unverified`. For the new handoff identity only, this is a non-blocking warning
  named `context_image_rights_unverified_direct_use`; rights/source/credit remain visible and are not
  relabeled as authorized.
- Runtime output is a deterministic read-only projection. It creates no migration, repository
  mutation, durable job, worker stage, provider client, credential field or publish action.
- The copy body is a pure gzh-compatible `<section>` fragment with controlled inline styles,
  `span leaf`, relative manifest assets and escaped content. Preview scripts/buttons are outside the
  copy root.
- Runtime browser validation is not fabricated. `not_run` remains an explicit warning; actual
  320px/430px acceptance is performed against an offline fixture.

## Focused backend quality gates

Source: `.trellis/spec/backend/quality-guidelines.md` and the task implementation plan.

- Python 3.11, Pydantic v2, strict typed domain/application boundaries, no FastAPI/SQLAlchemy in
  domain code and no multi-step business logic in route handlers.
- All generated/OpenAPI contracts are regenerated and checked for drift; generated frontend types
  are never hand edited.
- Tests block sockets/provider construction, verify deterministic bytes and archive integrity,
  exercise tamper/path traversal/state matrices, and preserve historical goldens.
- Security checks cover HTML/text escaping, exact URL/media allowlists, response security headers,
  safe Content-Disposition, no private storage paths and no secret/provider body projection.
- Run focused Ruff format/check, mypy, pytest, API contract, frontend lint/typecheck/test/build,
  browser acceptance, Compose config and `git diff --check`; report any command not run.
- Inspect overlapping diffs before each high-collision edit and preserve all unrelated dirty
  worktree changes.
