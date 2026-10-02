# 修复 Agent 线上效果统计 + 诊断后经批准执行的方案

## Goal

TBD.

## Requirements

- TBD

## Acceptance Criteria

- [ ] TBD

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.

## Status (2026-10-02 21:54)

Live: repair stats in the daily report (cron image 9c9d1c01, report repaired) and approved actions in
propose-only mode (8f14b771; watchdog + edu-ai-ops-action). Review proposals after a week, then
decide on OPS_ACTIONS_ENABLED.
