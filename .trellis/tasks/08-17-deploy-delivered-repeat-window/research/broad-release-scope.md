# Broad Release Scope Summary

## Frozen starting inventory

- Local `main=55cb573`, cached `origin/main=f20db20`, ahead by delivered-repeat/task/journal.
- Initial worktree: 24 modified + 98 untracked, none staged.
- Partition: 82 Agent Workbench, 11 OCR continuation/evidence, 8 deployment-task, 20 report, and 1
  skill-formatting path.
- Two frontend userinfo fixtures match committed-secret policy and require safe rewrite.
- Ignored `.env`, `.gemini`, `private/`, `output/`, caches, dependencies, and builds are never added.

## Git inclusion versus runtime

Commit/push Workbench, shared refactors, OCR evidence/tools, reports/source/generator, portfolio,
Trellis/spec/task, and skill formatting. Include user-facing PDFs/DOCX/TeX; exclude only ignored/
private material and reproducible `.fls`/`.fdb_latexmk`/`.xdv` compiler files.

- `小赛洞察`: active production content-worker behavior; warning-enforced.
- Delivered repeat: `.7` uses formal delivered WeCom history; `.6` remains replayable.
- Workbench: source/shared helpers enter image, but feature stays unreachable in production.
- OCR/diversity: runtime already deployed; preserve true/true; dirty OCR files are tooling/evidence.
- Reports/Trellis/frontend/task operators are excluded by production allowlists.

## Feasible release path

No exact project registry or Docker auth is configured, and c66 is a local-tag fast-path baseline.
Therefore commit/push all safe work to authoritative Codeup, build one immutable offline image/source
bundle from that exact SHA, and deploy through one reviewed local-tag operator. Do not claim standard
digest readiness; task 08-14 remains the future registry activation path. This one-time exception
to the digest-only release spec requires explicit user approval after the final planning summary.

## Failure boundary

Before durable `.7`, restore `.6` before c66. After durable/nonterminal `.7`, stop all eight app
services and retain candidate + `.7`. Never make a second deploy call, DB restore/downgrade,
provider fixture, manual enqueue/retry/resend, or WeCom send.
