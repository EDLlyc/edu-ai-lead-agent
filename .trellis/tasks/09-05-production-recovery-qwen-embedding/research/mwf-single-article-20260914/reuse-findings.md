# Minimal single-article production reuse — read-only findings

Scope inspected: production-shaped `release-hardening` source, the reviewed but
not deployed `manual-wechat-upload` worktree, and the prospective
`independent-article-drafts` worktree. Root working-tree paths did not contain the
independent/manual modules, so the named worktrees are the actual references.
No Git, network, SSH, model, database or WeChat calls were made. The production
head `20260914_0046` is dispatch-provided, not newly inspected here.

## Recommendation

Keep existing article generation and canonical single-child preparation. Add one
date-scoped owner and a narrowly scoped delivery consumer; do not modify the old
three-child contracts and do not import migration `20260909_0044`.

The smallest useful path is:

1. A date owner reserves `(account, Shanghai delivery_date)` and one governed
   event, freezing due time, cutoff, selected package, article identity and budgets.
2. `PostgresOfficialAccountRepository.enqueue_material_package` reuses the
   existing source+generation-mode+version-identity request fingerprint. Persist
   its run ID and poll its state; never regenerate by changing the identity after
   timeout. Existing article worker persists text/media/checkpoints and bounded
   retries. `result_unknown` stays fenced.
3. `PreparedWeeklyDraftArtifactOwner.build_child(run_id, role)` already works for
   **one** ready live article, without a DAG or sibling. Its `validate_child`
   returns a fully validated `WeChatPreparedDraft`. Do not call `aggregate`,
   `validate_batch`, weekly `stage_weekly`, or `prepare_weekly`.
4. Deliver a versioned single-child envelope through the existing shared output
   volume. The publisher validates and stages immutable bytes locally, then calls
   `WeChatOfficialAccountDraftOnlyService.create_prepared` through a durable,
   journaled client. It may claim delivery only at/after the frozen due time.
5. Acknowledged `add` is creation-complete. Persist private ID/ACK before DB state
   completion; a later timeout or DB failure reconciles that ACK, never adds again.

`role` remains necessary to the existing child manifest/preparer, but selecting a
technical role must not promote a non-official source to authoritative news.
This reuse does not require filling all three editorial categories.

## Exact reusable seams and limits

| Location | Reuse | Limit |
| --- | --- | --- |
| release `infrastructure/db/official_account_weekly_production.py:76` | Candidate loading through `_load_material_rows`, `_load_scores`, `_load_source_authority`, `_material_is_eligible`, `_governed_candidate` | `plan` and its returned tuple impose Monday + three roles; factor candidate projection, do not call `select_weekly_articles` then discard two winners. |
| release `infrastructure/db/official_account_local.py:229` | `PostgresOfficialAccountRepository.enqueue_material_package` | Idempotency is source+identity, not delivery date; bind date owner to returned run and do not mutate old runs. |
| release `infrastructure/db/official_account_local.py:1753` | `fail` and existing attempt/checkpoint storage | Configured retry limits exist; caller must freeze new-edition budget and must not call manual rearm after exhaustion. No need to import incompatible article retry columns just to reuse generation. |
| release `infrastructure/wechat_official_account/prepared_artifacts.py:114` | `PreparedWeeklyDraftArtifactOwner.build_child` / `validate_child` | `aggregate` is deliberately still three children. `_build_strict_child` includes current native images, caption policy, framing banners and readable source presentation. |
| release `application/services/wechat_official_account_draft.py:119` | `WeChatOfficialAccountDraftPreparer.prepare` | Pure preflight for one prepared child; preserve native child/version checks. |
| release same file `:151` | `WeChatOfficialAccountDraftOnlyService.create_prepared` | Effect executor only; **no durable idempotency by itself**. It uploads each media then thumbnail then adds, so it must receive a journaled/fenced client. |
| manual worktree `application/services/wechat_official_account_manual_draft.py:310` | `JournaledDraftClient`, per-inline ordinal/bytes intent+ACK, thumb and add receipts | Not present in release. Borrow its bounded mechanism deliberately, not the manual CLI or an automatic `manual_only` masquerade. |
| manual worktree `infrastructure/wechat_official_account/manual_journal.py:38` | `LocalManualDraftJournal`: fixed account namespace, nonblocking account lock, `O_EXCL`, `O_NOFOLLOW`, canonical envelopes, file/directory fsync | Filesystem locking protects writers using that same physical root only, not old DB workers. Root must remain persistent and shared across replacement containers. |
| manual worktree service `:490` | `run_batch` can take one item and verifies own acknowledged ID | Returns `created_unverified` on readback failure; that is still created. It is not itself a scheduled retry engine or global duplicate guard. |
| independent worktree `infrastructure/wechat_official_account/single_artifacts.py:92,132` | `publish_single_child` and `LocalSingleDraftArtifactStore` are useful bounded envelope/staging patterns | Its literal envelope binds `week_start` + `ArticleDeliveryBinding`; adapt to a new date contract/version rather than importing its full domain, tables or weekly policy. |
| independent worktree `infrastructure/db/official_account_delivery.py:44` | `reserve_article_owner`: insert-on-conflict followed by row lock and exact owner equality | Good shared ownership pattern; it protects article fingerprint only, not fresh rewrites of the same event. |

## Why the old three-item jobs are not the shortcut

`WeChatOfficialAccountDraftJobService.enqueue_staged` calls a three-source
preparer and constructs `WeChatDraftJobEnqueue.items` as a closed tuple. Existing
item table constraint fixes ordinal 1/2/3 to official/industry/application roles.
The executor can upload one claimed child, but repository status and claims remain
parent-job driven. Relaxing only tuple length silently changes old semantics.

More importantly, the old repository records `uploaded_image_count` and the final
`draft_media_fingerprint`; it does not persist per-media ACK values or a private
draft ID. The executor calls plain `create_prepared`, so definite failure retries
start uploads again; ambiguous effects become `outcome_unknown`. The prospective
independent executor also calls the plain creator and stores the final fingerprint.
Thus neither route supplies the desired reusable ACK history without a journal.

## Minimal persistence choice

Preferred minimal production-compatible DDL is an additive migration from actual
head `20260914_0046`, with **two small concepts**, not the existing 0044 lineage:

- A single-edition table: immutable edition/date/account identity, prepare/due/expiry
  instants, frozen selection+article policy, selected event/package, run ID,
  prepared ref/article/content identity, status, per-stage attempt counters,
  available_at, lease/fence/heartbeat, safe failure, private-journal receipt ref and
  acknowledged draft fingerprint. Unique `(account, delivery_date)` must survive
  schedule-version changes; status `no_topic` still owns that date.
- A shared owner table keyed by `(account, key_kind, key_value)`, where kind is
  event or article, recording owner and conflict/history. Reserve event at
  admission and article before any upload. This one table handles both duplicate
  dimensions. It can reuse the existing `reserve_article_owner` insert/lock idea.

Per-operation immutable intent/ACK files can remain in the publisher's existing
private artifact volume, avoiding a third SQL write-step table. Bind journal keys
to the DB owner and exact bytes, not caller-chosen retry folder names. Persist ACK
before marking the edition delivered; missing DB commit then resolves by reading
the existing ACK. The receipt log remains authoritative for ambiguous effects.

A filesystem-only date owner is possible on this single-host topology only with
the same persistent, descriptor-safe/fsynced locking rules and a canonical
cross-route history export. It is not a free drop-in: the producer currently has
the weekly output volume, while the private manual journal is publisher-only;
old SQL jobs do not honor its lock. Prefer additive SQL ownership over introducing
another standalone file scheduler with incompatible ownership.

## ACK retries: one necessary adaptation

The reviewed manual `JournaledDraftClient._intent` refuses every existing intent
without an ACK. This is safely conservative but means a definite provider rejection
(even classified transient) remains fenced forever. Do not promise bounded retries
by merely wrapping `run_batch` in a loop.

For this new automatic route, use bounded step attempts and immutable
`known-not-applied` failure receipts. Only an explicitly classified, definitively
non-applied failure permits another attempt; next attempt must preserve request
identity. A timeout, cancellation, invalid response, missing ACK or uncertain
commit never qualifies. Already acknowledged inline images/thumbnail are reused.
Definite failure receipts must store only safe error code/stage/status and frozen
attempt/delay, not raw provider responses. The existing HTTP client's own retry
behavior also needs to be accounted for in the frozen budget; do not multiply
outer retries by an uncounted inner write-retry loop.

## Cross-route exclusions and activation

- Import/reserve **all** old `wechat_mp_draft_items` owners joined to jobs by
  account, not only successful rows. Pending/in-flight/unknown work can otherwise
  race new selection. Keep duplicate historical owners in a conflict state rather
  than choosing a winner or deleting old rows.
- Import manual claims and acknowledged adds from the configured account root.
  Validate canonical intent/ACK linkage using the journal reader. `created_unverified`
  and an `add` ACK exclude reuse just as `created_verified` does. Bare missing ACK
  with a write intent remains a reservation; never classify it unsent.
- Event mapping is crucial: old item/manual raw article fingerprint maps to
  `OfficialAccountArticleVersionModel.content_fingerprint`, then run's
  `material_package_id`, `MaterialPackageModel.run_id`, and governed generation
  run's selected event. Explicit local previews can have production run status
  `result_unknown` **and** an independent manual add ACK, as this September 14
  sample demonstrated; do not infer delivery absence from generation status.
- Where old manual fingerprints cannot be mapped, use a reviewed sealed history
  mapping (run/material/event/source evidence) or expose a conflict. Do not invent
  an event identity from a title or mark the global exclusion complete silently.
- Stop old weekly admission **and** old inbox auto-enqueue in replacement mode.
  Existing historical workers may retain readable history, but any still-active
  old/new/manual write entrypoint must consult shared ownership; otherwise the
  guarantee applies only after those routes are quiesced, not globally.
- Prospective cutover is Wednesday September 16. No startup backfill of September
  14; historical failed/ready siblings and their receipts stay untouched.

## Credential and container boundary

`compose.yaml` currently gives only the draft worker `WECHAT_MP_APP_ID/SECRET`;
its command is `app.wechat_official_account_draft_main worker`. Producer weekly
scheduler/worker own `/app/output` on `official_account_weekly_dag_output`.
Publisher sees that same volume read-only at
`/app/input/official-account-weekly-editions` and owns writable
`/app/output/wechat-mp-draft-artifacts` on a separate volume.

Route new preparation from scheduler/producer without a WeChat client/secret.
Place a new single-edition inbox under that producer output volume. Extend the
existing draft worker's exclusive mode routing (or use one clearly replacement
command) to consume single envelopes and the due-date SQL claim with its existing
credentials. Bind its account to the configured secret-derived fingerprint; the
producer may know a non-secret configured account fingerprint only.

The producer must not use publisher-private journal reads for every scheduled
selection. Import validated manual history into shared SQL ownership in a bounded
activation/consumer reconciliation step, so selection can exclude it without
granting credential or private receipt access to generation services.

## Focused acceptance required

One candidate and no siblings; duplicate concurrent date claims; conflicting
account/event and account/article owners; manual ACK with failed production run;
claim/add intent without ACK; post-ACK DB failure; known-not-applied retry versus
uncertain write; reused media ACKs; timeout after add verified on next read;
date delivery gate + no startup backfill; credentials absent in producer; envelope
rejected by old weekly discovery; banners/source URL/author unchanged after
canonical prepare and upload. No live action has been performed by this research.
