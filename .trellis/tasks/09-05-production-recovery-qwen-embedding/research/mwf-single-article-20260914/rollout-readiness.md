# M/W/F replacement: production baseline and activation boundaries

## Authorization

User approved prospective replacement after final plan review: prepare ahead of
time, upload one unpublished draft on M/W/F at 10:00 Asia/Shanghai. Technical
defaults: prepare 60 minutes earlier; six-hour same-day catch-up; three bounded
attempts with base delay 60 seconds. First admitted date is 2026-09-16.
No historical batch replay, model test call, image generation, manual upload,
subscriber publication, old draft deletion or unrelated WeCom change is requested.

## Fresh read-only baseline

- Release application: `47820643219700d8ca7e616bd0205d6baad925d5`.
- Image: `sha256:4a8f3a945cb81267d76796b3d43389ac3b6b98b4959f814dd05bc0a142e113a0`.
- Schema head: `20260914_0046`; 12 application services and two dependencies healthy.
- Delivery queues idle, no live/stale-running/ambiguous deliveries; the separately
  sealed seven August copy jobs remain retained and unclaimable as recorded in the
  source-presentation release. Historical article failure is not queue activity.
- Standard release manifest/current-state metadata still missing. Do not report
  this offline activation as a bootstrapped standard release pipeline.
- Production filesystem has 39 GiB free. `.env` is a regular, non-symlink file,
  mode 0600, uid 1000/gid 1001. `.release.env`, `.release-commit`, `RELEASE_COMMIT`
  and `compose.yaml` are regular non-symlink root:root 0600. Preserve exact owners
  and modes when backing up/atomically updating/restoring; do not print values.
- Local exact base image is already present under
  `offline.local/edu-ai/edu-ai-lead-agent-backend:source-478206432197`. A candidate
  overlay must preserve the live Zhipu integration and permanent banners; no
  dependency or full mixed-main replacement is part of this release.

## Prior delivery identity evidence

Private journal root is the draft worker's persistent
`/app/output/wechat-mp-draft-artifacts/manual-v1/`. One account namespace contains
49 JSON envelopes. Canonical envelopes are `{payload, sha256}`; claims bind
`{account, binding}`, add intents `{binding, request, step}`, add acknowledgements
`{intent_sha256, value}`. Do not expose private ACK values or signed media URLs.

Two known acknowledged article identities map uniquely through DB article version
to material/copy event lineage:

- `898e30bf18ff67e07799dcb479ff3e25c44ebc142aa102a85f830fe2dc49e6c3` maps to
  ready article `75c5b5cb-c379-4a19-9e43-e6655ef50fc1` and event
  `1b4accbf-cf6a-5c65-9e49-07c91725c218`; binding version
  `manual-draft-binding-v1` with non-null `raw_content`.
- `aa0bc192b3f1d83816e862cd41b55571aa1efe9c0973818a23ea1961fded31ed` maps to
  article `e907350c-e6cd-4994-8d18-06d1f4470c2d` and event
  `5cb86b96-ee0b-5a30-b181-7948f12c58c5`; binding version
  `manual-local-editorial-preview-binding-v1`, `raw_content=null`, with provenance.
  The generation run remains `result_unknown`, but the manual add is acknowledged;
  that generation status must not permit duplicate delivery.

Six legacy `wechat_mp_draft_items` are all succeeded under the same account.
All six article fingerprints also map to exactly one distinct selected event via
the persisted article/material/copy lineage (fresh read-only verification).
Their exact complete item+job snapshot, ordered by `i.job_id, i.ordinal`, hashes to
`071adb79567c93ce8624467b49c1fa6a31d23bb9ec887d887570b08892409c34`.
SQL projection: `jsonb_agg(jsonb_build_object('item',to_jsonb(i),'job',to_jsonb(j))
ORDER BY i.job_id,i.ordinal)` over items joined to jobs on `j.id=i.job_id`.
Decode the JSON then hash canonical UTF-8 JSON with sorted keys, ensure_ascii=false,
compact separators. An initial query using nonexistent `i.id` failed read-only;
the corrected composite-key query produced the seal above.

Manual history seal: collect sorted relative POSIX paths for all `*.json` under
the exact private root; reject symlinks/nonregular files; project
`[{"path": relative_path, "sha256": SHA256(file_bytes)}, ...]` and hash using the
same canonical JSON. Count 49, digest
`2ad71f65ec195c485e73927db50d8894031944461563db88bbd8790250c808e7`.
This is an advisory baseline until revalidated under the deployment lock. New
lock files are not historical JSON records; do not silently ignore changed old JSON.
Fresh compatibility inspection found all 49 envelopes canonical; files are regular,
single-link uid 999/mode 0600 and journal/account directories uid 999/mode 0700,
with no symlinks. This does not replace under-lock verification at activation.

## Activation and recovery constraints

- Additive migration 0047 starts from actual 0046; do not import the incompatible
  independent-delivery worktree's migration 0044 or reset old rows.
- Consumer imports validated history before producer admission; a shared history
  barrier must not claim success for unmapped or unverified reservations.
- Before consumer starts, both new tables must be empty. Afterwards, expected
  imported owner/history rows are permitted, but editions must remain zero before
  September 16. Imported history is not a provider or WeChat write.
- New mode disables both old weekly admission and old draft inbox consumption.
  Merely disabling inbox auto-enqueue is not enough to prevent old queued execution.
- Back up protected config, runtime files, DB and required storage before migration;
  no retention cleanup or historical backup deletion is necessary for this activation.
- If migration was not attempted, restore exact previous runtime/config after a
  partial stop. Once new ownership/admission exists, schema compatibility alone is
  not permission to restore old route execution. Prefer a forward-compatible
  candidate core with both old/new optional writers disabled if activation fails;
  do not restore DB, downgrade Alembic or clear ownership to force rollback.
- Verify exact candidate digest, 12-service health, new schema, next-due date,
  exclusive mode flags, old-history hashes, new-edition count and private-history
  import outcome separately. No live model or draft call is needed for activation.

Status: read-only baseline complete; product implementation/check/operator work
in progress. No production activation or mutation in this slice yet.
