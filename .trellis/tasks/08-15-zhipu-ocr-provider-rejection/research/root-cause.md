# Root-cause evidence

## Repository and production evidence

- `backend/app/infrastructure/ai/factory.py::_create_image_validation_provider` passes
  `settings.ai_chat_model` into the image OCR adapter.
- `backend/app/infrastructure/ai/image_validation.py` posts an `image_url` content part to
  `{AI_PLATFORM_BASE_URL}/chat/completions`.
- A bounded production Settings probe on 2026-08-15 returned provider `zhipu`, chat model
  `glm-5.2`, base host `open.bigmodel.cn`, base path `/api/paas/v4`, and both production image
  flags false. No secret was read or printed.
- The archived acceptance result records one successful 1024×1024 media validation followed by
  one `provider_request_rejected` OCR terminal, with no stored image or retry.

## Official provider evidence

- [GLM-5.2](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.2) lists input modality as text and
  output modality as text.
- [GLM-5V-Turbo](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5v-turbo) documents
  `/chat/completions` with `image_url`, including Base64 image input.
- [GLM-OCR](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-ocr) is the provider's dedicated OCR
  model and supports PDF/JPG/PNG.
- [Document parsing API](https://docs.bigmodel.cn/api-reference/%E6%A8%A1%E5%9E%8B-api/%E6%96%87%E6%A1%A3%E8%A7%A3%E6%9E%90)
  fixes the model to `glm-ocr`, accepts URL or Base64, caps a single image at 10 MB, and returns
  bounded `layout_details` with element index, label, normalized `bbox_2d`, and content.

## Root-cause conclusion

The rejection is explained by a deterministic capability mismatch, not by OCR text quality:
the application sent a multimodal `image_url` request to the text-only `glm-5.2` model. The
smallest provider-aligned fix is a separate image OCR model/adapter using `glm-ocr` and
`/layout_parsing`; text generation remains on GLM-5.2.

## Second iteration after the one-call live fixture

The first bounded fixture used the corrected `glm-ocr` capability and reached one HTTP provider
attempt, but the adapter returned `invalid_provider_output`. No raw response body was captured, so
the diagnosis is based only on official contract evidence and the deployed parser's deterministic
schema:

- The official document-parsing response defines `layout_details` as `object[][]`: outer pages,
  then elements. The deployed `_ImageOcrResponse` expected a flat element list.
- Official `data_info.num_pages` is an integer, while `data_info.pages` is an array of page objects
  with positive `width` and `height`. The deployed page-count helper treated `pages` as another
  integer alias and rejected the documented array.
- Official layout elements include page `height` and `width`; the deployed element model used
  `extra="forbid"` without those fields, making the documented example invalid locally.
- Official `image` elements may carry bounded content such as an image reference. The deployed
  projection rejected any non-empty non-text content even though it was neither projected nor
  needed for the exact-text gate.

These are sufficient independent offline causes for the observed generic terminal. The corrected
boundary must accept only one nested page, type and cross-check page metadata/dimensions, ignore
bounded `image` content, reject `table`/`formula`, and retain the exact ordered text gate. Stable,
content-free parsing-stage issue codes are added so a future bounded gate can distinguish envelope,
page-metadata, layout, and unsupported-structure failures without exposing provider data.

## Third offline iteration after the second one-call fixture

The nested-envelope correction reached the raw response parser, but the second bounded fixture
again failed closed with only `image_ocr_layout_invalid`. No raw response or recognized content was
captured. That single broad code is equally predicted by several incompatible hypotheses, so it
does not identify which representation the provider returned.

Pinned official BigModel and `zai-org/GLM-OCR` sources add the following discriminating evidence:

- Raw `index` is an integer with no published minimum/base/continuity invariant. Official SDK
  examples, formatter output, MaaS mocks, and converter paths use or preserve index `0`, while the
  API example uses `1`. Requiring positive one-origin indices was an implicit assumption.
- The API prose describes raw `bbox_2d` in `[0,1]`, while the official MaaS converter and its unit
  tests consume raw pixel coordinates and divide x/y by `data_info.pages` width/height. Requiring
  unit coordinates rejected an officially executable raw path.
- Raw `bbox_2d`, `content`, `height`, and `width` are independently optional in the official schema
  and Python response types. Requiring bbox/content for ignored images or paired element dimensions
  was stricter than the provider contract.
- Raw MaaS labels remain the explicit four-value vocabulary `text/image/table/formula`. The richer
  SDK `json_result` vocabulary is not accepted by this direct HTTP adapter, and normalized SDK
  output is not auto-detected from coordinate magnitude.

### Bayesian update

These values describe confidence in the offline compatibility propositions, not a claim about the
private body returned by the second live call:

| Proposition | Posterior | Discriminator |
| --- | ---: | --- |
| Raw nested pages and exactly one image page are required | 99.5% | OpenAPI, SDK converter, and examples agree |
| Raw MaaS can emit page-bounded pixel boxes | 82% | Official converter formula and full-page pixel unit test; API prose conflicts |
| Raw MaaS can emit documented `[0,1]` boxes | 15% | Explicit API prose; executable examples favor pixels |
| Raw index must accept both zero- and one-origin values | 99% | No schema minimum plus official examples for both |
| Raw fields are independently optional | 98% | OpenAPI required set and official SDK response types |
| The second live failure was specifically bbox scale | Undetermined | Broad prior code has no likelihood-ratio value among parser hypotheses |

The safe correction therefore accepts only the union of two officially supported raw bbox forms:
unit coordinates, or pixels with deterministic positive page axes and range checks. It accepts
bounded unique nonnegative indices without continuity, retains the four-label raw mapping, ignores
image-only and outer extension values without projection, rejects unknown element semantics, and
never guesses an unbound scale. Scale is selected once for the entire text page so a tiny pixel
bbox at or below one cannot be mixed with ordinary pixel boxes and change geometric order. This is
a metadata compatibility change; exact visible three-line acceptance is unchanged.

## Break-loop analysis

### 1. Root-cause categories

- **B — Cross-layer contract:** the private raw HTTP boundary was modeled from one documentation
  example while the provider's official executable converter implemented another coordinate form.
- **D — Test coverage gap:** local fixtures mirrored one-based unit-bbox assumptions rather than
  including official SDK zero-index/pixel fixtures.
- **E — Implicit assumption:** index base, mandatory bbox, paired dimensions, and element/page
  equality were treated as invariants without a versioned provider guarantee.

### 2. Why prior fixes did not close the loop

1. Capability routing fixed the original 400/422 rejection but could not validate the successful
   response representation.
2. The nested-envelope correction fixed four real schema mismatches but retained narrower index,
   bbox, optional-field, and dimension assumptions.
3. Broad parser-stage codes protected privacy but collapsed every remaining hypothesis, so the
   second paid observation could not discriminate a next fix.

### 3. Prevention mechanisms

| Priority | Mechanism | Specific action | Status |
| --- | --- | --- | --- |
| P0 | Architecture | Keep raw MaaS and future SDK-normalized decoders as explicit boundaries; never scale-detect an envelope | Done for raw boundary |
| P0 | Test coverage | Pin normalized-doc and executable pixel fixtures, zero/one index origins, optional fields, and every granular parser code | Done |
| P0 | Runtime safety | Make every parser code terminal before repair/similarity/storage and retain default-off live gates | Done |
| P0 | Parser discrimination | Choose raw bbox scale once per page; reject unknown element keys and raw/normalized/error source conflicts with content-free codes | Done in independent review |
| P1 | Documentation | Record source hierarchy, coordinate conflict, privacy treatment, and exact-gate invariants in the backend spec | Done |
| P1 | Review | Require primary-source executable examples when provider prose and generated types disagree | Required by spec |

The implementation intentionally does not retry the provider, infer the second response body, add
SDK fallback, widen the raw label enum, or change public API/database contracts.
