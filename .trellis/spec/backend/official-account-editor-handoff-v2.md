# Official-Account Editor Handoff V2

## 1. Scope / trigger

- Use this sibling path only for a development-only editor handoff when both the V2 flag and
  `quality_auto` policy are explicit. `manual_only` continues to dispatch the frozen V1 path.
- V2 is a read-only projection of persisted run, Article, render, draft, audit and media state. It
  has no worker, migration, provider, acquisition, WeChat, WeCom, send or publish capability.
- V2 owns new identities and a fresh output directory. V1 constants, renderer output, golden files
  and ZIP bytes remain immutable.

## 2. Signatures

```python
service = OfficialAccountEditorHandoffV2Service(
    session_factory=session_factory,
    resolver=resolver,
    release_policy="quality_auto",
)
inspection = await service.inspect(run_id)

artifact = build_editor_handoff_v2_artifact(...)
finalized = bind_editor_handoff_v2_mobile_validation(artifact, exact_report)
target = write_editor_handoff_v2_artifact(finalized, fresh_output_root)
```

```bash
PYTHONPATH=backend conda run --no-capture-output --name edu-ai \
  python -m app.official_account_editor_handoff_v2_demo \
  --output-dir output/official-account-editor-handoff-v2-staging \
  --browser-report /tmp/editor-handoff-v2-mobile.json
```

## 3. Contracts

- V2 owns `wechat-editor-handoff-renderer-v2-gzh-xiaosai-semantic`,
  `wechat-editor-handoff-style-v2-xiaosai-adaptive`,
  `wechat-editor-handoff-template-v2-block-interleaved-mobile`,
  `official-account-editor-handoff-bundle-v2`, `wechat-editor-handoff-preflight-v2` and versioned
  release/placement/emphasis/recipe/mobile identities. V1 output does not change.
- `quality_auto` consumes persisted run, Article, render, draft, deterministic/model/image audit and
  generated-visual state without constructing a provider. A valid approval yields a truthful
  manual release, no review may yield a machine release, and any immutable rejection blocks.
  Machine release is `release.json`, never a fabricated review row.
- Context images retain their Article section, score exact alt/caption terms against visible text
  blocks, persist an `after` placement and remain separated from images by visible prose. They
  supplement and never replace body image blocks.
- Semantic emphasis selects exact 4--15-character source units, never arbitrary truncations,
  generic transition fragments or unbalanced quotation marks. It renders escaped slices whose
  concatenation equals the input and selects no more than three spans per text block.
- The deterministic recipe is `news_analysis`, `tutorial_list`, `case_opinion` or `analysis`. It
  changes only Xiaosai component rhythm and controlled title/TOC/callout variants; one theme,
  allowlisted inline CSS, `span leaf` and relative local images remain mandatory.
- `content_fingerprint` binds release inputs, Article identity, recipe, placement, body SHA and
  ordered media hashes. `artifact_fingerprint` additionally binds the canonical mobile report.
  Runtime stays `not_run`; a passed report must bind the exact content/body/media values, exact
  ordered `(320, 430)` observations, loaded images, zero overflow, zero external requests and exact
  preview/copy-root equality.
- The deterministic bundle includes release, placements, emphasis, recipe, mobile report, clean
  body/preview, Article/source/rights projections, media, `body-visuals.json`, manifest and ZIP. It
  remains simulation, local-only and unpublished.
- Every V2 body image must be a new V3 reference-conditioned output, never a catalog publication
  placed directly. The durable path requires one current `ready` generated-visual row per body slot,
  exact Article block fingerprint, approved reference public identity, normalized input checksum,
  output profile/hash and generated-media foreign-key match. Unknown or historical plan versions
  fail before byte resolution.
- The offline demo consumes a bounded, exact-field visual map with three distinct metadata-free
  1536x1024 JPEG outputs and three distinct approved reference publications. It verifies safe
  relative paths, every path component against symlinks, duplicate-free JSON objects, hashes,
  dimensions, metadata-free JPEG payloads (including comments), current production block anchors,
  production V3 planning and typed `ImageReference` input without constructing a provider. Safe
  exports include public refs, character labels, selection truth, plan/output identity and no
  private paths, raw IDs, vectors, prompt text or provider bodies.
- A fixture may record an explicitly authorized completed local image-generation run, but repeatable
  builds have zero model/embedding/image-generation calls. Never claim `multimodal_embedding` when
  the frozen reference choice used `deterministic_fixture_semantic`; production continues to carry
  the actual Qwen3-VL method from the durable plan.
- A named final delivery is valid only when rebuilt from the current code after the last semantic,
  renderer or auxiliary-projection change. An in-memory rebuild with the same accepted browser
  report must match its content fingerprint, artifact fingerprint and ZIP SHA-256. Any later
  byte-affecting change requires a fresh non-overwriting directory and repeated browser/gzh checks.
- Context source URL, credit, rights and section/block placement must agree across `article.md`,
  `article.json`, manifest, generated API and workbench; no projection may silently omit or relabel
  those fields.

## 4. Validation and error matrix

| Condition | Required result |
|---|---|
| V2 flag is off, policy is `manual_only`, or environment is not development | Keep V1 dispatch or fail closed; never enter automatic V2 |
| Persisted run/draft, Article/render lineage, deterministic/model/image gate is unknown or failed | Return a stable blocking check before media export |
| A valid human approval exists | Emit `kind=manual` with its immutable fingerprint |
| Any human rejection exists | Block before machine release; automatic quality cannot override it |
| Context media cannot bind a safe visible block or remain separated from images | Fail placement preflight without dropping or replacing media |
| Any body slot lacks a current ready V3 result, exact block anchor, approved reference input or matching generated-media row | Fail with `generated_visuals_ready` or V2 integrity failure; never fall back to direct catalog bytes |
| Frozen visual-map has duplicate keys, any symlinked path component, JPEG metadata, or changed field/path/hash/input/output/character truth | Reject the demo before Article/media export and perform no external call |
| Emphasis rewrites text, overlaps, uses a generic fragment or exceeds three spans | Fail deterministic emphasis checks/tests |
| Browser report does not bind exact hashes and exact 320/430 observations | Reject finalization and keep runtime `not_run` truthful |
| Output target exists, a path is unsafe, or archive verification fails | Preserve the existing target and do not install a partial bundle |

## 5. Good / base / bad cases

- Good: durable gates pass with no manual row, so a machine release creates three IP body images,
  block-bound news images, one cover, a passed exact mobile report and deterministic local ZIP.
- Base: runtime/API projection has canonical `mobile_validation=not_run`; repeated construction from
  the same snapshots has identical identities and bytes, while V1 remains exact.
- Bad: fabricate an approval, accept a rejected run, use one browser result for another article,
  place approved catalog art directly as a body image, claim an embedding call that did not occur,
  silently drop a context image, treat it as evidence/licensed, or call any external/social client.

## 6. Tests required

- Cover machine/manual/rejected gate ordering, unknown or failed image quality, generated-visual
  failure, tampered lineage, deterministic replay, archive safety and V1 byte regressions.
- Assert semantic spans are exact/nontruncated/nongeneric; placements carry semantic matches; three
  IP body images remain; and news media keep source/credit/rights/context-only truth.
- Assert each body output hash differs from generic fixture bytes; its exact current block anchor,
  safe reference public ID/input checksum, selection method, character visibility and output hash
  round-trip across `body-visuals.json` and manifest. Tampered map blocks/bytes, duplicate JSON
  fields, directory symlinks and JPEG comment metadata must fail closed.
- Assert Markdown, JSON, manifest and API/UI project identical source/credit/rights/placement values,
  then hash-match the named final directory against an in-memory current-code rebuild.
- Generate OpenAPI/TypeScript from the backend contract. Run the independent gzh validator to zero
  errors/warnings and Playwright at exact 320/430 with all images loaded, plan-derived order, no
  overflow and zero external requests.

## 7. Wrong vs correct

Wrong:

```python
# A missing review is falsely represented as a human approval.
review = StoredOfficialAccountManualReview(decision="approved", reviewer_label="automation", ...)
```

Correct:

```python
release = EditorHandoffRelease(
    policy="quality_auto",
    kind="machine",
    input_fingerprint=durable_gate_fingerprint,
    gate_codes=passed_gate_codes,
    manual_review_fingerprint=None,
)
```
