# Independent public-content and refusal-flow check

Reviewed the three new public-content/score/refusal-flow artifacts against exact deployed
`5c560da71bcbb61b765d3fe82c742cf2d5e676e1` using read-only `git show`/`git grep`.
No cleaned-up worktree or test infrastructure was reused.

## Finding corrected

Clarified `public-content-fit-review.md`: broad-pool threshold bypass determines eligibility
before source priority; qualified government priority requires an already-eligible candidate and
changes ordering, not its threshold. Also limited the no-provider-patch conclusion to the observed
HTTP-400 path instead of implying that all other jobs must be healthy. The original score JSON
was preserved unchanged.

## Verified conclusions

- The recorded `0.33723653 < 0.59`, frontier cohort, no veto, eligible and bypass flags are
  consistent with the deployed explicit broad-pool path. They do not establish high educational
  relevance. The compact projection is not sufficient to recompute the total or replace complete
  stored policy provenance; no arithmetic error is inferred.
- HTTP 400 becomes a non-retryable `ProviderRejectedError`; initial generation failure precedes
  draft persistence, deterministic validation and audit. Normal fenced failure persistence is
  per job, while the worker continues. The documented lease-loss/crash caveat is appropriate.
- Terminal same-version copy jobs are not automatically recreated. Refused initial copy cannot
  satisfy accepted-copy/package eligibility; it does not form a delivery-ordinal barrier for
  already-ready siblings. This is normal code behavior, not new terminal delivery evidence.
- Production does not decode 1301; only the bounded diagnostic established it for one observed
  content-bearing request. The nine older dependency-construction failures remain distinct.
- The documented edition-label gap is real: `_edition_slot_state` returns `ready` for a succeeded
  selection with all children failed. It is a display/projection issue, not delivery authority.
- The linked official [MFA publication](https://www.mfa.gov.cn/web/wjdt_674879/gjldrhd_674881/202609/t20260904_12016082.shtml)
  was read independently. It supports the broad diplomatic/economic subject description and
  subsidiary education/AI-governance mentions, but does not identify a moderation-triggering
  fragment or prove byte identity with the two captured government pages.
- The narrower substantive-technology eligibility proposal remains a user decision, not an
  approved or implemented business rule. No blanket source/name/country exclusion, moderation
  bypass, historical replay or future-delivery guarantee was introduced.

No blocking overclaim remains in these notes. Task acceptance remains open until a fresh eligible
run is formally delivered and a subsequent pass confirms no duplicate. No product/spec changes,
provider requests, SSH, deployment, commit or runtime tests were performed during this check;
documentation whitespace validation passed.
