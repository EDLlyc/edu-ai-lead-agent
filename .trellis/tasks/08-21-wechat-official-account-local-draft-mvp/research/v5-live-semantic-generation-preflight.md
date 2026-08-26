# V5 live semantic-generation preflight (2026-08-25)

## Scope

This note records aggregate local preflight only. It contains no credential, provider endpoint, raw catalog ID,
private path, vector, query, prompt or provider body. No embedding or image request was made during preflight.

## Verified local state

- The approved visual manifest loads as one current catalog with exactly 41 assets, all approved.
- PostgreSQL proves exact complete coverage for all 41 current assets under the active identity:
  `alibaba-model-studio / qwen3-vl-embedding / 2048 / brand-visual-embedding-input-v2`.
- The configured Alibaba multimodal endpoint matches the reviewed Beijing REST shape and its server-side key is
  present.
- The pinned ToApis origin and server-side key are present. The ordinary configured image mode is Comfly with three
  attempts, so the v5 operator command must override only its copied settings to `toapis` and one attempt before
  constructing an image client.
- The destination `output/official-account-news-ip-editorial-semantic-generated-20260825-v5` is a new additive
  location. V1--v4 outputs remain immutable.

Frozen pre-run tree SHA-256 values (sorted file/checksum projection) are:

- v1: `91b1fcd1d4fceb415d822227bb226d581a45a482c884a484117795d90a9396f6`
- v2: `41aec85a200f24df1859cd693ef97b9efc719787d00fc013d1bba762484b4106`
- v3: `0c0b95e99302f5b5512f31028330ec6aa91eb1f41c7eb71e4620b493e562708e`
- v4: `cedfce02ab9d02ea1d516eeba656dfe7d74dcd9ed6c9d415e9d25c23fe6c4e65`

## Authorized call budget and stop rules

- Exactly two paid Qwen3-VL text embedding requests: one for the parent-question block and one for the AI/child
  responsibility block. Complete-index proof occurs before client construction.
- At most two ToApis image requests: one for each successfully selected distinct approved public reference.
- Each provider request has one attempt and no hidden retry. Any semantic failure aborts before image generation.
  Any image timeout becomes `result_unknown`; any known typed rejection becomes `failed`; neither installs a ready
  bundle or permits an automatic replacement call.
- WeChat, WeCom, source-fetch, article-model, publish and send calls stay zero and their clients remain unconstructed.

## Completed live-local result

- Ready output: `output/official-account-news-ip-editorial-semantic-generated-20260825-v5`
- Actual external calls: two Qwen3-VL text embeddings; two ToApis image attempts; two image successes; no retry.
- Selected safe public refs: `079e5e02b1769f2a` and `a283092c9925185c`; both similarity bands are `medium` and
  neither appears in the three inherited v1 reference rows.
- Output: 21 files, five distinct metadata-free 1536x1024 JPEGs, ready manifest and deterministic ZIP.
- Tree SHA-256: `4ad903d90961545e469edacfe895bbd66fb1b1ec43a35382ab37d4b918e490c4`.
- ZIP SHA-256: `dc57bcc9d01bc5658fa06a04b8e57eb515ea7e5e0d002970e798653f61ce9908`.
- Manifest SHA-256: `23836fbfa958515c3f9d4ffad91a16c53f94eb29007207a4b6ef0937f9b9cc0d`.
- Browser acceptance at 430 px and 320 px: five loaded images, one `h1`, two semantic generated-scene modules,
  zero catalog cutaways, no horizontal overflow and zero external requests.
- Local visual inspection: both new images show a clear 小赛／赛先生 protagonist and no readable words, logo,
  watermark or QR code. Body-3 includes a non-text pictogram process overlay; body-4 shows a concrete observation/
  experiment scene. This observation is acceptance evidence, not a new image-level human approval gate.
- V1--v4 post-run tree SHA-256 values exactly match the frozen pre-run values. WeChat, WeCom, Comfly and publish
  calls are all zero. No commit was created.
