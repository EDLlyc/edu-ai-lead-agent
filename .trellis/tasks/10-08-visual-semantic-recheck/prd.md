# Qwen3-VL 语义选图重新评估（本地回放 + 盲评）

## Source (2026-10-08, owner)

"你看看，这个Qwen3-VL语义选图，能不能用上" → recommended re-replaying on the current selector and a
blind human comparison before any rollout → "先来做本地吧，行，请你处理". Local only.

## Built

- `evals/visual_replay/plan_sim.py`: optional in-tier semantic score hook; picks record asset ids.
- `evals/visual_replay/semantic_recheck.py`: both arms replay 186 production briefs in time order
  with the current planner (pool-aware) and catalog (12 resized images); identical gates, rule vs
  Qwen3-VL in-tier order (production query `canonical_visual_query({category, subject})`).
  Scores from the 09-30 cache mapped to the resized images by filename; 2 missing queries
  embedded through the local index. Blind page of 24 differing pairs + key; scoring reuses
  `evals.visual_replay.compare score`.
- Local brand copy matching production (41/41 checksums) in the session scratchpad.

## Result so far (`backend/evals/visual_replay/reports/2026-10-08-semantic-recheck.md`)

Same objective metrics (186 ok, LRU fallbacks 3 vs 2, 21 distinct images, top share 8%); the
arms pick different action images on 153/186 briefs (histories diverge). Which fits the news
better needs the owner's blind judgments: `tmp/visual-replay/2026-10-08/compare-semantic.html`.

## Decision rule (proposed)

Adopt semantic ordering only if it is preferred clearly (e.g. semantic wins ≥ 60% of the decided
pairs); otherwise keep rules. Rollout would also need: production visual index + embedding keys,
BRAND_EMBEDDING_PROVIDER_MODE pinned to zhipu, rule-order fallback when embedding fails.
