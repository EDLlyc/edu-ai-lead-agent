# 智谱 OCR 请求拒绝诊断与修复 — Design

## 1. Scope and boundary

本任务只替换受控图片文字识别的供应商适配层，并完成一次隔离上线验收。文本生成继续使用
`glm-5.2`；品牌 PDF OCR 继续使用现有 `glm-ocr` adapter；图片生成继续使用 Comfly；图片
质量 AI audit 保持关闭。公共 API、数据库 schema、三槽内容与企微策略均不改变。

根因是 capability routing，而不是提示词或图片质量：当前 factory 把
`AI_CHAT_MODEL=glm-5.2` 注入包含 `image_url` 的 OCR chat request。新设计用独立
`IMAGE_OCR_MODEL=glm-ocr` 调用智谱 `/layout_parsing`，不再让图片 OCR 经过文本模型。

第一次单次 live fixture 已证明 capability routing 修复生效，但 provider 的成功响应被
本地 parser 以 `invalid_provider_output` 拒绝。第二轮离线根因是 response envelope drift：
官方 `layout_details` 是 pages-to-elements 的 `object[][]`，`data_info.pages` 是页面对象数组，
而已部署 parser 分别按 flat elements 和整数解释；同时它因 `extra="forbid"` 拒绝官方
element `height`/`width`，并把有内容的 `image` element 错判为 schema failure。

## 2. Components and ownership

### 2.1 Settings and deployment contract

新增四个默认安全、范围有界的配置：

- `IMAGE_OCR_MODEL=glm-ocr`：只接受无空白、最长 120 字符的标识；启用受控视觉时必须
  精确等于当前审核版本 `glm-ocr`。
- `IMAGE_OCR_MAX_INPUT_BYTES=10485760`：图片原始字节上限，匹配供应商单图 10 MiB。
- `IMAGE_OCR_MAX_RESPONSE_BYTES=1048576`：关闭 crop/layout visualization 后的响应上限。
- `IMAGE_OCR_TIMEOUT_SECONDS=120`：连接超时仍复用 `AI_CONNECT_TIMEOUT_SECONDS`；总/read
  OCR 窗口使用此值。

`.env.example`、acquisition API、content worker、Doctor 和 production evidence 必须投影
同一组值。`IMAGE_OCR_ENABLED=false` 时新设置仍可解析但不会创建 adapter 或发起调用；
`IMAGE_DIVERSITY_ENABLED=true` 仍要求 OCR 同时开启。

### 2.2 Provider adapter

在智谱 provider 模块新增 `ZhipuImageTextRecognizer`，实现既有
`ImageTextRecognizer` protocol；不改变 application service 或 API。

请求：

```json
{
  "model": "glm-ocr",
  "file": "data:image/png;base64,<bounded bytes>",
  "return_crop_images": false,
  "need_layout_visualization": false
}
```

- 只接受 PNG/JPEG；受控生成当前可能得到 WebP，但 adapter 在 provider 前拒绝 WebP，
  由既有 typed quality failure 收口，而不是私自转码。
- 请求前验证非空字节、媒体类型、图片输入上限与 JSON 编码后的总大小。
- 使用既有 `_post_json_with_retries`、Bearer 认证、响应字节上限、并发与 typed provider
  error mapping。禁止记录 response body。

响应：

- `layout_details` 必须是严格的 pages-to-elements 二维数组且仅有一页；只 flatten 这唯一
  一页。flat legacy shape、空/多页 outer array 或超限 page elements 均 fail closed。
- `data_info` 使用 typed `num_pages` 和可选 `pages`：`num_pages` 必须为 1；`pages` 存在时
  必须恰有一个包含正整数有限尺寸的页面，并与 element 页面尺寸一致。
- 每个元素必须具有唯一正整数 index、官方 allowlisted label、有限且在 `[0,1]` 内的四元
  `bbox_2d`、有界 content，以及可选但成对出现的正整数 `height`/`width`。
- 只投影 `label=text`。按 `(y1, x1, index)` 确定排序，对每个 content 仅做 CRLF/Unicode
  空白规范化并拆分非空行；有界 `image` content 被忽略且不记录/持久化，`table` 和
  `formula` 作为未支持的结构 fail closed；不使用 `md_results`，避免 Markdown 标记污染
  精确文字。
- 最多输出 8 行；重复、缺失、额外或乱序继续交给
  `validate_exact_visual_text(..., require_order=True)` 判定。
- provider model 允许大小写规范化后精确匹配 `glm-ocr`，持久化仍使用配置中的规范值；
  不接受其他模型或多页/异常布局。
- 解析失败只暴露稳定 allowlisted stage issue：response envelope、page metadata、layout 或
  unsupported layout；不携带 provider content、URL、Base64、请求体或原始异常。
- `material_package` 只把 missing/unexpected/duplicate/misordered 四类 exact-text code 送入
  既有一次质量修复；任何 parser-stage code（包括与 text code 混合的 tuple）均在
  similarity/storage 前终止，只能进入既有安全 validation snapshot。

### 2.3 Factory routing

`create_image_text_recognizer` 仅在 `IMAGE_OCR_ENABLED=true`、
`AI_PROVIDER_MODE=zhipu`、真实图片 provider、有效 client/base URL/key 时创建
`ZhipuImageTextRecognizer`。图片质量 auditor 继续走原有 OpenAI-compatible adapter，
并保持 `IMAGE_QUALITY_AUDIT_ENABLED=false`；本任务不得将其误接到 `glm-ocr`。

## 3. Data flow

```text
validated generated PNG/JPEG
  -> ImageTextRecognitionRequest (bytes + expected 3 lines + order=true)
  -> Zhipu /layout_parsing (glm-ocr, no public URL)
  -> bounded layout_details
  -> deterministic text-line projection
  -> existing exact visual-text validation
  -> existing validation snapshot / typed failure
  -> similarity only after OCR passes
  -> MinIO write only after every required gate passes
```

No database transaction encloses the provider call. No provider payload or output is added to
the public API, durable metadata, or logs.

## 4. Error and compatibility matrix

| Condition | Result |
| --- | --- |
| Feature off / historical v1 | Existing behavior; no OCR client/call |
| `glm-5.2` remains text model | Copy/governance unchanged |
| Empty, PDF, WebP, oversized or malformed raster input | Provider-input typed failure before HTTP |
| 400/422 unsupported request | `provider_request_rejected`, no raw body |
| 401/403 | `provider_authentication_failed` |
| 429/timeout/5xx | Existing bounded retryable classification |
| Wrong provider model | Terminal identity mismatch |
| Flat/multi-page envelope or invalid/conflicting page metadata | Stage-classified terminal invalid-output |
| Invalid index/bbox/content/dimensions or unsupported table/formula | Stage-classified terminal invalid-output |
| Bounded `image` element content | Ignored without projection, logging or persistence |
| Missing/extra/duplicate/misordered text | Existing exact OCR quality failure/recovery path |
| OCR passes | Continue to similarity and storage; OCR never directly creates delivery eligibility |

No Alembic or OpenAPI change is expected. If implementation discovers either is required, stop and
return to planning rather than expanding scope.

## 5. Test design

- Unit/contract tests use `httpx.MockTransport` for exact URL, headers, Base64 bytes, model,
  disabled visualization fields, response bounds, official nested layout/page shape, element/page
  dimensions, layout sorting, non-text policy, stage classification and every error row above.
- Factory/config tests prove `AI_CHAT_MODEL=glm-5.2` and `IMAGE_OCR_MODEL=glm-ocr` remain separate,
  and quality auditor routing is unchanged.
- Material worker fake-provider tests prove exact ordered OCR precedes similarity/storage and no
  third image call exists.
- Compose/Doctor/evidence tests prove API/content worker equality and secret-free output.
- Full backend, frontend contract-only, release, lock, Compose, Doctor, shell and diff gates run
  before deployment. Frontend stays local-only and is not deployed.

## 6. Deployment and bounded live acceptance

ACR remains unavailable, so deployment uses the already reviewed offline source-overlay path:
build and validate one immutable local image, capture backup/rollback artifacts, quiesce downstream
services, recreate the nine backend/migration service tags from the same target image ID, migrate
(expected no-op at Alembic 0021), then restore services in dependency order. No frontend artifact
is built into or copied to production.

Live gates are sequential and stop on first failure:

1. With production delivery/schedulers unable to act, generate a protected local 1024×1024 PNG
   containing the exact three approved lines. Invoke exactly one logical `glm-ocr` request through
   the deployed adapter. Require exact ordered result and delete the fixture.
2. Reuse the previous clone/temporary-bucket pattern for exactly one real accepted news item.
   Maximum two image generations, one OCR logical call per image, no quality audit, no copy call,
   no WeCom row/call, and no second news. Download and manually inspect only the final isolated image.
3. Only if machine and visual gates pass, atomically set both production flags true, recreate API
   and content worker, restore schedulers, then dispatcher last. Do not enqueue/resend. Sample for
   30 seconds and require stable counters except ordinary scheduler work explicitly attributable
   to the current business date.

## 7. Rollback

- Any code/live gate failure before activation: keep flags false, restore stopped services, remove
  exact temporary DB/bucket/fixture/container, preserve typed evidence, and stop.
- Any failure after env edit: atomically restore the mode-600 env backup, recreate only affected
  services on the previous verified image, then restore dispatcher last.
- Unknown provider/delivery state is failure; do not retry another item or manually send.
