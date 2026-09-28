# Daily production quality report

`backend/app/quality_report_main.py` prints a read-only summary of one business day: slot
selections (with topic kind, e.g. 国家教育风向), copy pass/repair/fail and issue codes, 7-day brand
snippet reuse, images, formal WeCom delivery, long infographics, Official Account drafts,
acquisition failures and model token usage, plus 🔴/🟡 findings. It runs inside a
`SET TRANSACTION READ ONLY` transaction and never writes.

Production install (2026-09-28):

- `edu-ai-quality-report` → `/usr/local/sbin/` (root, 0755). It runs a one-off
  `docker compose run --rm --no-deps` of `acquisition-api` with the pinned report image, so no
  running service is restarted. Output: `/opt/edu-ai-lead-agent/reports/quality/<date>.md|json`.
- `edu-ai-quality-report.cron` → `/etc/cron.d/` (root, 0644): daily 21:40 Asia/Shanghai, after
  the 18:30 evening push. Log: `/var/log/edu-ai-quality-report.log`.
- Manual run for another day: `sudo /usr/local/sbin/edu-ai-quality-report 2026-09-27`.

When a later release changes the schema, rebuild the report image from that release and update
`IMAGE` in the script. Pushing the report to a WeCom operator group is not enabled yet.
