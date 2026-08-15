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
