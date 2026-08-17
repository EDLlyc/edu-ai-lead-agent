# Implementation Plan

## Phase 1: Versioned domain/config contract

- [x] Add a new default scoring identity and delivered-history veto-rule identity.
- [x] Keep `.6` as an explicitly supported tiered editorial version.
- [x] Make metadata serialization/deserialization, Ministry authentication/threshold bypass, and
  config construction preserve `.4`--`.7`.
- [x] Update Settings, `.env.example`, and Compose defaults without touching private `.env` files.

## Phase 2: Delivered-history projection

- [x] Refactor recent-history loading so selected rows still own `theme_repetition` inputs.
- [x] Add a delivery-backed daily query through copy/package/formal-delivered job lineage.
- [x] Add the equivalent delivery-backed slot query when slot history is enabled.
- [x] De-duplicate rows before latest-date aggregation.
- [x] Branch only by immutable veto-rule identity; preserve legacy replay behavior.

## Phase 3: Regression coverage

- [x] Unit-test `.6`/`.7` metadata, feature identity, and seven-day boundary.
- [x] Real-PostgreSQL test daily and slot selected-but-undelivered cases.
- [x] Cover formal delivered, test delivered, failed/partial/unknown/cancelled/expired, and duplicate
  package/job lineage.
- [x] Prove a newer failed/test job does not replace the latest older successful formal date.
- [x] Exercise one real daily-origin lineage; do not infer daily correctness from the slot query.
- [x] Prove same-day exclusion and theme penalty remain unchanged.
- [x] Run focused repository/service tests, Ruff, and strict mypy.
- [x] Run the full backend gate (completed by the independent Trellis checker).

## Phase 4: Review and documentation

- [x] Independently review query polarity, origin joins, replay compatibility, and test
  non-tautology.
- [x] Update topic-selection/content-slot/WeCom specs with the delivered-history contract.
- [x] Update the end-to-end Agent pipeline spec's scoring handoff/version references.
- [x] Run `git diff --check` and scope audit; do not deploy or mutate production.

## Rollback point

All behavior is repository-only until a separately authorized release. Reverting the new default
version and delivery-backed branch restores the prior selection-backed behavior without data or
schema rollback.
