# 影子对照按 Agent 版本拆分 + 周报少发按原因分类

## Source request (2026-10-05, owner)

Data review found (1) the shadow summary mixed replays of the old agent v3 with the current v4,
so "Agent 67% vs regeneration 89%" was not the current agent; (2) the weekly "missed 8" needed
reasons. Owner: "好的，请你处理". Statistics only; no production behaviour change.

## Built (2f1146a)

- Shadow: each agent arm records its agent version (shadow's own, or production's from the
  repair attempt); summary table by version; weekly counts the current version only.
- Weekly: each scheduled post not delivered is classified (operator hold, copy, image,
  delivery, other) from its newest copy run, image and delivery job.

## Rollout (2026-10-05 10:45)

Ops image `sha256:1faec7d9f9054bed610271b74b52858b1a5879c7384043c686ba367c27238054` (tag
ops-2f1146a; app/ = mainline 2f1146a); bases 29/29; smoke ok; gate PASS @ 2f1146a. Weekly and
shadow wrappers repinned (backups `*.before-2f1146a-20261005T104504`). week-2026-10-04 rewritten:
missed 8 = copy 4, image 2, operator hold 2 (matches a manual check). Shadow by version:
v3 8 pairs (agent 5, regeneration 8), v4 1 pair (agent 1, regeneration 0). summary.md is
rewritten by tonight's 21:10 run.
