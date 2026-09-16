# Compensation implementation checks — 2026-09-16

Worktree: `release-hardening`. No production writes, provider calls or WeChat writes
were performed by the compensation implementer. No commit was created.

## Focused evidence

`PYTHONPATH=backend pytest backend/tests/unit/test_official_account_visual_compensation.py backend/tests/integration/test_official_account_visual_compensation.py -q --no-cov --tb=short`

27 passed: 12 unit cases and 15 cases in a new isolated PostgreSQL database migrated
to the repository head. The database is fixture-created and removed afterward.
Fixtures use a frozen September 16 clock, fake content generation and synthetic
rows; there is no date-dependent test skip or paid request.

- Plan is non-mutating. Apply appends one authorization and private snapshot;
  repeat apply preserves its original deadline and does not create new authority.
- Exact article/lease/receipt/owner/journal/budget mismatches refuse authorization.
- Four concurrent real repository claims consume exactly once; same-lease repeat
  returns in-flight rather than new permission.
- Original article/render and every prior attempt retain their recorded values.
- New unknown remains unknown and unqueued after repeat apply.
- A proved non-applied failure after compensation retries with the same new
  physical key, never the original unknown key; attempt 3 exhausts the frozen
  budget even if callers pass 99 or manually rearm.
- Crash before or after consuming successor attempt 2 does not give lease-recovery
  attempt 3 a second compensation. An expired authorization cannot release a call.
- Modified frozen bundle, article/audit, or original attempt is rejected at the
  paid claim boundary, without consuming or mutating the visual intent.
- The real single-edition producer observes the rearmed same run, releases its
  lease, and remains generating within the new fixed cutoff. No new article is
  created and the original accepted audit is retained.

Ruff lint, Ruff format check, targeted strict mypy for the new module/claim DTO,
and `git diff --check` passed. Peer-owned executor tests cover physical key
forwarding into image generation and resuming article/render/ready-image state.

## Remaining release gate

Independent review, exact production target + mounted journal preflight, checked
deployment, operator apply, and observation of a genuine WeChat draft ACK remain
the main session's responsibility. These local checks alone are not a production
recovery claim. The original supplier result is still unknown.
