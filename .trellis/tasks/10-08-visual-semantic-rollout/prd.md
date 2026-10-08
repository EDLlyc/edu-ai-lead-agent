# Qwen3-VL 语义排序上线（门控内排序）

## Source (2026-10-08, owner)

After the blind judgments (semantic 13, rules 9, not significant) the owner decided "我感觉可以
上线", then "先在本地做一下吧": rehearse the rollout locally first.

## What the rollout changes (no code change)

Production `.env`: BRAND_EMBEDDING_PROVIDER_MODE=zhipu (pin; today it resolves to zhipu, but
`auto` would switch brand RAG to Qwen once alibaba visual embeddings are configured),
VISUAL_EMBEDDING_PROVIDER_MODE=alibaba, VISUAL_EMBEDDING_ENDPOINT / _API_KEY (owner's key from the
local .env), VISUAL_SEMANTIC_ENABLED=true. Build the visual index (`app.brand_visual_index_main`,
41 images). Recreate the six services (image unchanged).

The content worker already drops every ranking of a post on any failure and records
`semantic_unavailable` (rule order), so a provider outage cannot stop a post.

## Local rehearsal (2026-10-08 14:34; `evals/visual_replay/semantic_rehearsal.py`)

Production settings on a copy of the production catalog (41/41 checksums):
- brand embedding stays zhipu / embedding-3; selector v3; semantic on;
- index: 29 existing + 12 resized images embedded, 0 failed;
- `_resolve_subject_rankings` ready for all 6 categories (2–3 subjects each, 17 queries total),
  ≤ 0.91 s per post;
- 186 production briefs replayed with live rankings: 186/186 picked with semantic in-tier order,
  0 errors, 2 LRU fallbacks, 21 distinct images, top share 8%; identical to the offline re-check
  (186/186), which validates the cached-score mapping;
- failure drill (wrong key): `semantic_unavailable / provider_unavailable`, rule order, 0 errors.

## Rollout

Pending the owner's confirmation (incl. putting the Qwen key on the server).
