# Public-source review and editorial-scope decision

## Observed content, not a diagnosed offending fragment

On September 5 around 21:05 CST, a read-only query of the selected immutable event/evidence
identified 10 validated bindings from two public China Government article URLs:

- https://www.gov.cn/yaowen/liebiao/202609/content_7080164.htm
- https://www.gov.cn/yaowen/liebiao/202609/content_7080124.htm

The captured event headline concerns the eleventh Eastern Economic Forum. These two government
pages could not be retrieved by the web tool and exact-URL search returned no result. A matching
official [Ministry of Foreign Affairs publication](https://www.mfa.gov.cn/web/wjdt_674879/gjldrhd_674881/202609/t20260904_12016082.shtml)
was independently found by its public headline. Its main subject is diplomatic and economic
cooperation; education exchanges and AI governance appear within that wider context. This is a
public-source topical review, not a reproduction of the private combined generation prompt.

The known 1301 refusal does not identify which source fragment, brand context or generated output
triggered moderation. Do not label this official report unlawful, claim a specific word caused
the refusal, or rewrite/retry the refused input to circumvent a filter.

## Actual stored selection explanation

At 21:07 CST the read-only score projection for selection
`249c02f0-9389-44ea-b571-2a1676b943a4` showed:

- Rank 1, eligible true, zero hard vetoes.
- Rule total 0.33723653, threshold 0.59, passes_threshold false.
- Broad-v3 frontier cohort, not education-priority cohort; education relevance 0.0.
- Priority applied true and threshold bypass applied true.

This must not be described as a high-scoring education article. The two mechanisms are distinct:
the broad-tech pool can admit an otherwise eligible, non-vetoed frontier candidate below the
numeric threshold; qualified government-source priority then promotes an already-eligible
candidate in ordering. Government-source priority does not itself grant another threshold
bypass. Exact deployed `topic_selection.py:791-828` computes broad-pool eligibility before
`_priority_state`; `:1015-1041` requires `eligible_without_source_priority` for government yaowen.
The stored below-threshold/eligible combination therefore matches an explicit policy path,
not evidence by itself of a scoring arithmetic error or provider outage. The aggregate JSON
projection is not a replacement for the full stored policy/reason provenance.

## Provider-free reproduction against exact deployed source

Loaded only the stdlib-only `editorial_relevance.py` module from deployed commit
`5c560da71bcbb61b765d3fe82c742cf2d5e676e1` through `git show`, then exercised four synthetic cases
in memory. No production data was used as input and no provider/database client was constructed.

| Synthetic case | Current candidate/cohort | Editorial score |
| --- | --- | --- |
| Trade meeting with an incidental AI-governance mention | true / frontier | 0.52 |
| Direct school science-education curriculum | true / education priority | 1.0 |
| Direct AI research/model announcement | true / frontier | 0.5 |
| Trade meeting without any technology mention | false / out of scope | 0.0 |

The first result uses `hard_tech_topic_with_event_or_conference`. This reproduces broad keyword
admission but is not proof that the current published policy was intended to reject it. It also
does not predict provider moderation or end-to-end delivery.

## User decision required before changing eligibility

Main asked whether future selection should require technology, AI or science education to be the
substantive subject, excluding general current affairs/diplomacy/trade with incidental mentions.
This is a scope/eligibility change, so it has not been silently deployed. No answer is inferred
from the suggested default in the asynchronous question.

If approved, preserve genuinely substantive technology research, education practice and relevant
policy/governance announcements. Do not implement a blanket exclusion of government sources,
politicians' names, countries or all policy news. Use versioned policy and balanced positive/
negative regressions, preserve historical snapshots/terminal runs, and release from a clean
task-scoped projection rather than the dirty development workspace. An editorial change must not
be advertised as a guaranteed cure for provider moderation.

## Operational disposition

The separate exact-code review confirms the observed HTTP-400 failure is already non-retryable
and isolated to one copy job; a refused initial draft cannot create a package or block ready
sibling delivery jobs. This observed HTTP-400 path alone does not justify a provider/retry fix;
it does not establish that every unobserved or future job is healthy. No new paid call, content
rewrite, production change or send was performed in this follow-up review.

Recovery still requires the next fresh eligible run to reach formal terminal delivery and a
subsequent duplicate check. Expected next preparation/target remains September 6 06:00/07:30 CST;
this document installs no monitor and promises no automatic observation.
