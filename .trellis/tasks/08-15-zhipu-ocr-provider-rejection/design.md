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

第二次单次 live fixture 进入修正后的 nested parser，但只留下 content-free
`image_ocr_layout_invalid`。该信号无法在 zero-based index、raw pixel bbox、独立可选字段、
label drift 与真正 malformed content 之间形成 Bayesian 区分。新的官方源码审查显示：
OpenAPI 未规定 index base，官方 SDK examples/mocks 使用 0；API 文档描述 `[0,1]` bbox，
但官方 MaaS converter/tests 明确把 raw bbox 当作 pixels，再依据 `data_info.pages` 归一化。
因此本轮不是猜测实际 live body，而是实现同时覆盖两个官方 raw 表示、仍然 fail-closed 的
兼容边界，并拆分 content-free parser subcodes。不得为验证猜测而重试 provider。

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
  必须恰有一个包含正整数有限尺寸的页面，并作为 raw pixel normalization 的权威尺寸；
  若兼容性 `page_count` alias 出现则必须同样为 1，不能静默忽略冲突。
- 每个元素必须具有唯一、bounded、nonnegative integer index；允许 0/1 origin 与 gaps，
  不把 index base 当成排序语义。raw labels 只允许 `text/image/table/formula`，unknown 或
  case variant terminal。
- `text` 必须有可用四元 bbox。scale 在整个 raw page 上只选择一次：所有 text 坐标均在
  `[0,1]` 时按 API 文档解释；任一 text 坐标大于 1 时，全部 text bbox 都按 MaaS raw
  pixels 解释，并且只有两个正页面轴都可确定且 x/y 未越界时才接受。这样同页一个恰好
  `<=1` 的小 pixel bbox 不会被当成 unit bbox 而与其他 pixel bbox 混序；如果所有 bbox 都
  `<=1`，两种解释只相差相同的正轴缩放，几何顺序不变。绝不猜测 unbound `0–1000` 或
  其他 scale。element `height`/`width` 是 OpenAPI 明示的独立可选 page-axis metadata；
  `data_info.pages` 缺失时，仅以无冲突的 element axis 作 fallback，不要求 element 与 page
  metadata 相等。
- 只投影 `label=text`。按 normalization 后的 `(y1, x1, index)` 排序，对 bounded string
  content 仅做 CRLF/Unicode 空白规范化并拆分非空行；missing/null text content 投影为空并
  进入既有 missing-text gate。`image` 的 optional/opaque content 与 bbox 被忽略且不记录/
  持久化，`table` 和 `formula` 使用独立 unsupported code fail closed；不使用 `md_results`。
- raw response/data/page 的普通 provider extension 在 1 MiB response ceiling 内丢弃；
  element 只允许 OpenAPI 的六个键，未知 element key 以独立 content-free code terminal，
  防止 alternate label/content 语义被 `extra="ignore"` 隐藏。`json_result` 或 `error` 与 raw
  success envelope 共存时同样以 source-conflict terminal；单独的 normalized/error envelope
  以 source-invalid terminal。所有 extension value 均不被投影、记录或持久化。
- 最多输出 8 行；重复、缺失、额外或乱序继续交给
  `validate_exact_visual_text(..., require_order=True)` 判定。
- provider model 允许大小写规范化后精确匹配 `glm-ocr`，持久化仍使用配置中的规范值；
  不接受其他模型或多页/异常布局。
- 解析失败只暴露稳定 allowlisted stage issue，至少区分 source invalid/conflict、schema、
  page count、dimension/conflict、index/duplicate、label、bbox shape/scale/range、content
  type/limit、element extra、line limit 与 table/formula；不携带 provider content、URL、
  Base64、请求体或原始异常。
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
| Flat/multi-page/normalized-conflicting envelope or invalid page count/schema | Granular terminal invalid-output |
| Invalid/duplicate index or unknown raw label | Granular terminal invalid-output |
| Unit bbox or dimension-bounded raw pixel bbox | Deterministic normalization and geometric ordering |
| Invalid bbox, unbound scale, out-of-page range or invalid/conflicting fallback dimensions | Granular terminal invalid-output |
| Invalid text content or unsupported table/formula | Granular terminal invalid-output |
| Optional/opaque `image` content/bbox and bounded outer provider extensions | Ignored without projection/logging/persistence; unknown element keys are terminal |
| Missing/extra/duplicate/misordered text | Existing exact OCR quality failure/recovery path |
| OCR passes | Continue to similarity and storage; OCR never directly creates delivery eligibility |

No Alembic or OpenAPI change is expected. If implementation discovers either is required, stop and
return to planning rather than expanding scope.

## 5. Test design

- Unit/contract tests use `httpx.MockTransport` for exact URL, headers, Base64 bytes, model,
  disabled visualization fields, response bounds, official normalized and MaaS pixel raw shapes,
  zero-/one-origin indices, page-level scale selection for small pixel boxes, optional fields,
  ignored outer/rejected element extensions, element/page dimensions, layout sorting, non-text
  policy, granular stage classification and every error row above.
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

The source archive's reviewed `0644/0664` and `0755/0775` classes describe candidate executable
semantics, not permission widening for the active tree. Before quiesce, every exact existing path
must be a regular anchored file owned by the reviewed application owner/group and use only
`0600/0644` for non-executable content or `0700/0755` for executable content. The driver binds that
exact destination mode to the candidate semantic evidence and preserves it through atomic overlay;
a stricter `0600/0700` destination is never broadened to `0644/0755`. Group/world-write, special or
unknown destination modes, class/ownership/path drift and preflight-to-overlay changes fail closed.

Atomic payloads are staged only below fixed `/var/backups/edu-ai/releases`, never below a path
derived from `/opt`. Before any stop, that exact root must be a physical non-symlink `root:root`
mode-0700 directory on the application device with no stale reserved-prefix child. Generated
children use an exact six-alphanumeric suffix, are root:root 0700, prefix-disjoint from rollback
IDs, and are revalidated before `mv -T`. The stale scan propagates scan errors and rejects any
reserved-prefix object without printing its name; trap cleanup deletes only an exact physical
direct generated child and does not traverse a changed or symlink root.

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

## 8. User-authorized final fast-path release

After the reviewed atomic driver repeatedly recovered safely at operator-only source-install
guards, the user explicitly authorized one narrower final production path. This was an operational
exception to the complex driver, not a weakening of its reusable contract: the exact inactive
candidate, protected source archive and 307-entry checksum manifest remained the release inputs;
both image-diversity and OCR flags remained false; and no fixture, provider call, enqueue, retry,
resend or manual delivery was permitted.

The fast path required a terminal ordinary business baseline before any stop. It then acquired the
backup lock, quiesced the same eight application services, created a unique PostgreSQL/source/env/
marker/tag rollback set, and retained the earlier full MinIO/brand rollback because this release
neither migrated nor modified object data. The source archive was overlaid directly at the physical
application root by root with `umask 077`, `tar --no-same-owner --no-same-permissions`, followed by
all 307 checksum checks. Full/short markers and the shared plus nine service tags were advanced only
after the backup completed. Migration remained an Alembic-0021 no-op, services were recreated in
dependency order with the dispatcher last, and a 15-second stable counter gate closed the release.

Any failure after quiesce was required to stop candidate services, restore source/env/release/
markers and all active tags from the fast backup, recreate the previous services with the
dispatcher last, verify counters, and stop without a second attempt. The path deliberately skipped
another OCI/full-candidate/307-topology run and another MinIO/brand mirror because those inputs and
gates were already independently frozen and the authorized mutation did not touch object storage.

## 9. One-shot live OCR activation gate

After the default-off release, the user separately authorized one paid `glm-ocr` fixture attempt
and activation only after an exact three-line ordered PASS. The bounded runner used the exact active
candidate image, a deterministic protected 1024-pixel PNG, `AI_MAX_ATTEMPTS=1`, and direct
`ZhipuImageTextRecognizer` execution. It had no database, MinIO, Comfly, news or WeCom workflow and
was not allowed to enqueue, retry, regenerate, resend or activate on an unknown result.

The initial remote preparation stopped before Docker because its protected minimal environment had
13 lines while the wrapper asserted 12; cleanup completed and no HTTP request was started. After
that local assertion was corrected, the sole authorized Docker invocation returned only the safe
cleanup marker and outer exit status 1. It emitted none of the required typed OCR fields. Because
the wrapper removed its protected stderr and did not print the captured Docker status on that
failure path, both the exact Docker exit code and whether an HTTP request crossed the provider
boundary are unknown. Under the gate contract, unknown is failure: no second call is permitted and
the production flags must remain `false:false`.

Failure-state verification therefore replaces the activation branch. It requires exact fixture and
container cleanup, two stable service samples, healthy API, unchanged candidate/restart counts,
false API/worker flags, and zero durable/provider/WeCom aggregate deltas. A future attempt, if ever
separately authorized, must first preserve a typed pre-request marker and always surface the Docker
status and counted HTTP-attempt result without exposing provider bodies or credentials.

## 10. User-authorized activation without another paid fixture

The user subsequently lowered the activation acceptance boundary and explicitly authorized turning
the feature on without another provider fixture. A fresh official-contract review confirmed that
the c66 adapter's `/layout_parsing` endpoint, `glm-ocr` model, private data-URI request, 10 MiB
input limit and raw `layout_details` pages-to-elements shape match the current provider contract.
The prior unknown result remains a wrapper-observability failure and is not evidence of a provider
or adapter rejection.

The minimal activation contract allows no provider, fixture, queue or delivery action. Both feature
keys must be absent from the primary and release env files and runtime must still resolve the safe
Compose defaults. Activation then protects the exact primary env, appends only the two explicit
`true` assignments, renders Compose, and recreates only acquisition API and content worker with
`--no-build --no-deps`. The dispatcher is neither stopped nor recreated. Runtime must retain the
exact candidate, restart zero, healthy API, `glm-ocr` limits, one regeneration and disabled quality
audit. A 15-second gate requires unchanged provider and WeCom aggregates and zero running work.

Any failure after the env move restores the protected original bytes atomically and recreates those
same two services on their default `false:false` contract. The retained env backup is the activation
rollback artifact; this exception does not authorize a paid test, manual enqueue, retry, resend or
delivery.
