# Readable WeChat sources with versioned link visibility

## 1. Scope / Trigger

Prospective native V5 prepared drafts with two-banner framing use readable source
attribution. V1 fixed duplicate evidence rows and stripped external anchors; V2
removes every reader-facing source URL and the native WeChat `阅读原文` target.
V1 was deployed in the scoped 2026-09-14 source-overlay release, application commit
`47820643219700d8ca7e616bd0205d6baad925d5`. Activation and health evidence:
`.trellis/tasks/09-05-production-recovery-qwen-embedding/research/readable-source-release-20260914.md`.
V2 is the reviewed prospective current-owner rule; its production revision and
activation evidence belong to the dedicated 2026-09-15 no-source-link release
task and must be recorded only after activation succeeds. Neither release migrates
historical drafts or establishes standard-release provenance.

## 2. Signatures

- `render_readable_sources(article: ArticlePackage, *, version: SourcePresentationVersion) -> str`
- `source_presentation_content_url(article, version) -> str | None`
- Renderer and `build_strict_prepared_projection` accept `source_presentation=None`.
- Historical opt-in: `wechat-source-presentation-v1-readable`.
- Current owner: `wechat-source-presentation-v2-no-links`.
- New manifest fields: `source_presentation_version`, `content_source_url`.

## 3. Contracts

- Missing version preserves literal historical rendering/manifests, without new
  fields. Never overwrite stored artifacts to upgrade them.
- Prepared owner explicitly opts new two-banner V5 projections in; other callers
  retain their historical default.
- Deduplicate exact stored URLs in first-occurrence order, not evidence IDs or
  hosts. Different paths/queries remain separate references.
- Known complete hosts/proper subdomains map to publisher names, not authority
  tiers. Unknown names are escaped. Do not infer dates or original publishers.
- V1 freezes the first actual source as native `content_source_url`; its other
  sources retain exact copyable URLs. Keep this behavior only for historical
  reconstruction.
- V2 renders publisher names only: no `<a>`, `href`, literal URL, `查看原文`, or
  `阅读原文` hint. It freezes `content_source_url=null`, so WeChat receives no
  native read-more field. Stored Article sources and evidence exports remain intact.
- Canonical validation binds version, URL-or-null, HTML and identity. Consumers
  reject every caller URL override when the prepared value is null.
- Enqueue/execution calculate policy fingerprints from the prepared URL-or-null
  and comment flags; the current V2 therefore fingerprints `None` intentionally.
- Keep existing HTTPS, length, control and port checks. No DB/provider changes.

## 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Two evidence IDs, same URL | One visible source |
| Same publisher, different URLs | Both references retained |
| Old manifest without version | Exact old HTML/identity validates |
| V1 manifest with native target | Exact V1 HTML and URL validate |
| V2 manifest with `content_source_url=null` | No link field enters `draft/add` |
| Caller supplies URL for a V2 child | Reject before token, upload or draft call |
| Unsupported version or V4 opt-in | Rejected |
| Resealed URL/body/version drift | Canonical rejection |
| Unrelated URL override | Rejected before social calls |
| New native URL at enqueue | Worker policy matches |

## 5. Good / Base / Bad Cases

- Good: a new draft shows one deduplicated Xinhua source name and no link affordance.
- Base: historical manifests validate unchanged.
- Bad: changing V1 bytes, leaking a secondary URL, or sending `content_source_url`
  for a V2 child.

## 6. Tests Required

- `test_official_account_source_presentation.py`: names, escaping, V1 URL identity,
  V2 URL absence, override rejection, old replay and resealed tampering.
- `test_official_account_xiaosai_final_cta.py`: owner opt-in and framing.
- `test_wechat_official_account_draft_worker.py`: enqueue-to-execution URL-or-null policy.
- Run `gzh-design` HTML validation on the representative source component.

## 7. Wrong vs Correct

Wrong: render `阅读原文` text or send a native source URL for a current V2 child.

Correct: render versioned URL-deduplicated attribution; bind explicit `null`
through manifest, prepared draft, enqueue and execution while retaining internal
Article/evidence provenance.
