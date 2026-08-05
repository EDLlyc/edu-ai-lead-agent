# Technical design: Ministry science-news Top 1

## Boundaries

The change has four bounded responsibilities:

1. Add a versioned Ministry source and connector to acquisition.
2. Add a source-specific, deterministic science relevance rule that uses a bounded detail excerpt.
3. Carry source priority through governed event projections into deterministic topic selection.
4. Expose the persisted explanation and let existing content reconciliation consume the current topic revision.

No model call, browser session, proxy pool, publishing integration, or alternate downstream pipeline is introduced.

## Data flow

```text
MOE HTTPS entry
  -> exact HTTPS-to-HTTP same-host/path fallback (source version only)
  -> bounded list snapshot + fixed connector discovery
  -> title-prioritized bounded detail probes
  -> detail snapshot + PubDate/ArticleTitle/TRS_Editor extraction
  -> moe-science-v1(title + bounded body) relevance
  -> candidate/observation with match explanation
  -> existing governance and event organization
  -> event occurrences carry topic_priority_policy
  -> existing eligibility/veto gates
  -> source-priority deterministic rank
  -> current daily topic revision
  -> existing copy/image/validation/audit/material-package workers
```

## Source and transport contract

### Versioned source fields

Extend the source seed/profile/version mapping with:

- `allow_http_fallback: bool`, default `False`.
- `topic_priority_policy: str | None`, default `None`.

Add the same columns to `source_versions` in an additive Alembic migration. The migration default is false/null so old versions remain semantically HTTPS-only and non-priority. The seed config fingerprint includes the fields, so the normal idempotent seed path creates immutable new versions when the configuration changes; historical versions are untouched.

The new seed is:

| Field | Value |
|---|---|
| slug | `moe-science-news` |
| connector | `moe_news_v1` |
| entry | `https://www.moe.gov.cn/jyb_xwfb/` |
| hosts | `www.moe.gov.cn` |
| path prefixes | `/jyb_xwfb/` |
| tier | `A` |
| relevance | `moe-science-v1` |
| priority | `moe-science-top1-v1` |
| policy | recorded/manual review with existing terms timestamp |

### Fetcher behavior

Keep `validate_allowlist` strict by default and add an explicit source-policy parameter used only by `SafeHttpFetcher`:

- HTTPS is always accepted when host/path allowlists pass.
- HTTP is accepted only when `profile.allow_http_fallback` is true and the same host/path allowlists pass.
- Every redirect hop is normalized and validated again; public DNS is checked for every host; response type/size, timeout, cookies, retry and redirect limits are unchanged.
- HTTP does not become a globally accepted scheme, and a redirect to any unapproved host/path remains a typed `PolicyRejectedError`.
- Keep the existing strict helper behavior for all current callers and add contract tests for default HTTP rejection, allowed same-source fallback, off-domain HTTP rejection, and invalid path rejection.

## Ministry connector and relevance

### Connector

Implement `moe_news_v1` as a dedicated connector or a narrowly configured `HtmlConnector` instance with:

- discovery selector `#one_con1` (plus a documented mobile equivalent only if fixture evidence requires it);
- article path regex matching only `/jyb_xwfb/.../20YYYY/t20YYYYMMDD_<numeric-id>.html`;
- URL canonicalization and source allowlist validation for both relative links and the source's HTTP links;
- discovery date hint parsed from the dated article path;
- detail selectors `(.TRS_Editor, article, main)`;
- detail date preference for `PubDate`/`publishdate`, with the discovery date only as fallback;
- title extraction from `ArticleTitle`/`h1` and the existing bounded text extraction behavior.

Do not treat search results, JavaScript links, login links, or external assets as article candidates.

### Relevance rule

Add a domain evaluator `moe-science-v1` with NFKC/case/whitespace normalization and a fixed ordered vocabulary. The MVP vocabulary covers:

`科学`, `科技`, `科创`, `人工智能`, `AI`, `机器人`, `天文`, `航天`, `航空航天`, `物理`, `化学`, `生物`, `实验`, `科普`, `科学探究`, `科学教育`, `工程`, `创新`, `探究`.

The evaluator receives the title and at most a fixed prefix of cleaned body text (planned bound: 6,000 characters). It returns `is_relevant`, `matched_title_terms`, `matched_content_terms`, `matched_terms`, `rule_version`, and `content_characters_considered`. A title/body match is sufficient for this explicitly approved source taxonomy; no generative classifier is consulted.

Acquisition preserves the existing behavior for `ai-title-v1`. For `moe-science-v1`, discovery items are kept in source order, title matches are placed first, and title-neutral items fill the remaining configured detail-probe capacity. The executor fetches no more than the existing accepted-item limit, evaluates the title plus bounded detail body, and persists only fresh, relevant documents as candidates. Non-matches receive a filtered observation with a safe reason and no candidate row.

## Topic selection priority

### Candidate projection

Extend the governed occurrence projection query to read `SourceVersionModel.topic_priority_policy` for all event occurrences. An event is a priority candidate when any active occurrence at the governed event-version cutoff carries `moe-science-top1-v1`. This avoids relying only on the representative article's source when an event is deduplicated across sources.

Add an optional `topic_priority_policy` field to `TopicCandidate`. Add a versioned `selection_priority_rule_version` to `TopicScoringConfig` and bump the default scoring version (planned `scoring-v1-preview.3-moe-priority`) so the new immutable behavior cannot collide with the old profile/version snapshot.

### Ordering and explanation

After scoring and veto calculation, mark priority as applied only when the candidate has the approved policy, passes the numeric threshold, and has no veto. Sort groups as:

1. eligible approved-priority candidates;
2. other eligible candidates;
3. non-veto candidates below threshold;
4. vetoed candidates.

Within each group retain the existing `total`, source trust, event time, and stable event ID ordering. Thus a vetoed Ministry event cannot be forced into Top 1, and two eligible Ministry events use the existing deterministic tie-breaks.

Persist in the existing `topic_scores.explanation` JSON:

```json
{
  "selection_priority_rule_version": "source-priority-v1",
  "topic_priority_policy": "moe-science-top1-v1",
  "priority_applied": true,
  "priority_reason": "eligible_official_ministry_science_source"
}
```

Expose the existing explanation JSON in `TopicScoreResponse`; no new selection table is required. The selected score returned by the daily-topic API then shows why the Ministry candidate won.

## Compatibility and migration

- Existing source rows, snapshots, candidates, occurrences, events, and historical topic runs remain immutable.
- Additive source-version columns use safe defaults. The new source is enabled through the existing seed path and can be disabled by the existing source registry control if live parsing is unhealthy.
- Existing `ai-title-v1` candidates and ingestion tests must remain behaviorally unchanged.
- Existing topic runs with old config snapshots load through a backward-compatible default for the new priority-rule metadata and retain their historical ordering. New runs use the bumped scoring version.
- The current same-day revision mechanism remains the only route for a later governed cutoff to replace provisional `no_topic`/`all_vetoed`; no direct data correction or update of a locked selected row is added.
- Regenerate OpenAPI and frontend generated types after the score/source response changes.

## Operational and rollback shape

- Before live use, run source fixture and fetch-policy contracts, migration checks, and an opt-in one-source smoke.
- A source policy rejection, DNS failure, parser drift, stale/unknown date, or zero relevance result completes as an auditable source/job outcome and cannot create a topic.
- If the live source needs rollback, disable the source or publish a new source version with `allow_http_fallback=false`; do not weaken global URL validation.
- If priority behavior needs rollback, keep historical scoring runs intact and switch the configured scoring profile/version; do not rewrite old `topic_scores` or daily selections.

## Cross-layer test plan

- Unit: normalization, vocabulary matching, body bound, title/body combinations, priority ordering, veto precedence and tie-breaks.
- Contract: fetcher scheme policy and MOE list/detail connector, article-path restrictions, parser drift, and fixture metadata.
- Integration: seed/migration/source version mapping; bounded detail fetch and filtered observations; governance occurrence priority; topic score explanation and same-day revision/idempotency.
- API: source policy visibility, score explanation, daily selected score, and OpenAPI/generated-type consistency.
- Live: one controlled source run with no expanded scope or bypass behavior.
