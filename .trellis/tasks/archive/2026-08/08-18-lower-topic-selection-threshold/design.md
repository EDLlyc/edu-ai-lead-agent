# Design: immutable `.8` scoring threshold and bounded production activation

## 1. Versioned scoring contract

Introduce an explicit historical `.7` constant and make `scoring-v1-preview.8-threshold-059` the new default. Both `.7` and `.8` belong to the delivered-history/tiered/ministry-compatible version set. `.6` remains the legacy selection-history version.

Define named threshold constants:

- current `.8`: `0.59`;
- historical `.7` and `.6`: `0.62`.

`build_topic_scoring_config(settings)` selects the threshold by exact version rather than relying on a shared dataclass default. `TopicScoringConfig()` represents the current default (`.8`/`0.59`), while explicit historical constructors and metadata replay preserve their stored `0.62` value. Unknown/custom versions keep the existing configurable behavior and are not silently authenticated as `.8`.

The effective veto mapping becomes:

| Version | Threshold | Repeat basis | Veto identity |
|---|---:|---|---|
| `.6` | 0.62 | prior selection | v3 governed content |
| `.7` | 0.62 | prior formal delivered job | v4 delivered content |
| `.8` | 0.59 | prior formal delivered job | v4 delivered content |

No repository query or ranking formula changes are required.

## 2. Compatibility tests

Add contract tests that compare `.7` and `.8` metadata field-by-field, allowing only version, threshold and derived fingerprint to differ. Preserve literal `.6` and `.7` metadata round-trip tests. Exercise the `0.5899`/`0.5900` boundary and prove a delivered-repeat veto still overrides an above-threshold score.

Update only assertions that represent the current default; keep historical fixture versions literal. Real-PostgreSQL delivered-history tests remain valid and must pass unchanged.

## 3. Configuration

Change these defaults together:

- `Settings.content_scoring_version`;
- `compose.yaml` fallback;
- `.env.example`.

Production has a verified single owner: `.env` contains one `.7` key and `.release.env` contains none. The activation therefore performs one atomic, mode/owner-preserving substitution from exact `.7` to exact `.8`; missing, duplicate, or unexpected values fail closed.

## 4. Verification and deployment

1. Complete focused and full repository gates, commit the scoped change, and push Codeup `main`.
2. Build the candidate from a clean detached worktree at the pushed full SHA; do not use dirty workspace bytes.
3. Validate candidate identity, source manifest, imports, `pip check`, Alembic head and both `.7`/`.8` config contracts offline.
4. In a quiet business window, record fresh stable counters and the exact current runtime/source/tag/env state.
5. Stop application services in the established writer-safe order and create a new verified rollback set before mutation.
6. Install candidate source/image, preserve source ownership/modes, atomically change `.env` `.7 → .8`, and run Alembic-only migration (expected no-op; head unchanged).
7. Restore services one-by-one; API first, schedulers/workers in dependency order, dispatcher last. Do not manually enqueue, replay or resend.
8. Verify all 8 services use the candidate image, restart0/healthy, runtime `.8`/`0.59`, and stable durable/provider/WeCom counters.

The repository's production baseline was established by an offline/local-tag release, so use the existing reviewed checksum-bound offline-overlay mechanism rather than assuming the standard digest deployer baseline is ready.

## 5. Rollback

Before `.8` creates durable work, any failure restores exact `.7`, previous source/image/tags/markers and all 8 prior services. If `.8` durable work or a nonterminal delivery appears, stop all 8 application services and preserve candidate state for diagnosis; do not reinterpret or replay that work under `.7`. Database/object-store restore is not expected because there is no migration or object mutation.

## 6. Non-goals

The deployment does not regenerate today's morning selection, make provider calls, or send WeCom messages. A future ordinary scheduled run is the first authoritative business proof of the new threshold.
