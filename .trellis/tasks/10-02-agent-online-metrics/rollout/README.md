# Rollout: daily quality report image (release e8805a4)

Found 2026-10-02: the quality report cron (pinned image 518b16d8) has failed since 09-30 21:40:
its Settings reject the production `.env` (`IMAGE_DIVERSITY_SELECTOR_VERSION` = selector v3, which
the old image does not know), so only 0-byte `*.md.tmp` files exist for 09-30 and 10-01.

Image `sha256:9c9d1c0117d2de62f06bcaa13a94f6f232d5e950d1b134b199e5c4a1a4ae6e9d`
(tag `report-e8805a4`) = running app image 32c89fe6 + the 5 files in `files.txt` (adds the 修复
Agent section); base hashes 3/3 matched the running image; a read-only run for 2026-10-02 wrote
the full report (5,053 bytes) including the new section.

Deploy (owner confirmation required): back up `/usr/local/sbin/edu-ai-quality-report` as
`*.before-e8805a4-<ts>`, set `IMAGE=` to the digest above; then backfill
`edu-ai-quality-report 2026-09-30` and `2026-10-01`. The cron file is unchanged (21:40).
Rollback: restore the wrapper backup.
