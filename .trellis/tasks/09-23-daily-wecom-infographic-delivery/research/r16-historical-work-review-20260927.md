# R16 historical-work cohort review — 2026-09-27

The first sealed R16 read-only production preflight returned `baseline_identity` before
creating an attempt or stopping a service. The raw database had five unknown and
fourteen pending rows according to the operator's conservative all-history scan.
No production row was edited, retried or removed.

Read-only inspection found exactly seven `copy_generation_jobs` and their seven
`copy_generation_runs`, created on 2026-08-12 for `scoring_profile=preview` and
business dates 2026-08-04 through 2026-08-11. Each is `queued`, has zero job
attempts and no lease. The production worker's claim query requires the *current*
business date, so these historical preview rows are not automatically claimed
by the daily schedule. They remain available to an explicit historical-date
operator action; this release performs no such action.

The other five rows are `official_account_article_runs` from 2026-09-11,
2026-09-14 and 2026-09-16. They are terminal `result_unknown`, with
`current_stage=result_unknown`, `error_code=official_account_generated_visual_result_unknown`,
`error_retryable=false`, one attempt and no lease. The Official Account claim
query accepts only `queued` or expired-lease `running`, not `result_unknown`.
Their unknown provider outcomes must remain unknown and must not be replayed.

The reviewed exception is **exactly** the 19-row deterministic ordered SQL
snapshot in `r16_real_host.HISTORICAL_WORK_COHORT_SQL`, SHA-256
`22fc386e051df9f0cf6509677a929ae53d35e25a4e63775a68b7b20706fa0e12`
after stripping the final newline. It binds IDs, pairings, statuses, attempt
counts, no-lease predicates, dates/profiles and terminal error fields. The
operator first requires aggregate `(unknown,pending)=(5,14)` across **all**
job/run tables, then checks the exact cohort hash; a new, missing, changed or
replaced row blocks the release. Only the count returned to the idle-baseline
gate is normalized to zero; the original rows remain in the full database
identity and in the fresh backup/clone readback. This is not a general
age-based waiver, nor permission to mutate business state.

The known recipient remains the existing ordinary group by its two independently
captured webhook-key hashes. This review does not prove that the image provider
will produce a usable poster or that a group send has happened.
