# Actual producer-window review

Observed September 5, before any candidate activation. Main used read-only SSH/container metadata
and exact deployed source. No model, enqueue, database write, restart or schedule change occurred.

- Acquisition/content scheduler revisions remain
  `5c560da71bcbb61b765d3fe82c742cf2d5e676e1`, with `CONTENT_SLOT_MODE_ENABLED=true` and
  `BUSINESS_TIMEZONE=Asia/Shanghai`. Exact `scheduler_main.py` chooses three slot preparation
  crons instead of the legacy 06:30 cron in this mode. Previously verified morning preparation
  is September 6 06:00 CST; candidate preflight must freshly verify all actual slot settings.
- The official-account weekly scheduler is enabled: production/scheduler flags true,
  minimum week start `2026-09-07`, reconciliation every 300 seconds. Exact deployed
  `official_account_weekly_scheduler_main.py` constructs literal `WeeklyEditionSchedule()`:
  Monday 09:00 Asia/Shanghai, 24-hour catch-up. `due_weekly_edition_week_start` considers only
  the current week's Monday-to-Tuesday window, and the minimum-week guard excludes dates before
  September 7. No weekly work is due on September 5; the next weekly producer is September 7
  09:00 CST, later than the next morning slot preparation.
- The draft worker has auto-enqueue enabled but derives work from completed article artifacts;
  it is not an independent calendar producer. Existing ready/running/claimable queue and effect
  fences remain necessary. Do not infer safety from a cron calculation alone.
- Bind the weekly consumer/minimum-week settings and immutable scheduler source in release
  preflight. The earliest-producer check must cover all actual consumers, not silently assume
  only the content-slot cron exists. Preserve all schedule and enablement settings.

This establishes timing for the proposed release only, not delivery success, completed weekly
articles, successful official-account staging or any unattended monitoring arrangement.
