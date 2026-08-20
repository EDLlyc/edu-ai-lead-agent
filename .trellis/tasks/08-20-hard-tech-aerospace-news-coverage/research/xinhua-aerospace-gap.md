# Xinhua aerospace recovery coverage gap

## Verified external evidence

- Xinhua Tech entry: <https://www.news.cn/tech/>
- Verified article: <https://www.news.cn/tech/20260819/661cedb9b6cf44a6976a167bf60b5d73/c.html>
- Published: 2026-08-19 09:11:33, source shown as Xinhua.
- Headline: `朱雀三号遥二运载火箭发射成功 一子级成功着陆预定位置`.
- The article states that the first stage landed at the planned recovery-site position and the second stage placed its payload into orbit.

## Repository evidence

- `SOURCE_SEEDS` already contains `xinhua-tech` and `xinhua-education`; both are active Tier-B authoritative-media profiles.
- `xinhua_tech_v1` accepts controlled `news.cn` `/c.html` articles and the verified path is within the current allowlist.
- Daily discovery scans up to 50 items and probes up to 10 after deterministic cohort ordering. The verified headline is present on the current Xinhua Tech entry.

## Reproduced semantic failure

On the current `science-tech-editorial-v2` evaluator, all three samples return `out_of_scope` with `missing_substantive_frontier_progress`:

1. `朱雀三号遥二运载火箭发射成功 一子级成功着陆预定位置`
2. `我国可重复使用火箭一子级成功回收`
3. `新一代商业火箭完成陆上垂直回收`

Each sample matches `aerospace_astronomy`, but current progress patterns include forms such as `成功发射`, `成功验证` and `完成验证`; they omit completed landing/recovery morphology. The first headline uses `发射成功` and `成功着陆`, so neither current progress expression matches.

## Revised product direction

The user chose broader recall rather than a milestone-only fix. Under a new immutable rule, a governed hard-tech topic is sufficient for candidacy; completed progress, plans, failures, capital/market, events and product releases become typed ranking/explanation signals rather than acquisition exclusions. The downstream LLM pool should admit source-qualified, governed hard-tech candidates without lowering the global `0.59` numeric threshold or overriding remaining evidence, freshness, repeat, privacy/legal and unverified vetoes. The source frontier still does not expand because Xinhua Tech already covers the motivating event.
