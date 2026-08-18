# Research: Official GLM-OCR layout contract compatibility

- Query: Reconcile the official BigModel `layout_parsing` response with the official GLM-OCR SDK structured output, then identify a fail-closed compatibility model for the existing exact three-line OCR gate.
- Scope: mixed (repository code/specs plus official BigModel and `zai-org` sources only)
- Date: 2026-08-16

## Findings

### Executive determination

The current adapter encodes one plausible reading of the BigModel API documentation, but it is narrower than both the published OpenAPI schema and the official GLM-OCR SDK implementation. In particular, it requires positive one-based indices, mandatory `[0,1]` bboxes, paired element dimensions, and forbids every unknown element field. The official sources do not jointly support those assumptions:

- BigModel's API reference describes raw `bbox_2d` as optional and normalized to `[0,1]`, but the current official GLM-OCR MaaS converter and its unit tests explicitly treat the raw MaaS coordinates as absolute pixels and normalize them to the SDK's `0–1000` contract.
- The API schema gives `index` an integer type and an example of `1`, but no minimum or base. Official SDK examples, SDK formatter output, and MaaS mocks use `0`; the MaaS converter preserves whatever raw index it receives.
- Raw MaaS documents only four labels (`image`, `text`, `formula`, `table`). The SDK's public `json_result` guide documents a richer normalized vocabulary even though the default formatter often collapses native labels back into those four categories.
- The raw API makes `bbox_2d`, `content`, `height`, and `width` independently optional. It defines element `height`/`width` as page dimensions. `data_info.pages` is optional, and a present page entry carries required page width/height.
- The raw HTTP response and SDK `PipelineResult.to_dict()` are different envelopes. They must not be selected by coordinate magnitude or guessed interchangeably.

The safe model is therefore two explicit decoders feeding one small canonical representation:

1. `raw_maas` accepts the direct `/api/paas/v4/layout_parsing` response, retains model-identity validation, and validates either the documented unit bbox form or the pixel form consumed by the official SDK.
2. `sdk_json_result` accepts only an explicitly identified `PipelineResult.json_result`/`to_dict()` boundary, validates `0–1000` bboxes, and relies on pinned out-of-band provider/model provenance because the normalized wrapper does not carry the raw response's `model` field.

The current direct-HTTP adapter should use only `raw_maas`. Supporting the SDK shape should be a separate typed entry point, not an auto-detected fallback on the live response. Both decoders must project only bounded text regions into the existing exact ordered three-line validator. Although raw `bbox_2d` is transport-optional, this application's top-to-bottom/left-to-right gate must require usable geometry for every projected text region; index alone has no published reading-order contract. Any schema, provenance, unsupported-layout, or ordering ambiguity remains terminal before similarity, storage, or repair.

### Files found

- `.trellis/workflow.md` — research/write boundaries and task workflow.
- `.trellis/tasks/08-15-zhipu-ocr-provider-rejection/task.json` — active task metadata.
- `.trellis/tasks/08-15-zhipu-ocr-provider-rejection/prd.md` — provider-rejection diagnosis constraints.
- `.trellis/tasks/08-15-zhipu-ocr-provider-rejection/design.md` — intended OCR contract and exact-text gate.
- `.trellis/tasks/08-15-zhipu-ocr-provider-rejection/implement.md` — task implementation handoff notes.
- `.trellis/tasks/08-15-zhipu-ocr-provider-rejection/result.md` — content-free record of the single corrected provider attempt.
- `backend/app/infrastructure/ai/zhipu.py` — current direct HTTP adapter, response schema, layout projection, and issue classification.
- `backend/tests/contract/test_zhipu_image_ocr.py` — current contract fixtures and fail-closed/privacy tests.
- `backend/app/domain/image_validation.py` — exact visual text issue vocabulary and validator.
- `.trellis/spec/backend/visual-diversity.md` — currently frozen OCR assumptions and required gates.
- `.trellis/spec/backend/error-handling.md` — typed provider errors and content-free diagnostics.
- `.trellis/spec/backend/logging-guidelines.md` — prohibition on provider payload/content leakage.

No implementation or spec file was modified by this research.

### Current code patterns and mismatch points

- `backend/app/infrastructure/ai/zhipu.py:62-75` bounds the response and allowlists only four labels, but exposes only broad envelope/page/layout/unsupported issue codes.
- `backend/app/infrastructure/ai/zhipu.py:137-155` forbids extra element keys, requires `index > 0`, requires a four-value bbox, and makes content default to empty. This rejects official zero indices and official omission of a bbox.
- `backend/app/infrastructure/ai/zhipu.py:164-189` correctly models nested pages, required raw `data_info.num_pages`, optional `data_info.pages`, and an ignorable top-level extension surface.
- `backend/app/infrastructure/ai/zhipu.py:414-482` parses the direct raw response, compares model names case-insensitively, projects the sole page, and invokes the existing exact-text gate. The case-insensitive comparison safely accepts the official response example's uppercase model spelling.
- `backend/app/infrastructure/ai/zhipu.py:502-533` requires element `height` and `width` to appear together and agree with each other and page metadata. The cross-source equality check is useful, but pair-required presence is stricter than the official independent optional fields.
- `backend/app/infrastructure/ai/zhipu.py:536-566` rejects duplicate indices and unknown labels, rejects table/formula, ignores image content, sorts text by `(y1, x1, index)`, bounds output, and normalizes line endings/whitespace. Those projection and terminal-gate properties should be preserved.
- `backend/app/infrastructure/ai/zhipu.py:569-583` accepts only finite ordered `[0,1]` coordinates. This is the leading compatibility mismatch with the official MaaS converter's pixel-coordinate path.
- `backend/tests/contract/test_zhipu_image_ocr.py:120-170` builds only one-based, `[0,1]`, dimension-complete fixtures. `:223-272` explicitly rejects zero indices and coordinates above one. `:361-461` permits all element dimensions to be omitted but rejects independent/partial presence. The fixture matrix therefore reproduces, rather than discriminates, the disputed assumptions.
- `backend/tests/contract/test_zhipu_image_ocr.py:491-526` proves that missing, unexpected, duplicated, or misordered recognized lines retain the established exact-text issue codes.
- `.trellis/tasks/08-15-zhipu-ocr-provider-rejection/result.md:454-474` records one bounded provider attempt that ended only as `image_ocr_layout_invalid`, with no response body or recognized content exposed and no retry. Because the current parser maps zero index, bbox scale, label, extra-key, and several type failures to the same code, that observation has essentially no likelihood ratio among those causes.

### Official external references and versions

Only official primary sources were used:

- [BigModel document parsing API reference](https://docs.bigmodel.cn/api-reference/%E6%A8%A1%E5%9E%8B-api/%E6%96%87%E6%A1%A3%E8%A7%A3%E6%9E%90) and its [Markdown source](https://docs.bigmodel.cn/api-reference/%E6%A8%A1%E5%9E%8B-api/%E6%96%87%E6%A1%A3%E8%A7%A3%E6%9E%90.md) — endpoint/OpenAPI response fields and raw label enum.
- [BigModel GLM-OCR model guide](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-ocr) — official request examples and SDK installation guidance.
- [`zai-org/GLM-OCR` commit `cef4d0e`](https://github.com/zai-org/GLM-OCR/commit/cef4d0ea120d1741f5cefe8985eee45f6c8eff1d), dated 2026-04-21 — inspected current implementation baseline.
- [`glmocr/maas_client.py`](https://github.com/zai-org/GLM-OCR/blob/cef4d0ea120d1741f5cefe8985eee45f6c8eff1d/glmocr/maas_client.py) — returns the raw MaaS JSON unchanged.
- [`glmocr/api.py`](https://github.com/zai-org/GLM-OCR/blob/cef4d0ea120d1741f5cefe8985eee45f6c8eff1d/glmocr/api.py) — converts raw MaaS pixels to `0–1000`, constructs normalized regions, and serializes `PipelineResult`.
- [`glmocr/tests/test_unit.py`](https://github.com/zai-org/GLM-OCR/blob/cef4d0ea120d1741f5cefe8985eee45f6c8eff1d/glmocr/tests/test_unit.py) — offline mocks include zero indices and pixel-to-`0–1000` normalization, including a page-sized pixel bbox.
- [Official SDK integration guide](https://github.com/zai-org/GLM-OCR/blob/cef4d0ea120d1741f5cefe8985eee45f6c8eff1d/skills/sdk/SKILL.md) and [`agent.md`](https://github.com/zai-org/GLM-OCR/blob/cef4d0ea120d1741f5cefe8985eee45f6c8eff1d/agent.md) — public `json_result` envelope, zero-based examples, `0–1000` scale, richer label list, and SDK error serialization.
- [`glmocr/postprocess/result_formatter.py`](https://github.com/zai-org/GLM-OCR/blob/cef4d0ea120d1741f5cefe8985eee45f6c8eff1d/glmocr/postprocess/result_formatter.py), [`glmocr/config.py`](https://github.com/zai-org/GLM-OCR/blob/cef4d0ea120d1741f5cefe8985eee45f6c8eff1d/glmocr/config.py), and [`glmocr/config.yaml`](https://github.com/zai-org/GLM-OCR/blob/cef4d0ea120d1741f5cefe8985eee45f6c8eff1d/glmocr/config.yaml) — native-to-result label mapping and zero-based valid-region reindexing.
- [Official JSON examples](https://github.com/zai-org/GLM-OCR/tree/cef4d0ea120d1741f5cefe8985eee45f6c8eff1d/examples/result) — normalized integer bboxes on `0–1000` and indices beginning at zero.
- [Official `z-ai-sdk-python` v0.2.3 release](https://github.com/zai-org/z-ai-sdk-python/releases/tag/v0.2.3) — the version pinned by the BigModel guide at review time. Its published OCR response types make `bbox_2d`, `content`, `height`, and `width` optional, consistent with the OpenAPI schema.

The current `glmocr` published release inspected for parity was `0.1.5` (2026-04-08); its wheel contained the same MaaS bbox-normalization behavior. The repository commit above is newer and is the primary source of truth used here.

### Raw MaaS contract versus SDK-normalized contract

| Property | Raw `/layout_parsing` | SDK `json_result` | Compatibility consequence |
| --- | --- | --- | --- |
| Envelope | Object with `model`, nested `layout_details`, `data_info`, and other response metadata | `json_result` is pages → regions; `to_dict()` may also contain `markdown_result`, `original_images`, `usage`, `data_info`, or `error` | Select with an explicit trusted boundary; never infer envelope from bbox values |
| Model identity | Present on the direct response and required by this application's durable boundary | Not retained in the normalized `to_dict()` example | Raw decoder must compare it; SDK decoder requires pinned out-of-band provenance |
| Page shape | `layout_details: list[list[LayoutDetail]]`; `data_info.num_pages` required by the official response component; `pages` optional | `json_result: list[list[region]]` | For a single image, require exactly one outer page in either form |
| Index | Integer; example `1`; no minimum/base/contiguity constraint | Examples and formatter use `0`; MaaS conversion preserves raw index | Accept strict nonnegative integers, including both zero- and one-origin sequences; require uniqueness, not a guessed base |
| Bbox | Optional; docs say `[0,1]`, while official converter/tests consume raw pixels | Optional in practice; public SDK contract says `0–1000` regardless of backend | Validate per source; raw accepts unit or dimension-bounded pixels, SDK accepts `0–1000` |
| Labels | Exactly `image`, `text`, `formula`, `table` in OpenAPI enum | Guide lists `title`, `text`, `table`, `figure`, `formula`, `header`, `footer`, `page_number`, `reference`, and similar categories | Separate source allowlists and map to semantic actions, not one shared string enum |
| Element fields | `index` and `label` required; `bbox_2d`, `content`, `height`, `width` optional | Normalized MaaS converter emits only `index`, `label`, `content`, `bbox_2d`; guide shows the same core | Do not require optional raw fields; keep normalized element allowlist tight |
| Dimensions | Element height/width describe page height/width; `data_info.pages[*]` also carries page width/height | `data_info` may be retained outside `json_result`, but bbox is already normalized | Validate consistent duplicates; do not require both element fields merely because one exists |
| Presentation fields | `md_results` and crop/visualization fields may exist | `markdown_result`, `original_images` may exist | Never use them for the exact gate and never include them in diagnostics/logs |
| Failure form | HTTP/status or malformed response handled by adapter | SDK may return a `PipelineResult` whose serialized dict contains `error` | A present SDK `error` is terminal; never log or relay its value |

### Reconciliation by disputed field

#### Index base

There is no official invariant that raw indices start at one. The OpenAPI example of `1` is evidence for a possible one-based response, not a schema constraint. The official SDK's examples and formatter provide direct evidence for zero-based normalized results, and its MaaS converter does not shift raw indices.

Recommended invariant: `index` is a strict integer (booleans rejected), bounded, nonnegative, and unique within the page. Preserve it unchanged and use it only as ordering metadata/tie-breaker. Do not require contiguity: the OpenAPI does not promise it, and gaps do not weaken the exact text gate. Both `[0,1,2]` and `[1,2,3]` are accepted, while negative, duplicate, boolean, string, or out-of-bound indices fail closed.

#### Bbox scale and coordinate semantics

The official sources conflict. The API prose says normalized `[0,1]`; `glmocr/api.py` explicitly comments that MaaS uses absolute pixel coordinates from its internal rendering and performs `coordinate / page_dimension * 1000`. The official unit test exercises that transformation using full-page pixel dimensions. The SDK guide independently promises `0–1000` after normalization.

Recommended invariant:

- All present bboxes contain exactly four finite real numbers (not booleans), ordered as `x1 < x2` and `y1 < y2`, with nonnegative coordinates.
- At the `raw_maas` boundary, select scale once for the entire text page. If every text coordinate is at most `1`, the page is valid under the documented unit contract. If any text coordinate is above `1`, treat every text bbox as pixels and require positive page width and height; x coordinates must be at most width and y coordinates at most height. Do not accept an unexplained raw `0–1000` form without page dimensions.
- At the `sdk_json_result` boundary, every coordinate must be in `0–1000`.
- Page-level scale selection is essential when a pixel page mixes a tiny bbox whose values fit within `[0,1]` with ordinary pixel boxes: classifying each bbox independently can change their relative order. If every text bbox fits within `[0,1]`, unit and pixel interpretations differ only by the same positive axis scaling and preserve `(y1, x1)` order, so that remaining ambiguity is harmless to this gate.
- Because the product contract explicitly requires top-to-bottom/left-to-right projection and the provider does not publish index as reading order, every projected text region requires a bbox. A missing bbox is `image_ocr_contract_bbox_shape`. Missing bbox on an ignored image/figure remains harmless.

#### Labels and mapping

Use a source-specific allowlist followed by a shared semantic mapping:

| Source labels | Semantic action | Reason |
| --- | --- | --- |
| Raw `text` | Project as visible text | Raw OpenAPI textual category |
| Raw `image` | Ignore bounded content | Official non-text category; crop URL/path must not be projected |
| Raw `table`, `formula` | Terminal unsupported layout | Structured content can hide additional visual text or reorder it |
| SDK `text`, `title`, `header`, `footer`, `page_number`, `reference`, `seal` | Project as visible text | Treat all documented textual regions as visible so extra text cannot be silently hidden from the exact gate |
| SDK `image`, `figure` | Ignore bounded content | Documented non-text categories |
| SDK `table`, `formula` | Terminal unsupported layout | Same fail-closed rule as raw |
| Any unlisted label, including case variants | Terminal unknown label | Avoid speculative mappings and provider drift |

The default SDK formatter maps many native labels such as document/paragraph titles, reference content, vertical text, seals, formula numbers, tables, and formulas into the four canonical result buckets, while abandoning or skipping several headers/footers/images. That internal native vocabulary is not itself permission to accept arbitrary native labels at the `json_result` boundary. Accept the public normalized labels above; add a label only with a pinned official source and a deliberate semantic action. If a future SDK region exposes a `native_label`, it is metadata only and must never override or rescue an invalid normalized `label`.

This mapping preserves the exact gate: adding `title` support does not make output permissive, because its content is counted as visible text and any fourth/unexpected line still fails.

#### Optional fields, extra fields, and content

- In raw MaaS, require `index` and `label`; accept `content`, `height`, and `width` independently as documented. `bbox_2d` is also transport-optional, but a raw text region without it cannot satisfy this application's spatial-ordering gate and fails with the bbox-shape code. Missing/null textual content normalizes to an empty bounded string and therefore ends as `missing_visual_text`, not a schema crash or success. A non-null content value must be a bounded string with the existing control-character checks.
- A present dimension must be a strict positive bounded integer. Validate width and height independently. `data_info.pages[0]` is authoritative when present. Without page metadata, all present element values for the required axis must agree before that axis can be used as fallback. Both axes are required only when page-level raw bbox classification selects pixels. Element/page equality is not required because the official executable converter uses `data_info.pages`, not element metadata, for normalization.
- For a direct raw response, ignore bounded unknown top-level response metadata after the envelope and identity discriminators are validated. At the element level, accept only the six OpenAPI keys; an unknown element key is terminal because it may carry alternate semantics that would otherwise be silently discarded.
- For normalized SDK input, accept only the documented four region keys (`index`, `label`, `content`, `bbox_2d`). Wrapper keys such as `markdown_result`, `original_images`, `usage`, and `data_info` are outside the region and ignored after bounded wrapper validation. A present `error` key is terminal without inspecting or emitting its value.
- If later official SDK code proves additional region metadata such as crop paths or polygons, add those names to a source-specific ignored-key allowlist only. Never use their values for text, ordering, diagnostics, or logs. Do not set `extra="ignore"` for all element keys, because that would make an undocumented semantic change invisible.

#### Height/width and single-image page metadata

The element field descriptions call these page height and page width, not region height/width. The official page metadata duplicates the same axes. A single input raster should therefore satisfy:

- `raw_maas`: exactly one nested `layout_details` page and `data_info.num_pages == 1`; `data_info.pages` may be omitted, but if present it must contain exactly one entry with positive bounded width/height. Present element dimensions are page-dimension assertions and must be consistent as described above.
- `sdk_json_result`: exactly one `json_result` page. Optional retained `data_info` is advisory cross-check metadata; if it is present, reject a non-one page count or a conflict rather than silently ignoring it.
- Empty sole page remains structurally valid but cannot pass the exact text gate.

#### MaaS raw response versus normalized `json_result`

`MaaSClient.parse()`/its request helper returns raw JSON. The higher-level SDK converts `layout_details` into `json_result`, uses `data_info.pages` to normalize raw pixel bboxes, preserves the raw index/label/content, and drops raw element dimensions and other element fields. `PipelineResult.to_dict()` adds presentation/local-path metadata and can surface an `error`, but does not retain raw model identity in its public example.

Consequences:

- The direct HTTP adapter must not accept `json_result` as a fallback if `layout_details` parsing fails. Doing so could bypass model identity and reinterpret coordinates.
- A future SDK-backed adapter must not feed normalized `json_result` through the raw parser. It should pin SDK version, provider, model, and mode in configuration/result provenance, reject SDK `error`, then invoke the normalized decoder.
- If both `layout_details` and `json_result` appear at a boundary that claims to be ambiguous, reject with `image_ocr_contract_source_conflict`; do not choose whichever passes.
- Never use raw `md_results` or SDK `markdown_result` for recognition. Markdown headings, tables, image links, and formula syntax are presentation transforms and are not equivalent to visible ordered lines.

### Bayesian confidence and discriminating evidence

These are subjective posterior probabilities after reviewing the cited official sources; they are not provider measurements.

| Proposition | Posterior confidence | Most discriminating evidence | What would change it |
| --- | ---: | --- | --- |
| The response layout is pages → regions, not one flat list | 99.5% | OpenAPI shape, SDK shape, converter, and examples agree | A newer official versioned schema |
| Direct MaaS commonly emits absolute pixel bboxes despite the docs saying `[0,1]` | 82% | Official converter comment/formula and offline full-page pixel test are implementation-specific; API prose points the other way | Sanitized official raw fixture/schema clarification; no live call is needed if docs/code are corrected |
| Direct MaaS emits `[0,1]` bboxes | 15% | Explicit API description | Same discriminators above |
| Direct MaaS emits already normalized `0–1000` bboxes | 3% | No direct official claim; this is the SDK output promise | Versioned raw response example saying so |
| SDK `json_result` uses `0–1000` coordinates | 99% | SDK guide, converter, unit test, and example files agree | Versioned SDK breaking change |
| A parser must accept both zero- and one-origin indices | 99% | Raw schema has no base constraint; official examples exist for both; SDK formatter uses zero | An official schema minimum plus explicit base guarantee |
| Raw index is always zero-based | 55% | SDK mocks use zero and converter preserves it | Sanitized official raw fixtures across versions |
| Raw index is always one-based | 35% | BigModel schema example uses one | Same |
| Raw base is deliberately unspecified/variable | 10% | Absence of a constraint | Explicit provider statement |
| Raw label vocabulary is the four OpenAPI enum values | 97% | Explicit enum and MaaS converter behavior | Versioned raw schema expansion |
| SDK compatibility should recognize the documented richer label vocabulary | 90% | Official SDK integration guide explicitly publishes it, although default mappings often collapse labels | A versioned `json_result` schema that narrows the enum |
| Raw bbox/content/height/width are independently optional | 98% | OpenAPI required set and official Python SDK types agree | Corrected official schema |
| Element height/width are page dimensions | 99% | Direct official field descriptions and converter's need for page dimensions | Corrected field documentation |
| A single raster result should have one outer page and `num_pages == 1` in raw MaaS | 99.5% | Envelope semantics, input type, current design, and all official examples align | Official multi-frame image behavior |
| `data_info.pages` may be absent | 98% | OpenAPI and SDK types mark it optional | Corrected official required set |

The sanitized one-call result in the task record does not materially update any row: a broad `image_ocr_layout_invalid` is equally compatible with zero index, pixels, an official optional-field pattern, an extra element key, or a genuinely malformed response. Retrying without first splitting the safe diagnostic codes would provide poor information value and was outside this research scope.

### Recommended canonical compatibility model

The implementation target should be a content-free discriminated union, conceptually:

```text
RawMaaSResponse(source="raw_maas", model, layout_details, data_info)
SdkResult(source="sdk_json_result", json_result, optional data_info/error,
          pinned provider/model/sdk_version provenance)
                         │
                         ▼
CanonicalPage[CanonicalRegion(index, action, optional bbox, bounded content)]
                         │
                         ▼
ordered visible lines → existing exact ordered three-line validator
```

Validation order should be deterministic and terminal:

1. Enforce response byte/collection/string bounds before detailed parsing.
2. Validate the explicit source envelope and reject mixed/conflicting envelopes.
3. Validate raw model identity, or SDK out-of-band provenance, before projection.
4. Require one page and validate/cross-check page dimensions.
5. Validate region types, unique nonnegative indices, source-specific labels, optional bbox scale/range, optional content, and allowed fields.
6. Reject table/formula before text projection.
7. Require geometry for every projected text region and sort by normalized `(y1, x1, index)`; index is only the final geometric tie-breaker.
8. Normalize only line endings and Unicode whitespace, retain the existing per-line and eight-line bounds, and invoke the existing exact ordered validator against the immutable expected three-line tuple.
9. On any parser-stage issue, stop before similarity/storage/repair. Never downgrade a parser issue to a missing-text repair.

This accepts both official shapes without weakening the gate: compatibility applies only to metadata representation, while acceptance still requires exactly the three expected visible lines in exact order and no unsupported structured region.

### Stable content-free issue subcodes

Keep the external API at generic `invalid_provider_output`. Internally, replace the current catch-all layout code with a bounded allowlisted tuple (for example at most four sorted unique codes) drawn only from the following constants. No code includes a field value, array index, content excerpt, provider message, URL, or exception text.

| Suggested subcode | Meaning |
| --- | --- |
| `image_ocr_contract_source_invalid` | Neither the explicitly selected raw nor SDK envelope is structurally present |
| `image_ocr_contract_source_conflict` | Raw and normalized envelopes conflict/co-occur at an ambiguous boundary |
| `image_ocr_contract_model_missing` | Raw response lacks a bounded model identity; an unequal model still uses `provider_identity_mismatch` |
| `image_ocr_contract_page_count` | Outer page count, raw `num_pages`, or retained SDK page metadata is not exactly one |
| `image_ocr_contract_page_dimensions` | A present page/element dimension has an invalid type or range, or required pixel dimensions are absent |
| `image_ocr_contract_page_dimensions_conflict` | Duplicate page dimensions disagree |
| `image_ocr_contract_index_invalid` | Index is boolean, non-integer, negative, or above the bound |
| `image_ocr_contract_index_duplicate` | Two regions use the same index |
| `image_ocr_contract_label_unknown` | Label is outside the source-specific allowlist |
| `image_ocr_contract_bbox_shape` | Bbox is present but not four finite ordered numeric coordinates |
| `image_ocr_contract_bbox_scale` | Coordinates cannot be interpreted under the selected source contract |
| `image_ocr_contract_bbox_range` | Pixel/normalized coordinates exceed validated page/source bounds |
| `image_ocr_contract_content_type` | Present content is neither null nor a string |
| `image_ocr_contract_content_limit` | Content violates length/control-character bounds |
| `image_ocr_contract_element_extra` | A region contains an undocumented key outside its source allowlist |
| `image_ocr_contract_table_unsupported` | A table region is present |
| `image_ocr_contract_formula_unsupported` | A formula region is present |
| `image_ocr_contract_line_limit` | Projection exceeds the bounded line count/length before exact comparison |
| `image_ocr_contract_sdk_error` | SDK wrapper reports failure; its error value is never inspected or emitted |

Retain `missing_visual_text`, `unexpected_visual_text`, `duplicate_visual_text`, and `misordered_visual_text` exactly for the final content gate. A tuple containing any `image_ocr_contract_*` code is parser-terminal even if an exact-text code is also derivable. Prefer returning only parser codes in that case so downstream routing cannot confuse it with a repairable OCR-content miss.

### Concrete suggested tests

All tests should use offline mocked responses and sentinel strings; none should call a live provider.

#### Raw MaaS compatibility

- A nested, one-page response with documented `[0,1]` bboxes, one-origin unique indices, optional fields, and exactly three expected text regions passes.
- A nested, one-page response with zero-origin indices and pixel bboxes bounded by `data_info.pages[0]` passes and produces the same ordered lines.
- Pixel bboxes using the official SDK test's page-sized coordinate pattern pass; a coordinate beyond page width/height fails only with `image_ocr_contract_bbox_range`.
- A raw bbox above one without both page axes fails with `image_ocr_contract_page_dimensions` or `image_ocr_contract_bbox_scale`, according to a fixed validation precedence.
- Zero- and one-origin unique indices pass. Boolean, numeric string, negative, too-large, and duplicate indices each return their exact stable code. Noncontiguous but unique indices remain valid ordering metadata.
- Omitted image `bbox_2d` and omitted/null text `content`, `height`, and `width` are tested independently. Missing text bbox fails with `image_ocr_contract_bbox_shape`; width-only and height-only metadata are accepted when no pixel bbox needs the missing axis. Conflicting fallback dimensions fail with the conflict code.
- A pixel page containing both an ordinary pixel bbox and a tiny pixel bbox whose coordinates are all at most one proves that scale is selected once per page and geometric order is preserved.
- Missing/null text content reaches `missing_visual_text`; a non-string content value fails with `image_ocr_contract_content_type`.
- A harmless bounded unknown top-level field is ignored. An unknown element field fails with `image_ocr_contract_element_extra`, and its sentinel value appears nowhere in the exception or logs.
- Raw `image` content is ignored; raw `table` and `formula` return distinct terminal unsupported codes; an unknown/case-variant label returns `image_ocr_contract_label_unknown`.

#### SDK normalized compatibility

- A one-page `json_result` with zero-origin indices and `0–1000` bboxes passes the exact gate.
- Direct `json_result` and a bounded `PipelineResult.to_dict()` wrapper follow the same normalized decoder only when the caller explicitly selects `sdk_json_result`.
- `title`, `text`, and `seal` regions project as visible text; `figure`/`image` content is ignored; `table`/`formula` are terminal.
- `header`, `footer`, `page_number`, or `reference` containing a fourth line causes `unexpected_visual_text`, proving the richer label support cannot hide visible text.
- Bboxes above `1000`, negative coordinates, reversed axes, booleans, NaN, and wrong-length arrays fail with the precise bbox subcode.
- A wrapper `error` sentinel fails with `image_ocr_contract_sdk_error`; its value is absent from exception representation and captured logs.
- `markdown_result`, `original_images`, usage, crop paths, and any future allowlisted ignored region metadata never affect recognized lines and never enter diagnostics.

#### Source discrimination, identity, and privacy

- Feeding raw pixel `layout_details` into the SDK decoder or normalized `json_result` into the raw decoder fails at the source boundary; there is no scale-driven fallback.
- A response containing both raw and normalized shapes fails with `image_ocr_contract_source_conflict`.
- Raw model case variants pass, a missing raw model returns the missing-model subcode, and a different model retains `provider_identity_mismatch` before any text handling.
- Existing exact-three-line cases remain: exact passes; missing, extra, duplicate, and misordered lines produce the existing exact issue codes.
- Inject unique sentinels into raw/SDK content, `md_results`/`markdown_result`, `error`, `original_images`, crop URL/path fields, unknown fields, response bodies, and exception causes; assert none appear in exception `repr`, structured logs, durable safe metadata, or API responses.
- Assert parser-stage codes are terminal before similarity/storage and never enter the one-repair text path, including any attempted mixture with an exact-text code.
- Assert one mocked response is sufficient to identify index, bbox scale/range, label, dimension, extra-key, and SDK-error classes; assert no automatic second provider request.

### Related specs

- `.trellis/spec/backend/visual-diversity.md:42-61` currently freezes positive-only indices, mandatory `[0,1]` boxes, and paired dimensions. The official evidence above discriminates against those three details. A future spec update should preserve its one-page, bounded, exact-text, terminal-parser, and privacy invariants while changing only the representation compatibility rules.
- `.trellis/spec/backend/visual-diversity.md:93-100` already requires malformed/unsupported layout to fail before similarity/storage; the two-decoder model retains that behavior.
- `.trellis/spec/backend/visual-diversity.md:113-130` requires provider contract coverage without ordinary live-provider calls; the suggested test matrix expands that contract gate.
- `.trellis/spec/backend/error-handling.md:39-61` requires typed provider failures and bounded content-free diagnostics while the external API stays generic. The proposed subcodes are compatible with that rule.
- `.trellis/spec/backend/logging-guidelines.md:52-64` and `:86-100` prohibit raw provider payloads, content, URLs, object keys, private paths, image bytes, and secrets. The compatibility model treats all ignored SDK/raw presentation and crop fields as tainted metadata.

## Caveats / Not Found

- No live provider call was made, and no raw production response, image, OCR text, URL, object key, request identifier, or credential was accessed or recorded. This research cannot prove which raw bbox form the current deployed MaaS service returned.
- The BigModel API bbox prose and official GLM-OCR implementation are materially inconsistent. The proposed raw dual validation is justified because both official forms preserve relative ordering and pixel form is accepted only with validated dimensions; it is not a claim that both forms are simultaneously emitted by one provider version.
- The official API schema does not state index base or contiguity. The Bayesian split for the raw base is consequently weak; accepting unique nonnegative values is safer than asserting a base.
- The SDK guide's rich label list includes “etc.” rather than a closed machine-readable enum, while the current formatter often collapses native labels. The proposed list is intentionally closed to the labels explicitly named by the guide plus `seal`, which appears in official configuration/examples; future additions require new primary evidence and tests.
- The official normalized examples show the four core region keys. No current official contract was found that guarantees arbitrary extra region keys. Unknown element keys therefore remain fail-closed; only specifically documented future metadata should be ignored.
- The official SDK wrapper may contain local filesystem paths in `original_images` and provider text in `error`/markdown. These fields are especially sensitive and must not be included in safe diagnostics even in development.
- This research recommends a compatibility/spec change but, under the Trellis research role, does not edit implementation, tests, or `.trellis/spec/` files.
