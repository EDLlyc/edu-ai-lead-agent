# Design: IP 资产演示加固

## 1. Architecture and boundaries

继续扩展现有 IP 资产垂直切片，不创建第二套图库或身份系统。后端只增加缩略图派生读路径；前端优化列表请求量、检索表达、选择反馈、演示名片和相册控制；运维层增加只读预检。

```text
verified immutable original
  -> thumbnail policy v1 (max edge 640, WebP)
  -> content-addressed private MinIO object
  -> existing ip_asset_derivatives row
  -> /{asset_ref}/thumbnail?v=1 + cache headers

gallery/search/picker card -> thumbnail_url
detail/private media/flipbook/download -> existing preview_url/download_url

make ip-asset-demo-preflight
  -> capabilities + compose/process state + gallery + thumbnail + read-only search
  -> pass/fail summary, no durable mutation
```

## 2. Thumbnail contract

- Add a fixed `IP_ASSET_THUMBNAIL_POLICY_VERSION` and pure thumbnail encoder in the IP asset domain/service boundary. It normalizes EXIF orientation, uses a copied RGB/RGBA raster, calls `thumbnail((640, 640), LANCZOS)`, never upscales, and emits deterministic WebP with bounded settings.
- Extend the store with a derivative put path under `ip-assets/derivatives/<policy>/sha256/<prefix>/<sha>.webp`. The existing verified read must accept only either the exact original key shape or exact versioned derivative key shape; arbitrary keys remain rejected.
- Extend the repository with get/create derivative methods mapped to the existing table. Creation uses a PostgreSQL advisory lock or conflict-safe insert, checks asset/source/policy/kind, and returns the canonical row after concurrent replay.
- `IpAssetService.thumbnail()` resolves the same shared-or-profile access as `original()`, requires `ready`, tries the persisted derivative first, verifies object bytes, and otherwise generates/stores/inserts once. Provider calls and download counters are not involved.
- Add `thumbnail_url` to `IpAssetCardResponse` and a typed `GET /{asset_ref}/thumbnail?v=1` endpoint. The response uses `image/webp`, content length, derivative ETag, `Content-Disposition: inline`, and `Cache-Control: private, max-age=604800, immutable`.
- Keep `preview_url` unchanged for compatibility and high-quality detail/flipbook/private reads.

## 3. Search and presentation

- Frontend list/personal page size becomes 16; text/image search request size becomes 8.
- `_explanation()` stops embedding the numeric cosine value. It appends a bounded “画面语义相关” reason when a vector hit exists, while metadata matches remain explicit and authoritative.
- Search cards render a small “含画面语义线索” label whenever `similarity !== null`, but never render the float. The API retains the numeric field for backward compatibility and diagnostics; only the demo UI hides it.
- Example prompts are a data-driven constant rendered as buttons below the search hint. Activation changes only the controlled input value and announces the change through the visible helper/status surface.

## 4. Frontend interaction changes

- `AssetPreview` chooses `thumbnail_url` for grid cards and `preview_url` for detail. Shared creation picker cards and leaderboard use the thumbnail projection; private personal preview code remains header-bearing and unchanged.
- Selection control becomes a compact labeled pill with `选择` / `✓ 已选`; native checkbox and accessible name remain authoritative.
- Mobile CSS removes the leaderboard's negative order so the DOM's gallery-first order is preserved.
- Flipbook previous/next buttons move inside `bookStage` as absolute overlay controls with 44px+ targets. A separate below-stage hint remains; button handlers, disabled state and tests reuse existing controller methods.
- `ProfileSetupDialog` factors one `bootstrapProfile(displayName, department)` path used by both the form and a preset “使用演示名片” button. Preset values are `演示用户` and `品牌中心`; it does not reuse login input.
- Creation prompt becomes controlled local state so “载入示例简报” can fill it and announce the action without submission.

## 5. Demo preflight

- Add one small Python entry under `scripts/` plus `make ip-asset-demo-preflight`.
- It calls loopback endpoints with bounded timeouts, checks `docker compose ps --format json` (or a safe process fallback where documented), requires one effective running `ip-asset-worker`, verifies capability truth, fetches one gallery page, fetches one card thumbnail and validates WebP/cache headers, and sends one bounded text-search POST.
- Search is read-only and preview thumbnail generation may materialize a deterministic derivative, but the command creates no user/business asset, generation job, favorite, download aggregate or profile.
- Output contains only service names, safe refs/counts/status and the browser URL; never credentials, profile token, full provider body, object key or user prompt.

## 6. Compatibility, rollback and risk

- OpenAPI addition is backward-compatible; existing clients can ignore `thumbnail_url`.
- The existing derivatives table means no Alembic migration is needed. Rollback can stop emitting/using `thumbnail_url`; unused derivative objects/rows are safe immutable cache artifacts and need not be deleted.
- Thumbnail risk is image CPU/memory on a cold library. Reuse the existing upload semaphore or a dedicated bounded in-process semaphore and run Pillow work in a thread. First page size 16 bounds burst size.
- Store verification must not weaken the original exact-key invariant when adding derivative keys.
- Frontend changes preserve the current editorial/soft-craft visual direction and avoid a dashboard redesign.
