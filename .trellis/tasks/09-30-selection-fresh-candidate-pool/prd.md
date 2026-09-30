# 选题候选池只取新鲜事件并按新旧排序

## Source (2026-09-30)

Owner, looking at the exhibit's "09/30 早间，AI 读了 500 条新闻": “这个五百条，是真的读取了五百条新闻吗？”
Then, after the read-only production count: “你觉得哪个方案比较好。” → recommended "filter by the
freshness window, order newest first, then cap"; owner: “好的，请你处理”.

## Problem

`load_governed_topic_candidates` took all `event_clusters.status='active'`, `ORDER BY id LIMIT 500`.
Event ids are uuid5 (hash), so the cut was effectively random and the same every run. Nothing is
ever archived. Production on 09-30: 950 active events (oldest fetched 07-28, 324 older than 30 days).
The 09-30 noon run scored 42 of the 77 events fetched in the prior 3 days and 114 of 209 in 10 days,
while 163 of its 500 were older than 30 days. Events older than the freshness window (10 days) are
always vetoed `stale_event`, so they only took places.

## Change

- Candidate query keeps only events whose event time (same basis as the stale veto:
  `event_time_start` → `event_time_end` → `published_at` → `first_fetched_at`) is within the
  run's freshness window plus one day of margin, orders newest first, and keeps the 500 cap
  (`CANDIDATE_POOL_LIMIT`) as a safety net. Scoring rules, thresholds and vetoes are unchanged.
- Applies to content-slot runs and legacy daily topic runs (same loader).

## Verification

- Integration test `test_candidate_pool_is_the_freshest_events_newest_first`: stale events out,
  fresh ones newest first, the cap drops the oldest. Fails on the old loader, passes on the new.
- Related integration files: only pre-existing failures remain (two migration-head assertions
  and an order-dependent v4 rerank test), identical on the old loader.
- `make predeploy-check`: PASS (see the commit's gate line in the rollout note).
- Replay on production, 09-21..09-30, 29 slots, current rules (v15 + slot-ranking-v3):
  `backend/evals/selection_replay/reports/2026-09-21_2026-09-30-fresh-pool.md`.
  Pool 500 → ~205 per run; fresh events scored ~110 → ~186; ~76 fresh events per run were missing
  before; 0 non-stale old candidates lost; picks changed in 25 of 29 slots; mean pick score
  0.506 → 0.565. Deterministic order only (the LLM rerank was not replayed).

## Rollout

- Needs the owner's go-ahead. Python-only overlay `FROM` the running digest per
  `.trellis/spec/guides/production-mainline.md`, outside slot hours; tell the other sessions the
  new digest; the exhibit connector must pin it before its next restart.
- After deploy the exhibit's "AI 从 N 个候选新闻里" shows about 200 instead of 500.

## Not done

- Archiving old events (writes production data; other features read active events). Not needed
  for this fix.
