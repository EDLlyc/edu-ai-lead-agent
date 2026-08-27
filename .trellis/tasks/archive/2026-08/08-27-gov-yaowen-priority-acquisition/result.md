# Result

## Delivered

- Added independent Tier A source `china-government-news` with connector
  `gov_cn_yaowen_v1`, fixed government JSON entry point, strict `www.gov.cn` host and
  `/yaowen/liebiao/` path controls, and immutable offline fixtures.
- Added replay-safe scoring version
  `scoring-v1-preview.11-qualified-authoritative-priority` and policy
  `gov-cn-qualified-science-tech-v1`. Government authority changes ordering only after the event
  is already eligible and veto-free; it cannot bypass threshold, hard veto, freshness, or delivered
  repeat history.
- Fixed GLM-5.2 factual governance to disable default Thinking for bounded JSON output. Live
  diagnosis showed the old request spent all 4096 output tokens on reasoning and returned empty
  content; the corrected two-pass provider flow returned valid strict-schema JSON.
- Kept the content scheduler alive across same-day immutable scoring-version conflicts and cached
  the conflict per business-day slot, preserving historical runs without log spam or database
  rewrites.

## Verification

- Local focused gates: Ruff passed, scoped Mypy passed, source/selection/replay/deployment contract
  tests passed, targeted PostgreSQL integration tests passed, and the final governance/provider/
  scheduler suite passed 37 tests.
- Production acquisition run discovered the target URL and persisted one immutable snapshot and a
  Tier A candidate. The source-specific replay was idempotent (`unchanged=1`).
- Production governance run `bebc00ad-13ab-4130-8d20-7d5ecfd631f0` succeeded and created event
  `c362a3dd-f064-5f69-8c45-dca70ef703fd` with version
  `81e1a922-0eca-53a9-8bf6-a403db60969b`.
- Read-only production scoring projection: total `0.61197349`, threshold `0.59`, eligible `true`,
  cohort `frontier_science_technology`, editorial priority `0.86`, zero vetoes, priority applied
  with reason `qualified_government_yaowen_priority`, and no threshold bypass.
- No topic score/selection row or delivery was forced for the event. Seven pre-existing formal
  deliveries remained delivered.
- Production database is at Alembic `20260825_0036` with 11 seeded sources. All eight application
  containers use image `sha256:c23382aa2f6d...`, are running with zero restarts, API health is
  healthy, and recent severe-error scans are empty.

## Commits

- `7a45a65c2ba18324a279e233516aa25de0bc728a` — government yaowen acquisition and priority policy.
- `bcf9ee1702a829fa85f8b11970acf89d4cbdc43f` — bounded GLM-5.2 governance JSON output.
- `907ca68ff48c5164ffeaf6e35a90bd50160e5c39` — scheduler immutable-history survival.
- `3eca57c36d3b3fed1c702552528b7ffc5e9d2a08` — per-day immutable-conflict cache.
