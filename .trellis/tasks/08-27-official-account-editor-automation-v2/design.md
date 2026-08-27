# 公众号本地自动化与视觉优化 V2：技术设计

## 1. Architecture

V2 继续是批准后状态的只读派生，不新增 worker、provider 调用或数据库 migration。它在现有 V1 旁新增
版本家族，并复用 repository/media resolver 读取 durable snapshots：

```text
run/article/render/draft/media/audits
  -> versioned release policy (manual_only | quality_auto)
  -> immutable release projection
  -> V2 semantic emphasis + layout recipe + context placement plan
  -> V2 body/preflight/content identity
  -> optional exact browser validation report
  -> V2 artifact identity + deterministic ZIP
  -> generated API contract + local workbench/export
```

V1 functions/constants remain callable and unchanged. V2 may live in the same bounded modules when names remain explicit,
or in sibling `_v2` modules if that makes accidental dispatch impossible.

## 2. Release policy

Introduce an enum/config value with a safe default of `manual_only`. The application service receives the policy rather
than reading global settings inside domain code.

- `manual_only`: current approved review and fingerprint checks, V1 behavior.
- `quality_auto`: an existing manual rejection wins and blocks; an existing valid approval produces `manual`; otherwise
  the service derives `machine` from already durable article/render/draft/media quality checks.

The machine decision is a frozen projection, not a fake manual-review row. Its fingerprint hashes policy version, run,
article, render, draft, deterministic audit and media-quality inputs. `release.json` replaces the V1-only assumption in
the V2 bundle; compatibility may retain a nullable/safe `review.json` projection, but it must never label a machine
decision as human.

No provider is called to decide release. An absent/unknown required quality status fails closed with a stable code.

## 3. V2 rendering projections

### Semantic emphasis

Tokenize existing Chinese/ASCII spans without rewriting them. Build candidates from exact substrings already present in
the paragraph, scoring title/digest/heading overlap, numeric expressions, known terms and information density. Select
1--3 non-overlapping 4--15 character spans with deterministic tie-breaking by score, start offset and length. Rendering
escapes each original slice independently. A round-trip helper/test strips markup and proves text equality.

### Context placement

For each context asset, score eligible paragraph/list/quote blocks in its assigned section against alt/caption and source
labels. Select an `after_block_index`; fall back after the first prose block. Resolve collisions in stable ordinal order,
shifting later context images so at least one visible prose block separates every image, including existing body image
blocks. Persist a safe reason code and algorithm version, not raw embeddings or prompts.

### Layout recipe

Classify from structured, local signals only:

- context/news source present -> `news_analysis`;
- list/step density -> `tutorial_list`;
- quote/case signal -> `case_opinion`;
- otherwise `analysis`.

Recipe selects only Xiaosai-blue components. It controls title size band, TOC card width/size, callout alternation and
minor spacing. Deep-blue anchor cards are capped at five; additional callouts use the registered shallow/left-rule
variant. The output remains one section fragment with inline allowlisted CSS and `span leaf`.

## 4. Identity and browser validation

Separate two hashes:

- `content_fingerprint`: release input, article, theme/recipe/emphasis/placement versions, body SHA and media hashes.
- `artifact_fingerprint`: content fingerprint plus the canonical mobile-validation record hash.

Runtime artifacts use canonical `not_run`; browser acceptance first tests the content body/media, emits a report binding
content fingerprint/body SHA/media hashes, then the local exporter builds a final `passed` artifact and ZIP. Therefore
no artifact fingerprint can name two byte variants. API/runtime never imports a fixture report from another run.

## 5. API and frontend

Extend generated schemas with release kind/policy, content fingerprint, recipe, placements and mobile report binding.
Keep the existing development-only GET resource model. The workbench:

- says `自动质量放行` versus `人工批准` explicitly;
- shows each news image's section/block placement and source/rights warning;
- distinguishes runtime `not_run` from exact fingerprint `passed`;
- keeps clipboard/download as browser effects and does not add publish controls.

## 6. Fixture and export

Use only repository-owned/local fixture bytes. The fixture includes at least three IP body assets, one news context
asset and one cover. It may use a checked-in deterministic test image or an existing approved local source asset, but
tests never fetch it over HTTP. The export writer remains non-overwriting and content-addressed.

## 7. Compatibility, rollout and rollback

- Feature flag plus release-policy setting gates V2; `manual_only` is the immediate rollback.
- No database migration or durable row mutation is required.
- Do not edit historical renderer/export dispatch or V1 constants/goldens.
- High-collision route/schema/OpenAPI/frontend/spec files require local diff inspection immediately before patching.
- WeChat/WeCom/model/Embedding/image/news adapters are never constructed by default tests or export.

## 8. Security and failure semantics

All text stays escaped, source links remain HTTPS allowlisted, images remain controlled relative assets, and ZIP paths
remain normalized. Machine release records contain no prompts/provider bodies/private paths. Unknown quality states,
hash drift, mismatched mobile reports and placement inconsistencies fail with typed stable codes.
