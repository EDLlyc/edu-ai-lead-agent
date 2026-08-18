# Planning evidence

## Current code

- The current default is `scoring-v1-preview.7-delivered-repeat-history` with `TopicScoringConfig.threshold = 0.62`.
- `.6` maps to selection-backed `topic-veto-v3-governed-content`; `.7` maps to delivered-backed `topic-veto-v4-delivered-content`.
- Topic scoring configuration rows are immutable by profile/version/fingerprint/snapshot, so changing `.7` in place is invalid.
- Settings, Compose and `.env.example` all currently default to `.7`.
- No schema, OpenAPI or dependency change is required.

## Today and production

- The morning run used threshold `0.6200`.
- Scores `0.5997`, `0.5995` and `0.5978` would cross a `0.5900` numeric gate, but remain subject to all existing vetoes and ranking rules.
- Two higher-scoring candidates were rejected by actual recent formal-delivery history; this behavior must remain.
- Read-only production check on 2026-08-18: acquisition API, content scheduler and content worker all resolve `.7`; `.env` contains exactly one `.7`; `.release.env` contains no scoring-version key.
- The change is intended for future ordinary runs only; there is no historical replay or resend.

## Release constraints

- Build from clean Codeup commit bytes, not the working tree.
- Preserve exact env owner/cardinality and perform `.7 → .8` only after a fresh rollback set exists.
- No provider/WeCom call is part of deployment acceptance.
- The current production baseline uses the checksum-bound offline-overlay/local-tag release shape; standard digest baseline must not be assumed.
