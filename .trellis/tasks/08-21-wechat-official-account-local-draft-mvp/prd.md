# 微信公众号本地草稿 MVP

## Goal

在不连接微信公众号、不使用 AppID/AppSecret、不发起任何微信请求的前提下，完成一条可在本地
运行和审阅的公众号长文草稿链路：

```text
受治理素材包 -> 真实 LLM 长文生成 -> 长文审校 -> 结构化 Article Package
             -> 微信兼容 HTML -> 本地正文图/封面 -> 模拟草稿箱 -> 可恢复状态
```

用户可以在浏览器选择一个现有素材包，显式调用当前配置的真实 LLM 生成公众号长文，并查看文章、
来源、品牌绑定、排版、正文图片、封面和模拟草稿状态。系统同时保留完全离线的脱敏 fixture 路径，
用于开发、测试和演示。

## Background and Confirmed Facts

- 当前项目已经具备新闻采集、事实治理、受控选题、短文生成、品牌 RAG、配图、质量检查、素材包、
  PostgreSQL 任务状态和内部企业微信交付能力。
- 现有素材包响应已包含主题、短文、来源、品牌绑定、验证、审校、版本和图片；其持久化快照还保留
  证据原文摘录和受限品牌片段，足以作为长文生成的受控输入。
- 当前 `MaterialDraft` 是朋友圈短文结构，不是公众号长文结构；公众号长文必须使用独立类型、提示词、
  审校和版本身份，不能扩大原短文合同。
- 当前 AI 边界已支持 `fake` 与真实 `zhipu` 结构化 JSON 调用、HTTPS 校验、超时、有界重试、
  provider/model 身份、用量与安全错误记录，可以复用其底层模式。
- 项目没有微信公众号 HTML renderer、正文/封面媒体适配器或公众号草稿记录；现有规范明确禁止自动
  社交发布。本任务只新增本地模拟草稿，不改变该边界。
- 当前工作区包含其他尚未收尾的变更；实施前必须重新核对冲突文件，保留并适配用户已有修改。

## Requirements

### R1 — 双入口与素材资格

- `live` 入口只接受现有持久化素材包，并显式调用当前配置的真实 LLM。
- 输入素材包必须已完成文案验证与审校、图片成功且未被人工拒绝；事实来源和品牌知识继续保持不同
  绑定类型，品牌片段不得充当外部事实证据。
- `fixture` 入口使用内置脱敏文章输入、确定性 fake generator/auditor 和本地图片，不需要任何模型或
  微信凭据，也不得访问外网。
- 同一输入、生成模式、provider/model 和版本策略产生稳定请求指纹；重复提交返回原运行，不重复调用
  模型。提示词、schema、规则或模型身份变化才产生新的运行身份。

### R2 — 真实 LLM 长文生成与审校

- 新增长文 generator 和 auditor 协议；真实模式使用当前配置的 Zhipu/OpenAI-compatible JSON 接口，
  fixture 模式实现相同协议但不访问网络。
- generator 只返回严格结构化 JSON，不返回 HTML、CSS、Markdown 或任意 URL。文章正文默认目标为
  1800--2600 个中文字符，硬边界为 1200--4000 个字符，并由版本化配置控制。
- 长文至少包含标题、摘要、作者、导语、3--7 个章节、结语、结构化 claim 绑定、来源列表、正文媒体槽、
  封面槽、质量摘要和稳定内容指纹。
- 确定性验证必须检查长度、结构、引用集合、事实/品牌绑定类型、未知 ID、危险内容和版本身份；模型审校
  再检查事实蕴含、品牌语气、隐私、安全和不当发布指令。
- 正常 live 路径最多包含一次生成调用和一次审校调用；仅允许现有上限内的 JSON schema correction，
  不自动进行内容再生成。审校拒绝进入 `review_required`，保留可检查版本但不创建模拟草稿。
- 原始 prompt、原始模型响应、完整内部品牌正文和密钥不得写入数据库、日志或 API。

### R3 — 平台无关 Article Package

- 文章包是长文的权威中间稿，使用独立、冻结、版本化的结构化 block schema；正文只包含纯文本、
  枚举块类型、受控 claim 引用和媒体槽，不包含平台字段或可执行标记。新文章版本使用应用拥有的
  多图计划：正文支持 `body-0` 到 `body-4`，目标为 3--5 张互不重复的合格图片；当 live 素材包只有
  更少的已审核候选时允许 1--2 张安全降级，不得重复图片、联网补图或降低审校门槛来凑数。
- 每个外部事实 claim 必须绑定输入素材包中已有的 evidence ID；品牌 claim 必须绑定已有 brand chunk ID；
  opinion 不得伪装成事实或品牌依据。
- 同一文章版本可重复渲染，并保存 source package/version、provider/model、prompt/schema/rule、验证、审校、
  usage 和内容指纹。

### R4 — 微信兼容 HTML 与安全预览

- MVP 只从结构化 Article Package 渲染 HTML；不接受模型 HTML，也不提供任意 Markdown/HTML 编辑器。
- renderer 使用固定模板和静态设计 token 生成内联样式 HTML，只能输出受控标签和属性。所有模型文本
  都必须转义，所有链接只能从已验证的来源快照生成，媒体 URL 只能由本地媒体适配器注入。
- canonical render 保存媒体占位符；模拟草稿 payload 保存替换成本地媒体 URL 后的最终 HTML。两者各有
  独立版本和指纹。
- 浏览器通过独立 preview endpoint 在无权限 sandbox iframe 中查看，preview 响应带严格 CSP、
  `nosniff` 和 `no-referrer`；前端不得使用 `dangerouslySetInnerHTML`。

### R5 — 本地媒体与模拟草稿箱

- 用本地 adapter 模拟“上传正文图片”“上传封面”“创建草稿”，不得读取公众号凭据或访问微信域名。
- 多图计划与插入位置由应用根据章节数、候选标签、优先级、尺寸、校验状态和稳定指纹确定，模型不得
  决定 URL、媒体 ID、数量或顺序。图片分布在不同章节后，不得连续堆叠；同一 SHA-256 在正文中最多
  使用一次。
- 正文图和封面必须形成不同 role、不同媒体记录和不同稳定 local media ID，不得互换。fixture 使用
  3--5 张仓库内原创、无文字、无二维码、无敏感内容的审核图片及独立横版封面，整个选择/读取路径
  零外部请求。历史单图 run 继续按其已固定版本恢复和重放。
- 模拟草稿返回稳定的 `local_draft_id`、正文 HTML、正文媒体引用、封面引用和 `simulation=true`；UI/API
  必须始终显示“本地模拟，未同步公众号”。
- local adapter 保持未来真实 adapter 所需的 typed port 形状，但 MVP 不实现 token、素材或 `draft/add`。

### R6 — PostgreSQL 状态、幂等与恢复

- PostgreSQL 保存运行、文章版本、模型/阶段尝试、渲染版本、本地媒体和模拟草稿；核心 lineage 使用
  typed foreign key，JSONB 只保存有界版本快照和文章 payload。
- API 只创建持久化运行；独立本地 worker 领取任务。模型调用、对象读取和 adapter 调用均在数据库事务
  外执行，结果在租约校验后的短事务中写回。
- 状态至少区分 `queued`、`running`、`review_required`、`ready`、`failed` 和 `result_unknown`，并记录当前
  stage、attempt、lease、request fingerprint 和安全 error code。
- 渲染、正文媒体、封面或草稿阶段失败后，从最近成功的指纹一致阶段继续。结果未知时不得自动重做
  草稿创建；已成功的文章、render 和媒体不得重建。
- 并发和重复请求只能得到一个运行、一个文章版本、每个 role/ordinal 一个媒体身份和一个模拟草稿身份。

### R7 — 本地操作界面与运行方式

- 新增仅在本地开发开关开启时加载的“公众号本地草稿台”，支持素材包选择、显式 live 生成、fixture
  演示、运行列表、状态轮询、失败提示和重新打开。
- 详情展示标题、摘要、作者、文章结构、来源/claim、品牌与事实审校、版本、模型用量、正文图、封面、
  移动宽度 HTML 预览和模拟草稿 ID。
- UI 不包含正式发布、群发、公众号登录、账号选择或密钥输入；服务器状态由 TanStack Query 管理，
  OpenAPI 生成类型是唯一 wire contract。
- 提供一条有文档的本地命令启动 PostgreSQL、MinIO、迁移、API、本地 worker、前端并创建 fixture 演示；
  真实 LLM 路径只在已有服务器端配置完整时可用。

## Acceptance Criteria

- [ ] 无模型/微信凭据时，本地演示命令可创建完整 fixture 文章与模拟草稿，且默认测试零外部请求。
- [ ] 配置真实 Zhipu provider 后，从一个合格素材包显式创建 live 运行，持久化真实 provider/model、
  安全 request ID、usage 和 latency，并生成 1200--4000 字的结构化长文；不保存原始响应。
- [ ] 生成与审校严格拒绝未知 evidence/brand ID、品牌充当事实证据、越界结构和 provider/model 漂移。
- [ ] 同一文章版本重复渲染得到规范化稳定的 canonical HTML 与相同指纹；模型文本不能注入标签、脚本、
  事件属性、iframe、危险 URL、外部样式或任意媒体地址。
- [ ] preview endpoint 与 sandbox iframe 能在浏览器显示移动端文章，安全 headers 生效，前端没有
  `dangerouslySetInnerHTML`。
- [ ] 新 fixture 稳定生成 3--5 张不同 SHA-256 的正文图和一张独立封面，按章节分布并全部可在浏览器
  查看；live 在只有一张已审核源图时安全降级而不复制凑数；API 不暴露 MinIO bucket/object key 或
  私有路径。
- [ ] 模拟草稿创建后可在列表和详情中重新打开，明确显示 `simulation=true` 和“未同步公众号”。
- [ ] 相同请求重放和并发提交不重复调用模型或创建版本/媒体/草稿；请求指纹或版本策略变化时可形成
  新的独立运行。
- [ ] 渲染、正文媒体、封面和草稿阶段的注入失败能从最近成功阶段恢复；`result_unknown` 不自动重试。
- [ ] PostgreSQL migration、约束、租约、幂等、恢复和 upgrade-to-head 集成测试通过，且不用 SQLite。
- [ ] API/OpenAPI/前端生成类型无漂移；后端与前端格式、lint、type-check、测试和 build 门禁通过。
- [ ] API、OpenAPI、UI、Compose 和日志中均不存在公众号 publish/send、AppID/AppSecret 或真实微信调用。

## Out of Scope

- 公众号类型/认证/权限核验、access token、IP 白名单、正文图/永久素材/`draft/add`/发布接口。
- 自动正式发布、群发、浏览器模拟登录、阅读数据回流、多账号和账号密钥管理。
- 运行时重新执行新闻采集、Embedding 或图片生成；live 路径只消费已有审核候选，fixture 路径只读取
  开发阶段已生成并纳入仓库的脱敏图片。
- 任意 Markdown/HTML 导入、富文本编辑、拖拽排版、文章人工改稿和自动内容修复。
- 改变现有朋友圈短文、素材包、企业微信交付或生产部署语义。

## Key Decisions

- 用户已确认 MVP 必须调用真实 LLM；真实调用范围限定为长文生成与长文审校，微信侧保持本地模拟。
- 模型只产出结构化文章，不产出 HTML。renderer 和媒体 URL 替换完全由确定性代码负责。
- 当前多图策略是新的 schema/media-plan/renderer/adapter 版本；旧 prompt、Article Package、renderer、
  adapter 和单图导出字节保持可重放，未知或混合版本 fail closed。
- 真实路径消费已完成素材包；fixture 路径独立、可离线、与 live 使用同一 application port。
- API enqueue 与独立 worker 分离，PostgreSQL 是权威状态；重复运行通过输入与版本身份指纹去重。
- 本地草稿 port 为后续微信 adapter 保留边界，但本期不会添加任何公众号凭据或网络能力。

## Risks and Deferred Items

- 单个素材包中的事实证据可能不足以支撑很长的新闻分析。MVP 以“不扩写未经支持的事实”为优先，
  证据不足时允许进入 `review_required`；跨事件补充证据留到后续。
- 温度为零也不能保证供应商逐字确定。确定性由“同指纹不重复调用、持久化首个合格版本”提供，而不是
  假设模型输出天然稳定。
- 本地媒体 ID 与 HTML 只用于模拟，未来接入微信时必须重新核验官方限制、图片语义和账号权限。
- 默认文章长度、模板和样式是 MVP 版本化策略；运营调优不阻塞本地链路验收。

## Approved Refinement — Semantic media and human copy-ready review (2026-08-23)

- New runs must use a new frozen version bundle; historical v1--v5 article/render/media/export
  bytes and recovery remain executable. Unknown or mixed old/new identities fail closed.
- The current media planner must score each approved candidate against bounded section heading/body
  text and candidate semantic tags, then choose a deterministic one-to-one assignment. For the
  four-section fixture, the expected semantic order is observation in section 1, experiment in
  section 3, and record/review in section 4. Stable tie-breaking uses approved candidate priority,
  checksum and source ID; the model never chooses media.
- Three-image placement must span the article rather than occupy the first three sections. The
  placement policy is versioned, deterministic and preserves the old v1 media-plan result exactly.
- Reader-facing image alt/captions describe the actual visual purpose and section meaning. They
  must not contain “本地正文配图”, ordinal-only labels, internal paths, model/provider language or
  unsupported claims.
- Keep lossless repository PNGs as immutable masters. New fixture media uses deterministic,
  metadata-stripped publication derivatives with the same 3:2/cover aspect and a bounded byte-size
  target; media type, extension, checksum and export manifest must agree. Do not rewrite historical
  assets or pretend recompressed bytes retain the old checksum.
- Human review is an explicit local event, not a model verdict. Add an additive approve/reject API
  and development-only UI with bounded reviewer label/note and immutable audit metadata. The system
  never auto-approves. Replaying the same decision is idempotent; a conflicting second final
  decision fails closed unless a future task introduces article revisions.
- Pending/rejected review bundles remain visibly non-publishable. Only an explicitly approved run
  may produce a separate copy-ready bundle whose article body omits the review-warning banner.
  Bundle identity, directory and fingerprints include the human-review record so approval never
  mutates or silently reuses the pending audit package.
- Rewrite the sanitized fixture's public paragraphs to natural parent-facing language. Internal
  phrases such as “脱敏示例材料”, “品牌表达承担不同任务”, schema/provider/media-plan descriptions and
  test instructions belong in review/source metadata, not reader copy. The non-link fixture source
  boundary remains explicit.

### Refinement acceptance

- [ ] The fixture assigns three distinct approved images to sections 1/3/4 with semantic captions,
  no generic local-image wording and stable deterministic fingerprints.
- [ ] Publication derivatives materially reduce total fixture media bytes while preserving readable
  430px quality; source masters remain unchanged and historical v5 golden hashes still pass.
- [ ] Pending export retains its warning; approve/reject is a local human-only audited action; only
  approved review produces a distinct clean copy-ready HTML/ZIP and repeated export is exact.
- [ ] API/OpenAPI/frontend expose review state and accessible approve/reject controls only in the
  development workbench, with no publish/send/WeChat credentials or automatic approval.
- [ ] Default fixture, tests and export make zero external requests. No Zhipu, WeChat or WeCom call
  is made during implementation or acceptance.

## Approved Refinement — Multimodal approved-catalog matching (2026-08-23)

- The user explicitly approves using the existing 41-item, manifest-approved private brand visual
  catalog as the official-account body-image candidate pool. Approval does not widen the pool to
  arbitrary files, web search, generated images or unreviewed material.
- Freeze every historical official-account family through renderer v6 and review-bundle v3. New
  work uses an exact v7 multimodal-hybrid family; unknown or mixed families fail closed and old
  runs never acquire semantic fields or new bytes during recovery.
- Multimodal ranking is a separate, disabled-by-default live capability. It reuses the frozen
  `alibaba-model-studio/qwen3-vl-embedding` 2048-dimensional identity only after an operator has
  built one exact, complete current catalog index. API/startup/fixture execution never indexes the
  catalog and never creates the visual provider client.
- Hard eligibility runs before similarity: manifest approval, current catalog/checksum, body-safe
  role/kind, readable bounded PNG master, distinct checksum and publication suitability. A model
  score may only reorder survivors and may never admit another asset. Private filename/path,
  vectors, query text and provider bodies stay out of persistence, API, logs and exports.
- For an explicitly enabled live run, build one bounded text query per balanced article placement
  from the article topic, section heading and first 360 normalized body characters. Prove complete
  catalog coverage before paid queries, perform provider calls outside transactions, and compute a
  deterministic maximum-weight one-to-one assignment across the eligible catalog candidates.
  Existing tag score and priority/checksum/asset reference are deterministic tie breakers.
- Any disabled provider, incomplete/mixed index, authentication/timeout/output/identity failure or
  catalog race discards the entire similarity matrix and uses the frozen deterministic semantic-tag
  planner. One candidate skips the provider as `single_candidate`. There is no partial mixed plan,
  hidden retry or second logical request for one placement.
- Persist the final bounded selection snapshot in the immutable new Article Package before render.
  Retry/recovery uses that snapshot and performs zero additional embedding calls. The snapshot
  records only version identity, semantic status/closed reason, query fingerprints, bounded
  similarity bands and ordered candidate-to-section assignments.
- Selected catalog PNG masters remain immutable. The local adapter creates deterministic,
  metadata-stripped, size-bounded publication derivatives without exposing source paths. The
  material package's validated primary image remains the distinct cover; catalog assets are body
  candidates only.
- The development workbench explains `多模态语义匹配` versus `确定性标签回退`, but similarity is not
  editorial approval. Human approve/reject and approved-only copy-ready export remain unchanged.

### Multimodal refinement acceptance

- [ ] A complete fake 41-item index proves section-text/image ranking can change the deterministic
  tag order while preserving balanced placement, hard gates, distinct checksums and stable replay.
- [ ] Disabled/incomplete/provider-failure/catalog-race cases make zero or bounded fake calls as
  specified, discard partial scores, and reproduce the deterministic fallback exactly.
- [ ] Default fixture/tests/export make zero external requests. Explicit live configuration is the
  only path that can call the real multimodal provider; acceptance does not call it.
- [ ] V7 persists and reuses a bounded selection snapshot; OpenAPI/UI/export expose only safe method,
  status, closed reason and similarity bands, with no vector/query/private path leakage.
- [ ] The 41-item catalog remains operator-indexed and immutable; selected body derivatives are
  byte/type/size checked, and historical v1--v6 article/render/export goldens still pass.
- [ ] No implementation or acceptance path calls WeChat, WeCom, web search or image generation.

## Approved follow-up — first-call structured-output reliability (2026-08-23)

- Real Zhipu trials exposed invalid envelopes and schema drift before rendering. New live work therefore uses a
  separate v8 Article family: generator `official-account-generator-v5-structured-output` and auditor
  `official-account-auditor-v2-structured-output`. Historical v1--v7 identities, initial request bytes and recovery
  remain frozen.
- Only v8 places the bounded canonical Pydantic validation schema in the first system instruction; audit also carries
  the `accepted`/`issue_codes`/`claim_ids` conditional invariant. The user prompt remains governed input, all sent
  system and user text counts toward the same input limit, and schema correction remains at most one retry.
- Migration `20260823_0030` adds immutable numeric Article artifact v5 and refuses a downgrade while v5 rows exist.
  The generation default rises to 16,384 output tokens; offline fixtures and tests remain provider-free.
- The follow-up must run one explicitly enabled live smoke at most once, preserving the local simulated-draft-only
  boundary and never calling WeChat or WeCom.

## Approved follow-up — explicit local export of a ready live draft (2026-08-24)

- The user authorizes an explicit CLI-only export of a completed, simulated live article to a local non-root
  directory. Default export remains restricted to the sanitized fixture; live export requires the affirmative
  `--allow-live-local-export` flag and supports review mode only.
- The bundle must retain resolved HTML, offline preview, local relative media assets, Markdown/JSON/source/review/
  preflight/manifest and deterministic ZIP. It is permanently marked `LOCAL ONLY · 未同步公众号`, never published
  or copy-ready, and preserves rather than changes its manual-review status.
- API and CLI reuse one fail-closed media resolver for catalog body images and the persisted source cover. Any
  lineage/type/byte-size/checksum drift fails before a completed bundle is written; private paths and object keys
  remain excluded. No model, WeChat, WeCom or other social call is permitted during export.

## Approved supplement — manual IP-reference visual review (2026-08-24)

- The user authorizes an operator-run, local-only visual supplement that uses the existing 41-item,
  manifest-approved private 小赛／赛先生 IP catalog only as character, material and palette reference for
  new per-section illustrations. It does not make the private masters into public export assets.
- Each new visual is mapped to one article section and must be original, free of readable text, chest labels,
  logos, QR codes, watermarks and advertising layout. This manual-supplement wording is superseded for the durable
  automatic path below: it deliberately adds no image-level human-review gate and leaves only the independent
  article-level manual review in force.
- The supplement is outside the current durable Article/worker/API/export pipeline: it neither changes the
  default zero-egress fixture/tests nor grants runtime image-generation/network behavior. It never calls
  WeChat or WeCom, and any future product integration needs a new approved, versioned media contract.
- A local review bundle may retain only catalog version, bounded public asset references, new-image checksums and
  section summaries. It excludes catalog source files/paths, raw IDs, vectors, prompts and provider bodies.

## Approved follow-up — automatic approved-IP body visuals (2026-08-24)

- The user authorizes the local official-account worker to automatically generate original per-section **body**
  illustrations from the current article's already-selected, manifest-approved 41-item 小赛／赛先生 catalog reference.
  The exact complete Qwen3-VL selection remains the authority; if it is unavailable, the persisted deterministic
  selector snapshot is used. The capability must never search or use arbitrary local files.
- Generation is versioned, additive, durable and fail-closed: persist a safe intent before one external image call,
  validate provider/model/fingerprint and output, store bytes privately, then stage local body media. An interrupted
  unconfirmed intent becomes `result_unknown` and is never silently retried. Calls occur outside DB transactions.
- Default settings, fixtures and tests make zero external requests and do not construct an image provider client.
  Real image generation requires explicit local-worker/image configuration and may reuse the existing image port;
  it never calls WeChat or WeCom and never publishes.
- No image-level human-review gate is required. This does not change the existing independent article manual-review
  event or approved-only copy-ready semantics. Safe DB/API/export/log projections exclude raw asset IDs/paths,
  vectors, prompt text, reference bytes and provider bodies; bounded public asset references/checksums remain allowed.

### Automatic-visual acceptance

- [ ] Each generated body visual is mapped one-to-one to a revalidated selected section/reference and has a durable
  safe plan/result record; ready bytes are local staged media only.
- [ ] Disabled/fixture and incomplete-semantic cases use bounded existing catalog selection without constructing an
  image client or making external requests; provider output/configuration/recovery drift fails closed.
- [ ] OpenAPI/API/export expose only safe status and output metadata, no image human-review action, and preserve
  article manual-review and permanent no-WeChat/no-WeCom/no-publish boundaries.

## Approved follow-up — block-anchored publication visuals (2026-08-24)

- Freeze the complete generated-visual v1 replay contract. Current work uses additive v2 plan, prompt,
  reference-input and output-profile identities; it must not rewrite v1 rows, fingerprints, PNG provider request
  bytes or raw stored outputs.
- Each v2 placement selects one deterministic eligible semantic text block inside its assigned section. Persist only
  bounded block index, kind and fingerprint; construct the transient scene brief from that exact block plus the
  section heading and topic. Raw block text and prompt remain private and transient.
- Exact valid PNG references remain byte-identical at the provider boundary. Approved-catalog JPEG publication
  references are deterministically decoded and converted to metadata-free PNG for ToApis/Comfly, with the
  normalization version and provider-input checksum bound to the v2 request fingerprint.
- The actual v2 generated body artifact is a deterministic, metadata-free 1536×1024 JPEG publication derivative.
  Its bytes—not the provider's arbitrary raw aspect ratio—are persisted and reused by local media, preview HTML and
  export. Dimensions, MIME and byte size are bounded and fail closed.
- A provider timeout after the durable intent is ambiguous: mark the ledger and run `result_unknown` immediately and
  never repeat that paid call automatically. Known validation/rejection outcomes remain `failed`.
- The development-only timeline shows `generating_body_visuals` with ready/total progress derived from safe contract
  fields. Gallery alt text is bounded and describes the anchored section/block purpose; gallery and final HTML use
  the same persisted 3:2 composition and reduced-motion/accessibility behavior remains intact.

### Block-anchored visual acceptance

- [ ] Migration `20260824_0033` advances from the actual unique `0032` head, preserves nullable v1 rows and enforces
  the complete v2 block/reference-input/output-profile shape.
- [ ] No-network builder tests prove exact v1 PNG bytes and deterministic JPEG-to-PNG Comfly/ToApis inputs; timeout
  tests prove one provider call, immediate `result_unknown` and zero recovery retry.
- [ ] Unit/repository/HTML/export tests prove stable block anchors/fingerprints, historical v1 fingerprint replay and
  metadata-free exact 3:2 v2 stored bytes shared by media, preview and export.
- [ ] OpenAPI/generated types and focused frontend tests prove ready/total timeline progress and semantic alt text.
- [ ] Default fixture/tests construct no provider and make zero external requests; acceptance never calls an image,
  embedding, article, WeChat or WeCom provider.

## Approved follow-up — news-backed visible-IP ToApis demo (2026-08-24)

- Preserve every historical run/output and freeze generated-visual v1/v2 prompt/request bytes. New worker work uses
  additive v3 plan/prompt identities that require the manifest-approved 小赛／赛先生 character to be a clearly visible
  protagonist while preserving recognizable silhouette, face construction, material and palette.
- Bind current-news interpretation only to bounded snapshots from the two user-approved Ministry of Education pages:
  the 2026-07-21 basic-education news and the 2026-04-10 five-department AI+Education action plan. External facts bind
  those evidence IDs; family guidance remains explicitly labeled interpretation, never brand evidence.
- The operator-only demo uses ToApis single-reference downgrade with one immutable approved company-IP reference per
  exact news-backed body block. It persists a safe local intent before each of at most three paid calls, sets provider
  attempts to one, performs no hidden retry and stops unknown on timeout. It never constructs Comfly, article-model,
  embedding, WeChat, WeCom or publish clients.
- Store only metadata-free exact 1536×1024 JPEG derivatives in a new `official-account-news-ip-*` output directory.
  HTML, evidence, visual map, manifest and ZIP refer to those same bytes and keep manual review pending/local-only.

### News/IP demo acceptance

- [x] Additive migration `20260824_0034` advances from the actual `0033` head and admits only complete v3 visible-IP
  plan/prompt tuples while retaining v1/v2 constraints and publication profile.
- [x] Offline tests cover exact official-source claim binding, frozen v2 versus mandatory-visible-IP v3 prompts,
  ToApis JPEG-to-PNG input construction, exclusive intents, three-call limit/no retry and safe local projections.
- [x] One isolated run finishes `ready`: two authoritative source snapshots, three ToApis calls/three successes,
  three metadata-free 3:2 images and local visual inspection passing visible-IP/no-text/no-logo/no-watermark checks.
- [x] Article/embedding/Comfly/WeChat/WeCom/publish calls are zero and no secret, provider body, prompt or private path
  enters the output bundle.
