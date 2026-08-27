# 微信公众号编辑器本地适配

## Goal

把现有公众号本地草稿与小赛 `gzh-design` 排版成果收敛成一个面向运营人员的、可验证的
微信公众号编辑器交接流程：在开发工作台完成最终审稿后，可以预览微信兼容正文、复制富文本、
下载正文图片与封面、下载完整交接包，并清楚看到哪些条件仍阻止“可复制交接”。本任务不连接
公众号、不读取账号凭据、不创建微信草稿，也不发布或群发。

## Background and Confirmed Facts

- 现有 durable official-account 链已经生成结构化 Article Package、固定模板 HTML、1--5 张正文图、
  独立封面、本地模拟草稿、人工审稿和不可变导出包。历史 renderer、adapter、bundle 与恢复字节必须
  继续可重放。
- `run_wechat_draft_preflight()` 已检查保守标题/作者/摘要长度、HTML 字节与标签白名单、HTTPS 来源、
  受控本地媒体、MIME/字节/尺寸、2.35:1 封面和人工审稿，但仍固定记录
  `mobile_screenshot_not_run`，见
  `backend/app/application/services/official_account_export.py:225` 与
  `backend/app/application/services/official_account_export.py:495`。
- fixture 可在批准后生成独立 `copy-ready` 包；真实新闻运行仍被 CLI 限制为 review-only，见
  `backend/app/official_account_local_cli.py:147`--`162`。V10 规范也明确：带
  `publish_permission_unverified` 新闻上下文图时，请求 copy-ready 必须拒绝，见
  `.trellis/spec/backend/official-account-editorial-repackage.md:783`--`794`。本任务不改写该历史
  copy-ready 语义，而是新增独立的 editor-handoff 版本家族。
- 开发工作台已有安全 iframe 预览和不可变人工批准/退回，但没有复制正文、下载交接 ZIP、下载封面或
  查看结构化预检的操作入口；当前预览入口见
  `frontend/src/features/official-account-local/OfficialAccountLocalPanel.tsx:824`--`839`。
- 当前导出器已生成相对 `assets/` 图片路径、完整 SHA-256 manifest 与确定性 ZIP；重导出读取持久化
  PostgreSQL/MinIO 状态，不调用文章、审校、Embedding、生图、新闻源、微信或企微。
- 已注册的“小赛蓝（摸鱼绿原结构）”主题完整保留 `gzh-design` 母版结构，只替换小赛 AI 视觉色板；
  `gzh-design` 要求纯 `<section>` 正文、内联样式、受控标签、文字 `span leaf`、无脚本/外部 CSS，
  并要求生成后校验到 0 ERROR/0 WARNING。
- 2026-08-19 基于微信官方文档的本地研究记录确认：服务端草稿路径中的正文图片必须先上传并换成微信
  侧 URL，封面使用独立素材 `media_id`，创建草稿与发布是不同接口。本期既不持有凭据也不调用这些
  接口，因此不能声称相对本地图片已经成为微信草稿资源。
- 当前工作区有大量其他未提交改动；实现只能添加新版本和窄范围接口/UI，必须在高碰撞文件修改前检查
  重叠 diff，不得覆盖或回退其他任务。

## Requirements

### R1 — 新版本、小赛主题与历史兼容

- 新增一个明确版本化的 editor-handoff renderer/style/template/bundle/preflight 家族；不得原地改变
  历史 V1--V10 renderer、已有 review/copy-ready bundle、fixture golden bytes 或恢复行为。
- 新版本从现有 Article Package 确定性渲染，不接受模型 HTML、任意 Markdown/HTML 上传或运行时主题
  文件路径。需要使用的小赛主题 token 与组件结构必须作为项目拥有、可审计、可测试的静态资产进入
  版本身份，不能依赖 `/root/.codex/skills`。
- 排版保持 `gzh-design` 已确认的原版结构和小赛品牌色；只能使用微信兼容的受控标签、属性与内联样式。
  所有文本转义，图片 URL 只由受控交接适配器替换。

### R2 — 编辑器交接包

- 仅对 `ready` 且已经不可变人工批准的运行生成 editor-handoff 包；pending/rejected/failed/
  `result_unknown` 均返回 typed blocking reason，不生成貌似可用的交接物。
- 包含纯正文片段、带复制按钮的本地预览、Markdown/JSON 安全投影、正文图、封面、来源/权利清单、
  editor preflight、manifest、移动端验收记录和确定性 ZIP。
- 纯正文文件不得包含 `html/head/body/style/script/button` 外壳；复制按钮和脚本只存在于预览外壳，
  不进入被复制的正文节点。
- 每个文件记录 SHA-256、字节、MIME、尺寸、role、ordinal 和来源边界；ZIP 写入后必须重新读取验证，
  重复同指纹导出返回同一路径和同一哈希。

### R3 — 图片与微信边界

- 正文图、新闻上下文图和封面保持不同 role。正文按文章块位置排列，封面保持 2.35:1；不得重复图片、
  不得用外链替换、不联网补图。
- 编辑器交接 HTML 使用包内相对素材供本地预览；UI 必须明确提示：正式进入微信后仍需由微信编辑器
  上传，或由未来微信 adapter 换成微信侧 URL/封面素材 ID。
- 用户已明确决定：新闻上下文图即使带 `publish_permission_unverified`，也直接保留在 editor-handoff
  正文中并允许复制/下载，不作为 blocking gate。系统必须保留原始 `rights_status`、来源页、署名和
  “发布权未验证”提示，不得把它改写成已授权或已核验；该策略使用独立版本身份，不能放宽历史
  review/copy-ready 导出规则。

### R4 — 版本化 editor preflight

- 在现有预检基础上新增 editor-handoff 规则版本，检查：人工批准、rights 状态披露、正文纯片段、标签/属性/
  CSS allowlist、`span leaf`、受控相对图片路径、图片数量与唯一性、封面比例、所有 manifest 哈希、
  禁止占位符/私有路径/API URL/远程图片，以及复制预览与正文内容一致性。
- 规则结果分为 `passed`、blocking errors 与非阻断 warnings；前后端使用稳定 code，不依赖中文字符串
  判断状态。`publish_permission_unverified` 在本版本中产生稳定的非阻断 warning，并保留在 rights
  manifest 与 UI 中。
- 320px 与 430px 的视觉验收作为独立可验证产物进入交接记录；默认单元/集成测试可以使用确定性浏览器
  fixture，不发起外部请求。运行时不得伪造浏览器已验收。

### R5 — 开发工作台与生成合同

- 在现有公众号本地草稿详情中增加“微信公众号编辑器交接”区域，显示审核、样式、图片、权利、移动端
  和包完整性状态。
- 仅当全部 blocking gates 通过时开放“复制正文”和“下载交接 ZIP”；正文图和封面始终提供独立安全
  下载，便于运营人员手工上传。操作成功/失败必须有键盘可达、`aria-live` 的明确反馈。
- iframe 继续 sandbox；前端不使用 `dangerouslySetInnerHTML`。剪贴板与下载是浏览器 effect，不是
  server mutation；不可用或权限拒绝时不能提示成功。
- 后端新增 typed、development-only、无副作用的预检/导出资源接口；更新 FastAPI OpenAPI、生成的
  TypeScript 类型、mapper、TanStack Query hooks、focused tests 与文档。不得新增 AppID、AppSecret、
  access token、账号选择或 publish/send action。

### R6 — 默认零外部请求与自动化边界

- 默认 fixture、测试、预检、导出和 UI 验收对模型、Embedding、生图、新闻源、微信、企微均为零请求；
  不创建新的 durable worker job，也不修改已批准的运行时 Article/render/media。
- 本任务只完成本地编辑器交接，不实现微信 `uploadimg`、永久素材、`draft/add`、发布、群发、浏览器登录
  自动化或账号权限探测。

## Acceptance Criteria

- [ ] 一个批准的 fixture/current-version 运行可从开发工作台生成并重新打开 editor-handoff，看到完整
  预检，复制纯正文并下载确定性 ZIP、正文图与 2.35:1 封面；重复请求不产生不同字节。
- [ ] pending/rejected/failed/result-unknown 运行不能生成可复制交接物，UI 显示稳定阻断码与中文说明。
- [ ] 新正文通过 `gzh-design` HTML 校验（0 ERROR、0 WARNING），没有外壳、脚本、事件属性、外部样式、
  私有路径、`/api/` 图片 URL、未解析占位符或远程图片。
- [ ] 正文和预览使用相同经过哈希绑定的内容；复制按钮不进入正文；剪贴板失败、API 不可用和权限拒绝
  都有正确的可访问反馈。
- [ ] 交接包包含 1--5 张互异正文图、独立封面和全部已选择的新闻上下文图；图片 role/order/SHA/MIME/
  尺寸与 manifest 一致，ZIP 路径无绝对路径或 traversal。未验证权利的上下文图仍可复制，但正文、
  rights manifest、预检和 UI 都显示非阻断的 `publish_permission_unverified` 状态。
- [ ] 320px/430px 浏览器 fixture 证明实际图片全部加载、无页面横向溢出、无外部资源请求；横向目录的
  主题内手势滚动可作为明确记录的预期行为。
- [ ] API/OpenAPI/生成 TypeScript、前端 mapper/hooks/components、后端与前端 focused tests 通过，
  development flag 关闭时新 UI 与端点不可用。
- [ ] 历史 renderer/bundle golden tests 保持不变；现有 fixture/live local review 导出、人工审稿和恢复语义
  无回归。
- [ ] 实施和验收期间微信、企微、发布、模型、Embedding、生图和新闻抓取调用均为 0；没有新增公众号
  凭据字段、自动发布入口或误导性的“已同步/已发布”状态。

## Out of Scope

- 微信 access token、IP 白名单、账号认证/权限、正文图上传、永久素材、草稿箱、发布、群发与数据回流。
- 自动浏览器登录或对真实公众号编辑器执行粘贴；真实账号验收只能在未来经单独授权的任务中进行。
- 富文本人工编辑器、拖拽排版、文章内容修订、自动批准、自动版权判断或从互联网补图。
- 修改朋友圈短文、素材包、企业微信交付、新闻采集、文章/Embedding/图片生成或生产部署语义。
