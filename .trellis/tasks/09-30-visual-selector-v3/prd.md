# 配图参考选择 v3：道具/人物门控 + 轮换 + 可选向量排序

## Source request (2026-09-30, owner)

"你看看能不能上线，还有这种类似的多模态的模型吗？" → offline replay approved ("好的，请你处理")
→ "那这个先本地，做做，你看看，怎么做比较好。" Local only; no production change.

## Evidence (replay of 186 production visual briefs, 2026-08-31..09-30)

Label-based numbers use prop labels drafted by Claude from visual inspection
(`tmp/visual-replay/labels/action-props-v1.json`, pending owner confirmation).

| arm | errors / no action | wrong prop | extra character | distinct | top-1 | same as previous |
|---|---|---|---|---|---|---|
| production rules (v2-novelty) | 0 / 0 | 3% | 63% | 5 | 61% | 52% |
| semantic v2 (today's code, production query) | 33 / 23 | 11% | 65% | 3 | 78% | 24% |
| v3 rules | 0 / 0 | 0% | 0% | 15 | 13% | 0% |
| v3 + Qwen3-VL order | 0 / 0 | 0% | 0% | 16 | 13% | 0% |
| v3 + Qwen3-VL, no prop gate | 0 / 0 | 19% | 0% | 15 | 11% | 0% |

- Semantic v2 ranks identity sheets by similarity; with a two-character plan it picks a large
  single-character sheet and exhausts the 6 MiB budget (56/62 duo plans broken). The worker logs
  the ConflictError at info level and skips, so the post silently gets no material package.
- Production concentration comes from novelty exhaustion (every image is "recent" within 7 days,
  so the top rule score wins every time) and thin tags (97/186 briefs are AI; 5/26 action images
  carry an `ai` tag). 118/124 solo-cast plans received a two-character action image.
- Subject retrieval (24 queries): Qwen3-VL puts the obvious prop first for telescope, microscope,
  book and rocket subjects, but 25–46% of the top three carry a forbidden prop (AUC 0.64–0.77);
  AI subjects rank the only suitable image 5th–14th. Embeddings cannot replace the prop gate.

## Design

1. Identity references: deterministic rules only (cover the cast with the fewest bytes).
2. Action reference pool: approved, fits the remaining budget, characters ⊆ plan cast, prop is
   pose-only or allowed for the plan subject (labels live in the private catalog).
3. Order: suitable-prop image not used in the last N picks → pose-only image not used in the
   last N picks → least recently used. Inside a tier: Qwen3-VL similarity when semantic mode is
   on and the index is complete, otherwise rule score; stable asset id last.
4. New selector version; v2 behaviour stays literal when v3 is not configured.

## Open

- Owner confirms the 26 prop labels and the subject → prop table.
- Owner judges `compare-v3.html` (15 production vs v3-rules, 15 v3-rules vs v3-semantic).
- Follow-up, not in scope: reference derivatives (downscaled copies) so large prop images fit
  the 6 MiB budget.

## Implementation status (2026-09-30, local, uncommitted; branch fast-forwarded to mainline 37acc76)

- Domain:
  - `VisualAsset.props`: optional; validated against `KNOWN_VISUAL_PROPS`.
  - `AssetSelectionRequest.recent_action_sequence`: ordered; carried through `_coerce_request`.
  - Selector v3 in `AssetSelector._select_gated_action`.
  - `SUBJECT_ALLOWED_PROPS` and `ACTION_COOLDOWN_REFERENCES=12` live in `visual_diversity.py`.
- Service: selector v3 is accepted in the reviewed bundle.
  - Semantic retrieval queries once per category subject before the lock.
  - Primary and alternate plans each get their subject's ranking.
  - Ordered history is passed through.
  - An unlabelled catalog falls back to v2-novelty and logs a warning.
- Config:
  - `IMAGE_DIVERSITY_SELECTOR_VERSION` accepts v2-novelty or v3.
  - `VISUAL_SEMANTIC_ENABLED` requires diversity plus v3. The local `.env` (semantic on, diversity
    off) is now rejected by this branch.
- Tests:
  - 13 new selector unit tests.
  - Config bundle and guard tests.
  - Postgres integration test of the full v3 reservation with a fake subject-ranking service.
  - Unit and contract: 3152 passed, 32 failed. That is the 28 known failures plus 4 stale fixtures
    already fixed on `feat/eval-gates-20260929`; none are new.
  - The existing integration test `test_concurrent_plan_reservation_replay_and_warning_delivery_contract`
    also fails on unchanged mainline (`execute_next` returns False).
- Replay with the real v3 code (`v3_app_*` arms): same aggregate metrics as the prototype (0 errors,
  0 wrong props, 0 cast conflicts, 15 distinct images, top-1 13%). Individual picks differ on
  about half of the rows because of tie-break details.
- Not done:
  - Prop labels are not in the private manifest yet; this waits for the owner's confirmation.
  - No deploy or commit.
  - The reference-derivative follow-up is not started.

## Owner go-ahead and sample review (2026-09-30, "好的，请你处理，然后你，生成几张图，我看看")

- **Prop labels:** accepted as drafted.
  - Builder `scripts/build_brand_asset_manifest.py` now emits `props` from `_KNOWN_PROPS`.
  - Local private manifest rebuilt; backups are `*.before-props-20260930` and
    `*.before-characters-20260930`.
  - Rebuild diff: only `props` (26 action assets) and one character correction.
- **Samples:**
  - Each re-render uses the production brief, plan, v3 prompt and model gpt-image-2.5-sunburst via
    Comfly, with a direct connection. Through the local proxy, uploads failed with httpx
    `RemoteProtocolError`.
  - Production originals were fetched read-only from production MinIO, with checksums verified.
  - Paid calls: 6 successful renders plus 2 failed attempts; the provider-side outcome of the
    failed attempts is unknown.
- **Sample result (6 pairs):**
  - Production 07db43e1 (two characters, Sai-only astronaut reference) drew Xiaosai as a goggled
    astronaut. v3 with the two-character astronaut image drew Xiaosai correctly.
  - Replay: production had 9 of the 125 plans that include Xiaosai with no Xiaosai in the action
    image (7%); v3 has 0.
  - Three other pairs are on par with production. The two first-version failures are fixed.
- **Finding 1:** `小赛.png` (the Xiaosai identity) is a flat 281x276 logo. A two-character plan with
  a Sai-only prop image drew Xiaosai in Sai's goggles and coat. Selector v3 now prefers action
  images showing exactly the plan cast.
  - Replay after the fix: 0 errors, 0 wrong props, 0 cast conflicts, 14 distinct images,
    top-1 share 16%, strong prop fit 23%.
- **Finding 2:** `小赛看书.png` shows Sai but was labelled Xiaosai by the private override file. It is
  corrected there (private data; production needs the same edit at deploy).
- **Follow-up:** a downscaled 3D Xiaosai full-body sheet as the identity reference (needs reference
  derivatives, because the full-body sheets are 5–8 MB).
