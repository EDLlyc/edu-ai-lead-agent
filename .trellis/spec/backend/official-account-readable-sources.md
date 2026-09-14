# Readable WeChat sources and native read-more binding

## 1. Scope / Trigger

Prospective native V5 prepared drafts with two-banner framing use readable source
attribution. This fixes duplicate evidence rows and stripped external anchors.
Deployed in the scoped 2026-09-14 source-overlay release, application commit
`47820643219700d8ca7e616bd0205d6baad925d5`. Activation and health evidence:
`.trellis/tasks/09-05-production-recovery-qwen-embedding/research/readable-source-release-20260914.md`.
This does not migrate historical drafts or establish standard-release provenance.

## 2. Signatures

- `render_readable_sources(article: ArticlePackage) -> str`
- Renderer and `build_strict_prepared_projection` accept `source_presentation=None`.
- Opt-in: `wechat-source-presentation-v1-readable`.
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
- Freeze the first actual source as native `content_source_url`. Other sources
  retain exact copyable URLs, since WeChat strips external anchor wrappers.
- Canonical validation binds version, URL, HTML and identity. Consumers use the
  frozen URL and reject unrelated caller overrides.
- Enqueue/execution calculate policy fingerprints from the same prepared URL and
  comment flags, never a hard-coded `None` URL.
- Keep existing HTTPS, length, control and port checks. No DB/provider changes.

## 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Two evidence IDs, same URL | One visible source |
| Same publisher, different URLs | Both references retained |
| Old manifest without version | Exact old HTML/identity validates |
| Unsupported version or V4 opt-in | Rejected |
| Resealed URL/body/version drift | Canonical rejection |
| Unrelated URL override | Rejected before social calls |
| New native URL at enqueue | Worker policy matches |

## 5. Good / Base / Bad Cases

- Good: duplicate Xinhua evidence yields one source and its real native link.
- Base: historical manifests validate unchanged.
- Bad: deduplication by hostname, guessed dates, or read-more text without a URL.

## 6. Tests Required

- `test_official_account_source_presentation.py`: names, escaping, URL identity,
  old replay, resealed tampering, existing URL restrictions.
- `test_official_account_xiaosai_final_cta.py`: owner opt-in and framing.
- `test_wechat_official_account_draft_worker.py`: enqueue-to-execution URL/policy.
- Run `gzh-design` HTML validation on the representative source component.

## 7. Wrong vs Correct

Wrong: emit one authority anchor per evidence ID and enqueue with URL `None`.

Correct: render versioned URL-deduplicated attribution; bind the actual primary
source through manifest, prepared draft, enqueue and execution.
