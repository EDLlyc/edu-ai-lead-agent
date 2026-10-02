# 选图：按素材余量选人物 + 压缩超大动作图

## Source request (2026-10-02, owner)

"你看看我们做的那个多模态选图，还有什么要优化的？" → items 1 (pool-aware cast planning) and 2
(compress oversized reference images) → "好的，请你处理", replay offline first; deploy: "确认".

## Problem

Selector v3 reused a cooled image (least recently used) in 10 of the last 18 production picks.
Two-person plans alternate between the only two prop-free two-person images, and several action
PNGs (up to 10.2 MB) never fit the 6 MiB reference budget, so they were never selectable.

## Goals and acceptance

- The planner avoids a subject+cast whose fresh action pool is empty; plans are unchanged when the
  catalog has no prop labels or the selector is not v3.
- Every approved action image fits the budget; props and characters in the manifest unchanged.
- Offline replay over production briefs: cooled reuse clearly lower, no selection errors.

## What was built (11ad19c)

- `action_pool_capacity` (domain/visual_assets.py): approved action images per subject and cast
  that pass the prop gate, show exactly the cast, fit the budget and are outside the cooldown.
- Planner penalty: 1,500 for an empty pool, 300 for one image left (visual_diversity.py), wired in
  material_package.py.
- `evals/visual_replay/plan_sim.py`: sequential re-planning plus selection, three arms.
- The 12 action PNGs over 3.5 MB resized to a 1536 px longest edge; manifest rebuilt with
  `scripts/build_brand_asset_manifest.py` (only those 12 entries changed).

## Results (186 production briefs, `tmp/visual-replay/2026-10-02/plan-sim.md`, local)

| Arm | Cooled reuse | Distinct action images | Top image share |
|---|---|---|---|
| Today's planner | 105 (56%) | 15 | 16% |
| Pool-aware planner | 52 (28%) | 15 | 12% |
| Pool-aware + resized images | 3 (2%) | 21 | 8% |

Gate `predeploy gate PASS @ 11ad19c`; 52 unit tests in the touched modules pass.

## Rollout

Live 2026-10-02 13:31 (`rollout/`): image
`sha256:b8fa7adaecbf24b0c5371245b9f8fec40ca3ad31b43c1cb5e23d36427117cba2` = 5887bce7 + 3 app files
+ plan_sim. Smoke on staged and then live materials: 41 assets verified, 26 action images within
budget. Backups: `/var/backups/edu-ai/brand-materials/before-visual-pool-20261002T133009/`,
`visual-assets.manifest.json.before-visual-pool-20261002T133009`, env
`*.before-visual-pool-20261002T133121`. Rollback in `rollout/README.md`.

## Follow-up

- After the first live slots, compare the share of "cooldown exhausted" picks with the replay.
