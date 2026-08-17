# Design — 图片供应商输出容错与品牌素材兜底

## Decision Summary

采用三层顺序：`URL contract → one durable representation recovery → approved catalog fallback`。

不在解码器里猜测或清洗非法 Base64，也不把 data URI 当成 Base64 字符串偷偷剥头。传输格式异常仍是失败；可靠性由有界状态机和已审核素材补偿，而不是降低验证标准。

## Data Flow

1. `OpenAICompatibleImageGenerator._payload()` 请求 `response_format=url`。
2. 适配器按现有闭集解析 direct raster / JSON URL / JSON Base64 / documented task result。
3. URL 走现有安全下载和栅格验证；合法 Base64 走严格解码和相同栅格验证。
4. 非空 `b64_json` 严格解码失败，抛出 `ImageOutputValidationError(reason=image_output_representation_invalid)`，不附带原值。
5. `MaterialPackageExecutor` 只针对该 reason：
   - recovery counter=0：持久化一次恢复并排队；
   - recovery counter=1：不再调用 provider，调用现有 `_persist_catalog_fallback()`。
6. 兜底成功后 artifact/package 使用现有 direct-delivery-compatible 状态；失败则维持 review/failed。

## State and Compatibility

- 不加 DB 字段。复用 `provider_rejection_retry_count` 的 0/1 约束和现有 claim budget；这是兼容字段名，其新语义是“供应商拒绝或图片表示异常的单次输出恢复”。
- `_schedule_provider_rejection_retry` 应收敛为可接收 safe `initial_error_code`/recovery kind 的内部 helper；旧 provider rejection 行为保持原样。
- claim projection 从 package fallback snapshot 恢复 safe initial error：
  - `image_provider_rejected`：继续使用现有 neutralized prompt；
  - `image_output_invalid`：保留当前视觉方案和 prompt，只派生新的 provider request fingerprint。
- `_provider_request_fingerprint()` 对两类 recovery 都必须与首请求不同，防止供应商幂等缓存返回同一坏响应；重放同一 recovery 时仍得到同一指纹。
- 现有 API 的 `neutralized_retry`/counter 不新增枚举，避免 OpenAPI 和前端漂移；`initial_error_code` 提供准确原因。

## Failure Classification

仅 `ImageOutputValidationError.reason == image_output_representation_invalid` 进入输出恢复。

以下仍 fail closed，不能借 catalog 掩盖：

- `image_download_url_invalid` / `image_download_address_invalid`
- redirect、显式非图片 media type 或 media-type/signature mismatch
- `image_download_too_large`
- `image_raster_signature_invalid`
- `image_dimensions_invalid`
- provider identity mismatch
- OCR parser/security/integrity failures

普通 provider rejection 仍按原“一次 neutralized retry → catalog”路径；网络 transient 仍按 `image_max_attempts`，耗尽后按现合同 fallback。

## Safe Diagnostics

- 适配器不返回 representation 值或 URL。
- application 只记录 safe reason `image_output_representation_invalid`、attempt、counter、next action 和主 provider/model。
- validation snapshot 延续现有 `provider_output` stage；fallback snapshot 只记录已审核资产的安全标识、basename、checksum、role 和 selection reason。

## Test Design

### Adapter contract

- payload URL contract；URL success。
- provider 尽管请求 URL 仍返回 valid Base64：兼容成功。
- invalid Base64 产生精确 safe reason，exception/string/log 不含 sentinel。
- unsafe URL、redirect、non-image、oversize、bad signature/dimensions 仍拒绝。

### Material state machine

- representation invalid #1：一次 durable queued recovery，counter=1，safe initial error，prompt unchanged，fingerprint changed。
- recovery succeeds：正常生成图路径，不触发 catalog。
- representation invalid #2：catalog success，不第三调 provider。
- missing/corrupt catalog/store error：typed review/failed。
- provider rejection 和 exhausted transient 旧矩阵不变。

### Delivery and idempotency

- direct-mode delivery query accepts catalog fallback package exactly once。
- replay/lease loss/concurrency does not duplicate provider call/storage/job。
- tests inspect safe projections and logs for raw sentinel absence。

## Migration and Release Impact

- Alembic: none.
- Runtime dependencies/locks: none.
- Production API/OpenAPI/frontend schema: none expected; drift gates prove it.
- Runtime services affected by code: content-worker; acquisition-api only for existing projections/routes if shared imports change. Deployment is a separate task.
