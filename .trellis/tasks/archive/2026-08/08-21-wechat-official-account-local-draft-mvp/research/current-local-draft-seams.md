# 当前代码复用边界与实现证据

## Existing input and lineage

- `backend/app/schemas/material_package.py:202-231` 已提供素材包列表/详情的稳定 API 投影；详情包含
  topic、copy、sources、brand bindings、validation、audit、versions 和 image。
- `backend/app/application/services/material_package.py:3600-3685` 构造的持久化快照保存 claim 类型、
  evidence binding ID、精确引用、source URL、brand chunk ID、受限 chunk text 以及 copy/provider/version
  身份。新长文链路应读取这些已经持久化的快照，不重新抓取来源或重新做 embedding。
- `backend/app/schemas/copy_generation.py:246-259` 的 `MaterialDraft` 是 1200 字符上限的朋友圈短文结构。
  不应为公众号长文扩展这个类或改变历史 schema；需要独立 Article Package。
- `.trellis/spec/backend/brand-knowledge-rag.md:60` 明确品牌 chunk 不能充当事实 evidence。长文 claim
  validator 必须继续执行这条类型隔离。

## Existing provider boundary

- `backend/app/core/config.py:256-273` 已定义 `disabled|fake|zhipu`、model、timeout、concurrency、retry、
  input/output 和 usage budget；`backend/app/core/config.py:452-472` 对真实模式执行 HTTPS、base URL 与
  server-side secret 校验。
- `backend/app/infrastructure/ai/copy_generation.py:169-260` 的现有私有 transport 已实现 JSON chat、
  timeout、bounded response 和 usage；`264-345` 实现 strict schema parse 与最多一次 schema correction。
- `backend/app/infrastructure/ai/factory.py:273-304` 已证明 fake/real adapter 由配置选择且 secret 不进入
  application API。
- 新 adapter 应复用 `app.infrastructure.ai.zhipu._post_json_with_retries`、
  `app.infrastructure.ai.provider_json.extract_provider_json_object` 和现有 typed provider errors；不要
  import 私有 `_ZhipuStructuredCopyClient`，也不要为 MVP 重构短文 provider 行为。

## Persistence and worker patterns

- `.trellis/spec/backend/database-guidelines.md:87-104` 要求 API/worker 短事务、provider call 在事务外、
  `FOR UPDATE SKIP LOCKED`/lease/heartbeat 和 request fingerprint 防重复副作用。
- `backend/app/infrastructure/db/models.py` 已有 copy generation、image artifact、material package 和 WeCom
  job/attempt 模式；新表必须使用 typed FK、check/unique/index，并通过 Alembic 而不是 `create_all()`。
- 当前 migration head 是 `20260821_0025_visual_input_normalization_v2.py`；实现前重新检查 head，再创建
  additive 0026 migration。
- `backend/app/content_worker_main.py` 集成了多个内容 executor，但本地公众号链路需要自己的 opt-in
  worker，避免 `content_worker` 启动即隐式调用长文模型或改变生产调度。
- `.trellis/spec/backend/wecom-delivery.md` 已定义 side effect 的 `unknown`、不盲重试、child step 持久化
  和 dispatcher 边界，可复用可靠性模式但不能复用其发送语义。

## HTML and frontend boundary

- 仓库当前 Python/Node 依赖没有 Markdown parser 或 HTML sanitizer。MVP 最安全路径是只接受结构化
  blocks，由 stdlib escaping + 固定 tag/style builders 生成 HTML，不引入任意 HTML 清洗问题。
- `.trellis/spec/frontend/type-safety.md:9-26` 要求 `backend/openapi.json` 与生成 TypeScript 类型作为 wire
  contract；`frontend/src/features/material/api.ts:1-17` 是当前消费模式。
- `.trellis/spec/frontend/type-safety.md:88-90` 和 component/quality specs 禁止把模型内容交给
  `dangerouslySetInnerHTML`。长文预览应使用独立 preview URL + `sandbox` iframe，并在服务端响应严格
  CSP，而不是在 React DOM 中注入 HTML。
- `frontend/src/app/App.tsx:11-17,73-86` 已有仅开发环境 lazy-load/feature flag 模式，可用于本地草稿台。
- `frontend/src/features/material/hooks.ts` 已采用 TanStack Query list/detail/mutation/polling；新 feature
  应保留同样的 server-state ownership 和 terminal-state stop 条件。

## Product and safety constraints

- `.trellis/spec/backend/agent-pipeline.md:10,941,1123-1124` 明确当前终点是人工素材包且禁止自动社交
  发布。本地模拟必须使用独立命名、`simulation=true` 与显著 UI 文案；不得出现 publish/send API。
- 现有素材包图片保存在私有 MinIO 并通过受控 API 下载。模拟正文图/封面应引用已验证的 image artifact
  descriptor，API 只返回本地 media URL，不返回 bucket/object key、provider URL 或私有路径。
- 默认测试保持 provider-free；真实 LLM smoke 必须 opt-in、只读取服务器端已有 secret，并只打印
  provider/model/usage/run ID 等安全摘要。
