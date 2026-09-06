# Deployed provider-refusal flow review

## Conclusion

No provider/runtime recovery patch is justified by the observed content refusal. In the deployed
version, the observed **HTTP 400** already becomes a non-retryable rejection: an initial-generation
failure terminates that individual copy run, produces no accepted draft/package, and does not
prevent other eligible jobs from proceeding. Do not change model, credentials, parameters, retry
limits, prompts, selection versions or delivery paths on this evidence.

Important precision: production does **not** parse `1301`. It classifies the HTTP status and
discards the error body. The instrumented diagnostic established `1301` separately for one
observed content-bearing request; it did not update any production job. The nine historical
`copy_provider_unavailable` run records are a different, pre-hotfix cause and must not be relabeled.

There are real **observability/UI accuracy gaps**, but no evidence that they block normal delivery
or constitute a global model outage. A bounded classification/display follow-up can be considered
after recovery verification; none was implemented in this review.

## Scope and evidence

- Read `prd.md`, `design.md`, `implement.md` and the complete `research/execution-log.md` first.
- All code observations below refer to exact deployed commit
  `5c560da71bcbb61b765d3fe82c742cf2d5e676e1`, read with `git show`; line references are for that
  committed file, not potentially dirty current-main files. The previous temporary exact-source
  worktree and test services were already removed and were not recreated or reused.
- The execution log records a fixed nonprivate request accepted by the same endpoint/model/
  parameters; both observed news-bearing requests returned HTTP 400, and the separately reviewed
  instrumented invocation captured only official code `1301`. It also records 15 earlier successful
  governance invocations that day. These are scoped observations, not proof of universal provider
  availability or any future copy's acceptance.
- The last recorded instrumented invocation performed one embedding request (200, six brand hits),
  one generation request (400/1301), zero audits and zero production mutations. Historical counters,
  release/config identity and the protected seven-job cohort remained unchanged.
- The official-code interpretation is already documented in the task's reviewed evidence:
  [Zhipu error-code reference](https://docs.bigmodel.cn/cn/api/api-code). It identifies a refusal
  class affecting input or generated output, not the responsible phrase, passage or brand chunk.
  Public-source/business-fit review and fresh runtime checks are owned by main, outside this audit.

## Exact failure and retry path

| Boundary | Deployed behavior | Source at the deployed commit |
| --- | --- | --- |
| HTTP transport | For status >=400, retains status/headers but replaces body with empty bytes. 401/403 map to authentication failure; 429 and 5xx are retryable categories; other >=400 statuses immediately raise `ProviderRejectedError`. The observed 400 does not reach transport backoff/retry. | `backend/app/infrastructure/ai/zhipu.py:1387`, especially 1418 and 1439–1448 |
| Typed error | `AppError.retryable` defaults to false. `ProviderRejectedError` supplies code `provider_request_rejected`, a static body-free message and HTTP/API status 422, without enabling retry. | `backend/app/core/errors.py:16`, `:210` |
| JSON correction | Generator/auditor call the transport before their JSON/schema correction `try` block. The correction loop catches only JSON-envelope/schema errors, not provider rejection. Consequently HTTP 400 does not trigger a correction request. | `backend/app/infrastructure/ai/copy_generation.py:268`, `:283`, `:296`; audit `:338`, `:351` |
| Copy orchestration | The initial `_generate_and_persist` rejection escapes before a draft exists or deterministic validation/audit/repair can begin. `execute_next` catches `AppError`, records failure, cleans heartbeat state and returns `True` (work consumed), rather than terminating the worker. | `backend/app/application/services/copy_generation.py:171`, `:204`, `:283` |
| Job retry decision | `_record_failure` retries only when `error.retryable` is true and attempts remain. The observed rejection therefore passes `retry_at=None`. | `backend/app/application/services/copy_generation.py:549` |
| Durable state | `fail_job` fences the one claimed job, sets that job and run to `failed`, clears its lease, records its safe error, records `retry_scheduled=false` and a failed checkpoint. It does not change sibling jobs. | `backend/app/infrastructure/db/copy_generation.py:747`, especially 765–805 |
| Graph | One orchestration node connects START to END; no node retry policy or refusal-specific graph loop is installed. The durable job machinery remains the execution authority. | `backend/app/application/services/copy_generation_graph.py:49` |

This is **normal persisted-failure behavior**, not a claim of exactly-once provider execution
under every crash. If the process loses its lease or crashes before terminal failure persistence,
the existing stale-lease mechanism can recover an unresolved running job. No such crash/recovery
was evidenced for the observed refusal. Do not reinterpret a successfully persisted terminal
rejection as a stale job needing replay.

There is one separate existing repair-path nuance: if a later, already-authorized single repair
gets `ProviderRejectedError`, the executor keeps the original draft. If that original was already
deterministically valid and independently audit-accepted, it can remain accepted; otherwise it
stays `review_required`. It does not issue another request after rejection or use a rejected
provider output. This branch is not the observed initial-generation failure and must not be
described as its outcome (`copy_generation.py:330–351`; existing unit case
`backend/tests/unit/test_copy_generation.py:1709`). No change to this separate policy is proposed.

## Sibling isolation and next normal slot

1. `reconcile_ready_slot_topics` selects each legitimate stored slot selection lacking a copy run
   with the current version fingerprint. Existing runs are excluded irrespective of whether they
   succeeded or failed (`backend/app/infrastructure/db/copy_generation.py:165–218`). The ordinary
   daily path has the same missing-run predicate (`:115–163`). No terminal same-version job is
   recreated merely because a scheduler polls again.
2. `_claim` considers only the current business date's queued/retry-scheduled jobs that are due
   and below the attempt cap, with row locking and `SKIP LOCKED`; terminal failed jobs are not
   candidates (`:1101–1187`). This also explains why the protected older queued cohort does not
   become today's automatic work. Do not alter this date boundary to force recovery.
3. The worker reconciles, then rotates among slot selection, optional brand ingestion, copy and
   material work. A consumed failed copy returns to the loop; there is no process-wide
   provider-disabled flag set by that error (`backend/app/content_worker_main.py:324–378`).
   Siblings may wait for their normal turn/resources, but a single rejection is not an ordinal
   or scheduler barrier.
4. The independent content scheduler reconciles each configured schedule and missing current-date
   copy runs periodically. It does not inspect a prior copy failure to disable another slot
   (`backend/app/content_scheduler_main.py:89–129`, `:164–179`). Future events still must pass
   ordinary acquisition/governance/selection; no replacement or fallback topic is authorized here.
5. Package reconciliation requires `run.status=accepted` and a non-null active draft. The final
   load additionally checks deterministic pass and audit acceptance. Thus an initial refused
   run cannot reserve its own image/package (`backend/app/application/services/material_package.py:1666`,
   `:3461`).
6. Slot automatic-delivery candidates are current-date, unexpired, quality-eligible packages with
   no existing formal delivery. The dispatcher chooses the lowest ordinal among **claimable
   delivery jobs**, not among every selected topic. A failed copy with no package/job cannot
   block a ready sibling (`backend/app/application/services/wecom_delivery.py:1033–1068`, `:611–659`).
   Target, expiry, per-package gap and unknown-outcome protections remain in force.

The next scheduled preparation/target in the prior baseline was September 6 06:00/07:30 CST.
Main must recheck current time and actual persisted readiness. This audit cannot promise a future
selection, accepted copy, image success or formal delivery. Completion still requires the real
fresh lineage through `wecom_delivery_jobs.status=delivered`, followed by no duplicate delivery.

## Why historical `copy_provider_unavailable` is different

`_execute_claimed` emits `copy_provider_unavailable` if its brand retriever, generator or auditor
object is `None`, **before brand retrieval or a model request**
(`backend/app/application/services/copy_generation.py:263–267`). It is a missing constructed
dependency, not a decoded supplier refusal and not evidence that an entire provider account is down.

The worker initially constructs a disabled placeholder executor; it replaces it with the fully
wired executor only when provider/brand dependencies are available
(`backend/app/content_worker_main.py:102–109`, `:229–270`). Deployed brand resolution now maps
`auto + zhipu` to Zhipu when Alibaba visual mode is not enabled
(`backend/app/core/config.py:497–508`). The prior hotfix and current successful live embedding/
retrieval substantiate that the old dependency problem and new one-request refusal are distinct.

The task's 20:44 read-only scope observation confirmed nine different selected events and only
one observed event. All nine stored runs still retain the pre-hotfix factory failure. The no-send
diagnostics intentionally did not create production attempts or rewrite their historical reasons.

## API/frontend exposure and genuine gaps

- Copy status and detail APIs return the individual run's status, error code, IDs/timestamps and
  any stored draft/validation/audit findings. `GET /api/v1/copy-generation-runs/{id}/detail` remains
  usable for a failed run with an empty draft list
  (`backend/app/api/v1/routes/copy_generation.py:60–112`, `:115–149`). There is no slot-copy retry
  endpoint here; POST creates/enqueues the separate daily-origin contract (`:30–57`).
- Because the runtime never captures 1301, a newly persisted production HTTP-400 rejection would
  expose generic `provider_request_rejected`, not a content-specific code. Historic factory failures
  correctly retain `copy_provider_unavailable`. The read API itself still succeeds; this is not
  converted into an API-wide 503 or a global provider-health assertion.
- The edition item schema exposes `copy_status`, `copy_generation_run_id` and `copy_url`, but no
  per-copy error code. The slot-level `error_code` belongs to selection, not the child copy
  (`backend/app/schemas/content_slots.py:92–133`; route `content_slots.py:162`, `:225–243`).
- Frontend mapping drops `copy_url`; story cards show the generic individual-failure label and raw
  copy status, then only a package link if a package exists. Thus a first-generation refusal has
  poor in-board diagnosis, although its direct copy-detail API remains available
  (`frontend/src/features/content-edition/api.ts:60–69`, `:124–144`;
  `ContentEditionBoard.tsx:137–178`). The board-wide "confirm API service" message is shown only
  when the edition fetch itself fails (`:45–48`); ordinary failed child data does not trigger it.
- A separate accuracy defect exists in the aggregate projection: once slot selection succeeded
  and no child is preparing, `_edition_slot_state` returns `ready` unless every child is expired.
  Therefore all three children can be `failed` while the slot badge says "栏目已就绪"
  (`backend/app/api/v1/routes/content_slots.py:299–320`;
  `frontend/src/features/content-edition/api.ts:49–58`). This does not enqueue/send anything; it
  overstates readiness, not a global outage. It is a legitimate small UI/projection follow-up.

Minimal follow-ups, **not prerequisites for respectful refusal handling and not implemented**:

1. If operational diagnosis is prioritized, a separately reviewed runtime bounded allowlisted
   `error.code` classification can distinguish content refusal from transport/configuration
   errors while remaining non-retryable and body-free. Preserve unknown-code behavior and historic
   records; do not infer 1301 from every 400. This is observability work, not a delivery bypass.
2. Expose the safe per-copy failure/detail link on the edition card, and make aggregate labels
   describe actual failed/mixed states without reusing UI state as delivery authority. These changes
   require their own API/frontend tests and a scoped release; they do not justify deploying dirty main.

## Addendum: low-score frontier eligibility and government-source priority

Main's separate 21:07 read-only observation reports rank 1, `eligible=true`, total `0.33723653`
below threshold `0.59`, `passes_threshold=false`, zero vetoes, a frontier cohort, zero education
relevance, and both `priority_applied=true` and `threshold_bypass_applied=true`. This audit did not
query those records itself. The combination is consistent with **explicit deployed policy**, not
necessarily a score comparison defect or provider-factory failure:

1. `score_topic_candidate` permits a below-threshold, zero-veto `FRONTIER_SCIENCE_TECHNOLOGY`
   candidate when `config.has_broad_hard_tech_pool` is true. It records bypass reason
   `governed_broad_hard_tech_pool`; the ordinary numeric pass remains false
   (`backend/app/domain/topic_selection.py:792–825`). The configured broad pool is version-gated
   to matching scoring, delivered-content veto, editorial and hard-tech policy versions (`:353–365`).
   This frontier eligibility path does not require positive education relevance.
2. **Government priority is already in exact deployed 5c**, not only in dirty-main specifications.
   `qualified-authoritative-priority-v1` recognizes source policy
   `gov-cn-qualified-science-tech-v1`. It requires its compatible config, zero vetoes, a cohort
   other than `OUT_OF_SCOPE`, and `eligible_without_source_priority`
   (`topic_selection.py:368–377`, `:1014–1036`). The deployed China-government-news source seed
   already supplies this source policy
   (`backend/app/infrastructure/ingestion/source_profiles.py:183–194`).
3. Crucially, government priority does **not** independently grant threshold bypass. The broad
   frontier pool first establishes eligibility; government priority then changes ordering. A
   below-threshold education candidate without another valid bypass cannot be rescued merely by
   this government-source policy. Ministry-specific bypass is a separate branch (`:813–819`).
4. Slot ranking puts priority candidates in group 0 before ordinary eligible candidates in group 1,
   then considers score plus bounded slot affinity. An evening frontier candidate also has its
   normal frontier affinity (`backend/app/domain/content_slots.py:265–275`, `:303–350`). Thus a
   comparatively low raw score can still rank first; rank is not raw-score order alone.

Existing exact-release tests make that intent unusually explicit:
`test_current_policy_admits_governed_broad_hard_tech_below_numeric_threshold` (`test_topic_selection.py:657`),
`test_qualified_government_yaowen_beats_a_higher_scoring_ordinary_candidate` (`:745`), and
`test_government_yaowen_priority_never_creates_new_eligibility` (`:778`). These tests were inspected,
not rerun during this audit.

This explains how the stored classification can lead to selection, **not whether the classification
correctly represents this particular story's main subject**. Main's independent public-source
review identifies a primarily diplomatic/economic story with incidental education/AI mentions.
Determining whether such incidental mentions should qualify for the frontier cohort is a separate
editorial-contract decision requiring user direction and a bounded classifier/policy review. It
does not establish which input/output fragment triggered 1301 and does not authorize a policy
change, regeneration, filter circumvention or replay of the expired selection.

## Validation performed for this audit

- Read-only `git show`/`git grep` of exact committed backend, frontend and existing tests.
- Executed only the two pure status-projection functions extracted by AST from the exact committed
  API file, with synthetic inputs and no imports of application runtime/dependencies. Results:
  failed copy -> item `failed`; all-failed slot -> `ready`; failed + ready -> `ready`;
  failed + preparing -> `preparing`. This confirms the aggregate-label finding without a DB,
  provider or production call.
- Prior full/focused/provider-free and PostgreSQL gates are recorded in the execution log. They
  were not rerun in this review because the isolated source/test environment had been cleaned up.
- Only this Markdown review was written. No product/configuration edits, private source reads,
  provider calls, SSH, queue operations, deployment, commits or modifications to prior evidence.
