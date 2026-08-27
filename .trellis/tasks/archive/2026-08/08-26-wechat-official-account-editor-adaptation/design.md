# 微信公众号编辑器本地适配：技术设计

## 1. 问题重述与不可变边界

本任务解决的不是“自动发布公众号”，而是把已经生成并人工批准的本地公众号 Article Package，
确定性投影为一套可在微信公众号编辑器中手工粘贴、上传图片和继续预览的交接物。

以下事实决定最小实现：

- 现有 run、Article Package、正文/上下文/封面媒体、模拟草稿和人工审稿已经持久化；交接阶段不应再次
  写作、审校、Embedding、生图或抓新闻。
- 微信正文图片和封面在未来服务端接入时仍需分别上传到微信；本期只有本地相对资源，不能声称已进入
  草稿箱。
- 历史 V1--V10 renderer、adapter、review/copy-ready bundle 和恢复字节必须冻结。
- `gzh-design` 需要纯 `<section>` 正文、内联样式、`span leaf` 和确定性校验；运行时不能依赖个人目录
  `/root/.codex/skills`。
- 用户已选择“未验证发布权的新闻原图直接使用”。该状态是非阻断 warning，但来源和原始
  `publish_permission_unverified` 必须持续可见，不能伪装成已授权。

## 2. 关键设计决策

### D1 — 只读派生，不新增 durable job

editor-handoff 是批准后不可变状态的确定性派生，不是新的长任务。后端按请求读取现有 PostgreSQL/媒体
存储快照，校验哈希，在内存或临时目录中构建交接物并返回。它不更新 run、article、draft、media 或
manual review，也不创建数据库表、migration、repository 方法、队列或 worker。

这使相同输入指纹得到相同正文和 ZIP 字节，同时避免为可重建输出引入第二套状态机。未来真实微信
上传是有外部副作用、需要幂等记录的独立 adapter/job，不属于本任务。

### D2 — 独立版本家族，不改历史输出

新增以下固定身份；具体字符串在实现时一次冻结并加入测试：

- editor renderer：`wechat-editor-handoff-renderer-v1-gzh-xiaosai`
- style：`wechat-editor-handoff-style-v1-xiaosai-blue`
- template：`wechat-editor-handoff-template-v1-moyu-layout`
- bundle：`official-account-editor-handoff-bundle-v1`
- preflight：`wechat-editor-handoff-preflight-v1`
- rights policy：`editor-handoff-context-rights-v1-direct-use-disclosed`

这些是现有 Article Package 的下游投影身份，不加入当前 worker 的 Article version tuple，也不替换
`official_account_export.py` 中任何历史常量或分支。

### D3 — 项目内拥有小赛主题

把已批准的“小赛蓝（摸鱼绿原结构）”所需设计 token、组件骨架和映射规则整理为项目内的静态、只读
主题定义。来源以当前已通过 `gzh-design` 0 ERROR/0 WARNING 的主题和 V4 产物为基线；运行时代码不得
打开 skill 目录。主题规范化内容和 SHA-256 进入 renderer/bundle identity 与 golden tests。

渲染器只接受结构化 `ArticlePackage` 和经过完整性验证的媒体描述符，不接受模型 HTML、任意 Markdown、
用户 HTML 或运行时模板路径。文章文本、alt、caption、credit 和 URL 均经过各自的转义/allowlist。

### D4 — 新闻原图直接使用但不抹去风险事实

`publish_permission_unverified` 在 editor-handoff preflight 中映射为非阻断 code
`context_image_rights_unverified_direct_use`。正文保留该图，工作台允许复制/下载；同时：

- `rights.json`、`preflight.json`、manifest 和 API 返回原始 rights status 与来源页；
- 工作台显示“按当前本地策略直接使用，发布权未验证”；
- 不写 `licensed`、`approved_rights`、`copyright_cleared` 等虚假状态；
- 历史 copy-ready 导出仍按原规则拒绝，不受该策略影响。

## 3. 分层与文件所有权

### Domain

新增 `backend/app/domain/official_account_editor_handoff.py`，只包含纯类型和纯函数：

- 版本常量与 `EditorHandoffIdentity`；
- `EditorHandoffMediaAsset`、`EditorHandoffCheck`、`EditorHandoffPreflight`；
- Article Package 到 gzh 正文的确定性渲染；
- HTML 标签/属性/style/URL/图片引用检查；
- manifest/fingerprint 输入的 canonical serialization。

该模块不导入 FastAPI、SQLAlchemy、对象存储、浏览器或 provider SDK。

### Application

新增 `backend/app/application/services/official_account_editor_handoff.py`：

- 通过现有 repository 读取 run/article/draft/manual review/media snapshot；
- 通过现有 `OfficialAccountLocalMediaResolver` 读取并重新校验媒体字节；
- 组装 typed input，调用 domain renderer/preflight；
- 构建纯正文、预览、JSON/Markdown/rights/manifest 与确定性 ZIP；
- 返回内存中的 typed artifact，不持久化、不联网。

路由只调用该 use case 并投影 HTTP，不复制 eligibility、render 或 ZIP 规则。

### API schemas and routes

扩展 `backend/app/schemas/official_account_local.py` 和现有
`backend/app/api/v1/routes/official_account_local.py`。不增加新的 router include：

- `GET /api/v1/official-account-local/article-runs/{run_id}/editor-handoff`
  返回状态、版本、指纹、checks、warnings、媒体下载列表及 artifact URLs；blocked 状态也是可展示的
  200 typed response。
- `GET .../editor-handoff/body`
  返回可复制的纯正文 `text/html; charset=utf-8`。
- `GET .../editor-handoff/preview`
  返回固定本地预览外壳；复制脚本/按钮在正文节点之外。
- `GET .../editor-handoff/assets/{asset_name}`
  只接受 manifest 中确定生成的安全文件名，重新校验媒体字节并使用 attachment header 下载。
- `GET .../editor-handoff/bundle`
  返回确定性 ZIP attachment。

body/preview/bundle/assets 只在所有 blocking checks 通过时返回；否则抛出带稳定 code 的 `AppError`
（409/422），而不是仅返回中文 message。所有响应使用 `private, no-store`、`nosniff`、
`no-referrer`；预览 CSP 只允许 self 图片、内联样式和固定哈希脚本，禁止表单、object、base 和外部连接。

### Frontend

在 `frontend/src/features/official-account-local/` 内新增窄组件
`OfficialAccountEditorHandoff.tsx` 及 CSS/test；由现有详情页组合，不重新设计整个工作台。

- `api.ts` 只从生成 OpenAPI 类型映射 wire response；不手写第二份 transport schema。
- `hooks.ts` 增加 handoff query key/query；它是 GET server state，不使用 mutation。
- `clipboard.ts` 或 feature-scoped helper 执行浏览器 Clipboard API/fallback，明确区分成功、不可用和权限
  拒绝；组件不直接发裸 `fetch`，不使用 `dangerouslySetInnerHTML`。
- preview 继续 sandbox iframe；正文只在后端固定预览文档内渲染。
- ZIP、正文图、新闻原图和封面使用安全 URL 与浏览器 download effect。
- `aria-live` 汇报复制/下载状态；按钮有明确 disabled reason 和键盘 focus 样式。

## 4. Eligibility 与数据流

```text
development flag
  -> existing run/article/draft/review/media snapshots
  -> immutable approval + fingerprint gate
  -> verified media bytes
  -> gzh deterministic renderer
  -> editor preflight
  -> metadata / body / preview / assets / deterministic ZIP
  -> generated OpenAPI mapper + TanStack Query
  -> sandbox preview + clipboard + local downloads
```

### Blocking eligibility

以下任一条件阻止正文、预览和 ZIP：

- `APP_ENV != development` 或新的 backend opt-in flag 未开启；
- run 不是 `ready`；draft 缺失、非 `ready`、非 simulation；
- article/validation/audit 不完整或不通过；
- manual review 不是 `approved`，或 review fingerprint 与 run request fingerprint 不一致；
- Article Package/version/media-slot 形状不合法；
- 不是 1--5 张互异正文图，缺少独立封面，媒体 hash/MIME/dimension/role/ordinal 不一致；
- 纯正文、asset path、manifest、ZIP 或 preview/body 一致性检查失败。

`pending`、`rejected`、`failed`、`result_unknown` 都返回稳定 blocking code。单张素材下载是否开放遵循
“已存在且完整即可下载”：即使 handoff blocked，原有媒体端点仍保持现有行为；新的 handoff asset 路由
不绕过 handoff gate。

### Non-blocking warnings

- `context_image_rights_unverified_direct_use`：用户选择直接使用，持续披露；
- `mobile_browser_validation_not_run`：当前 runtime 请求未经过真实浏览器检查；
- 其他只影响运营提示、不影响结构安全的已定义 warning。

warning 不得通过中文字符串判断；前后端 switch 必须穷尽稳定 code。

## 5. 正文与媒体映射

### 纯正文

输出从唯一的全局 `<section>` 开始，不含 doctype、`html/head/body/style/script/button`。固定允许元素以
项目内 preflight 与 gzh validator 交集为准，至少遵守：

- 样式全部 inline；无 class/id/event handler/CSS variable/external CSS；
- 所有可见文字落在 `<span leaf="">` 内；
- `img` 使用 `max-width:100%;height:auto;display:block;margin:0 auto`，不把小图强制拉伸；
- 目录只精选前三个核心章节；章节按 `01/02/...`，结语使用主题约定；
- 每个正文段落通过纯确定性规则标记 1--3 个已有关键词，不生成或改写内容；
- 来源链接只允许 Article Package 已声明的 HTTPS source URL；
- 不允许远程图片、`/api/` 图片 URL、私有路径、占位符或未声明 asset。

正文图按 Article image block/slot 的原位置输出；新闻上下文图按
`news_context_media.items[].section_index` 输出在对应章节，不改变其 alt/caption/credit/source lineage。
封面不进入正文，单独输出。

### 资产命名

只生成规范化相对路径：

- `assets/body-00.<ext>` ... `body-04.<ext>`
- `assets/context-00.<ext>` ... `context-01.<ext>`
- `assets/cover-wide.<ext>`

扩展名由验证后的 MIME 决定，禁止用户输入文件名。每项记录 role、ordinal、SHA-256、bytes、MIME、
width、height、alt、section anchor、provenance 和 rights status。所有 hash 在读入与写 ZIP 后复核。

## 6. Bundle contract

ZIP 根目录使用由固定 bundle identity 与 handoff fingerprint 派生的安全名称，内容排序稳定、时间戳与
Unix mode 固定、自身不递归包含：

```text
article-body.html
preview.html
article.md
article.json
sources.json
rights.json
review.json
preflight.json
mobile-validation.json
theme.json
README.md
assets/body-*.{jpg,png,webp}
assets/context-*.{jpg,png,webp}
assets/cover-wide.{jpg,png,webp}
manifest.json
```

`manifest.json` 绑定：run/request/content/render/resolved/review/theme/handoff fingerprint、全部版本、
rights policy、每个文件 hash/bytes、媒体元数据和 archive contract。重复读取同一批准状态产生相同正文、
manifest 与 ZIP SHA-256。

`preview.html` 内的被复制节点字节必须等于 `article-body.html`；预览按钮、提示和固定脚本位于节点外。
脚本仅操作本页 DOM/clipboard，不联网。`article.md`/JSON 是安全投影，不暴露对象存储 key、私有路径、
raw provider body、prompt、vector 或账号凭据。

## 7. Mobile validation

静态 preflight 不能冒充浏览器验收。runtime metadata 默认返回：

```json
{"status":"not_run","viewports":[320,430]}
```

该项是明确的非阻断 warning。focused Playwright acceptance 使用离线 fixture/loopback 静态服务实际打开
同一 renderer 产物，在 320px 和 430px 下断言：

- 所有正文/上下文图片 `complete && naturalWidth > 0`；
- document 没有页面级横向溢出；主题目录自身可横向手势滚动是允许行为；
- 没有外部 request；
- 正文与预览 copy root 一致。

测试生成真实 `mobile-validation.json` fixture 记录；一般 runtime 不把 fixture 结果套到其他文章。

## 8. Development-only 配置

新增 backend setting `official_account_editor_handoff_enabled`，默认 `False`，且只有
`APP_ENV=development` 才允许端点工作。Compose/local env 只透传显式 opt-in，不包含公众号凭据。

前端继续受 `import.meta.env.DEV && VITE_OFFICIAL_ACCOUNT_LOCAL_ENABLED=true` 控制，并同时读取 backend
capability `editor_handoff_enabled`；production build 不展示交接区。关闭任一 gate 后不能仅靠猜 URL 使用
端点。

## 9. 兼容、碰撞与回滚

- 不修改历史 renderer/export 常量、历史 bundle writer 或 golden bytes。
- 不新增 migration/repository/worker；因此无数据库 downgrade 与迁移头冲突。
- 高碰撞文件是 `backend/app/core/config.py`、`.env.example`、`compose.yaml`、route/schema、
  `backend/openapi.json`、生成 TypeScript、现有 Panel/CSS、README 和 Trellis spec。每次修改前检查局部
  `git diff`，只作最小合并，不回退其他任务。
- 回滚只需关闭 backend opt-in/前端 dev flag；既有 run、review、media、draft 和历史导出不变。
- 如果在实现期间发现必须持久化新状态或执行 provider/微信请求，停止并重新规划，不能把它隐式塞进
  本任务。

## 10. 文档更新

实现完成后用英文更新 backend official-account spec，并新增/更新 frontend editor-handoff spec 与索引；
README 增加本地 flag、操作顺序、ZIP 内容、权利 warning、零外部请求边界和“未同步公众号”说明。生成
一个新的本地 fixture 交接目录/ZIP供验收，但不提交真实账号数据或凭据。
