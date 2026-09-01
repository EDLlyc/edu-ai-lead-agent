# 公众号本地自动化与视觉优化 V2

## Goal

把已完成的 development-only 微信编辑器交接升级为真正可无人值守的本地流程，并提升小赛公众号正文的
新闻感、语义配图位置和视觉节奏。V2 必须允许通过已经持久化的确定性校验、模型审校和图片质量状态自动
放行，不要求人工点击批准；同时保留 V1 人工审核交接的版本身份、字节和历史阻断语义。

## Background and confirmed facts

- V1 已提交并归档，拥有独立 renderer/style/template/bundle/preflight/rights-policy 身份，默认测试和导出
  零外部请求，不调用微信或企微。
- V1 application gate 在
  `backend/app/application/services/official_account_editor_handoff.py:234-260` 强制要求不可变人工批准；
  这与用户最新确认的“不需要人审”目标冲突。
- V1 新闻上下文图只记录 `assigned_section_index`，renderer 在章节标题后、正文块前统一插入，见
  `backend/app/domain/official_account_editor_handoff.py:212-237`；它不能精确解释图片对应哪个正文块，且可能
  与正文图相邻。
- V1 `_emphasized()` 只用正则取每段第一个 4--14 字短语，见
  `backend/app/domain/official_account_editor_handoff.py:586-601`，不满足 `gzh-design` 每段 1--3 个语义重点的
  规则。
- 当前 V2 评审样例的 manifest 只有 3 张 body 图和 1 张 cover，未包含 context 新闻图；Playwright 已证明
  320px/430px 无页面溢出、3 张图片加载和 0 external requests，但交接包内 `mobile-validation.json` 仍为
  `not_run`，外部 sidecar 才记录 `passed`。
- 当前标题字号固定为 26px，目录卡固定宽 110px；样例标题 24 字、章节标题 22--24 字，并且 4 个 callout
  都渲染成同一深蓝卡，造成拥挤和模板重复感。
- 当前工作区有大量其他任务的未提交修改；公众号文件没有重叠 diff。实现必须检查每个高碰撞文件的局部
  diff，保留政府要闻及其他任务的所有改动。

## Requirements

### R1 — V2 additive compatibility

- 新增 V2 editor-handoff renderer/template/style/bundle/preflight/release-policy 身份；不得修改 V1 常量、V1
  golden、历史 Article Package fingerprint、历史 exporter 或恢复字节。
- V2 继续只从已持久化的 run/article/render/draft/media/audit 状态派生，不修改已批准文章，不新增微信、
  企微或社交发布动作。
- 运行时不读取 `/root/.codex/skills`；小赛主题组件和规则仍由项目内静态、哈希绑定的定义拥有。

### R2 — 可审计的自动放行

- 增加显式、版本化的 release policy：`manual_only` 保持 V1 行为；`quality_auto` 允许没有 manual review 的
  V2 运行在所有质量门禁通过时自动放行。
- `quality_auto` 至少要求：run/draft ready、simulation、Article fingerprint 与固定 render 谱系一致、
  deterministic validation passed、model audit accepted、全部所需媒体完整且图片质量状态没有明确失败。
- 已存在的人工 `rejected` 决定必须优先阻断，不能被自动策略绕过；已存在 `approved` 可以作为 manual
  release。没有人工记录时生成确定性的 machine release projection，记录 policy/version/input fingerprints
  和 gate codes，并进入 V2 manifest/ZIP；不得伪装成人工批准。
- 默认离线 fixture 与测试使用 `quality_auto` 且不构造 provider client；生产/非 development 环境和 flag
  关闭时继续 fail closed。

### R3 — 正文块级新闻图计划

- V2 为每张 context 图生成确定性的 placement projection：section index、目标 block index、插入方向、
  匹配理由/版本。优先使用 alt/caption 与正文块的语义词重合，信息不足时回退到章节第一个完整正文段后。
- 新闻图是 IP 正文图的补充，不替换 body image block；同一章节内按 block 顺序交错，两张图片之间至少有
  一个可见正文块。冲突时稳定顺延，不能丢图。
- manifest、article JSON/Markdown、API 和工作台展示 placement 与原始 source/credit/rights；
  `publish_permission_unverified` 仍只产生明确的非阻断 warning，绝不改写为已授权或事实证据。

### R4 — 确定性语义重点

- 不改变 Article Package 或调用模型。V2 从标题、digest、章节标题、数字/专名和正文已有短语中确定性评分，
  每个正文段落选择 1--3 个不重叠的 4--15 字重点；无可信候选可少标，但不能凭空生成文字。
- renderer 只切分并转义原文，将选择结果用小赛 AI 蓝下划线组件包裹；全文输出文本逐字拼回必须等于原始
  文本。选择规则和版本进入 V2 identity，并以中文、数字、危险字符和稳定重放测试覆盖。

### R5 — 自适应小赛版式

- 保持“小赛蓝（摸鱼绿原结构）”单主题和微信兼容骨架，不跨主题、不引入外部 CSS/字体、`class`、`id`、
  `display:grid` 或复制正文内脚本。
- 根据文章结构确定一种稳定 recipe（至少新闻解读、教程/清单、观点/案例），只改变组件组合与节奏，不
  改写文章事实或短文案。
- 标题按长度分档，目录卡按精选标题长度使用受控宽度/字号；保留最多 3 个核心目录项。深色锚点卡全文
  不超过 5 个，重复 callout 改用同主题的浅底提示/左竖条金句变体。
- 图片继续 `max-width:100%;height:auto;display:block;margin:0 auto`，所有可见文本仍使用 `span leaf`。

### R6 — 新闻场景离线样例与移动验收

- 新增一套含 3 张互异 IP body 图、1--2 张本地新闻 context 图和独立 2.35:1 cover 的确定性样例。来源、
  署名、未验证权利和 context-only-not-evidence 必须在正文、rights、manifest、API/UI 中可见。
- 默认 fixture/单元/浏览器测试不得联网；测试必须证明新闻图没有替换 IP 图、图片顺序符合 block plan、
  全部图片加载、320px/430px 无页面级横向溢出且 external request count 为 0。
- 浏览器报告必须绑定被验证的 content fingerprint/body SHA/media SHA。V2 本地导出采用两阶段身份：先固定
  content identity，再把通过的 browser report 纳入最终 artifact identity/ZIP，避免同一 artifact
  fingerprint 对应 `passed` 与 `not_run` 两套字节。普通 API runtime 未运行浏览器时必须诚实显示
  `not_run`。
- 工作台文案明确区分“当前运行未做浏览器验收”和“与当前 content fingerprint 精确匹配的离线验收已
  通过”，不得套用其他文章的 fixture 结果。

### R7 — 合同、测试、输出和文档

- 所有新增状态和 placement/release/mobile 字段通过 FastAPI schema、生成 OpenAPI 和生成 TypeScript
  传递；前端不得手写第二份 wire schema或使用 `dangerouslySetInnerHTML`。
- 更新 focused backend/frontend tests、独立 `gzh-design` validator、Playwright 和本地导出脚本；默认
  全套调用模型、Embedding、生图、新闻抓取、微信和企微均为 0。
- 生成一个新的本地 V2 output 目录，包含干净正文、独立预览、完整 ZIP、新闻图、IP 图、封面、通过的
  fingerprint-bound mobile report 和校验摘要；不得覆盖既有 V1/V2 输出目录。
- 文档用英文记录 release policy、新闻图 placement、recipe、浏览器报告身份和永久 no-publish 边界。

### R8 — 正文块驱动的 IP 参考生图

- 正文 body 图不得仅因为来自公司目录就称为 IP 图。每张新图必须从一个稳定正文块提取场景 brief，先从
  已批准的小赛视觉目录选择与该块语义和角色动作匹配的参考资产，再把参考图作为人物身份/造型锚点连同
  brief 提交给生图模型；最终正文使用新生成的场景图，不直接把目录原图当成正文成图。
- 生产路径优先复用现有 Qwen3-VL 完整索引的正文块级检索；离线 fixture 使用冻结且可校验的选择投影，
  但不得伪装成真实 embedding 调用。两种路径都必须保留 block index/fingerprint、safe public ref、角色
  `xiao-sai` / `sai-xiansheng`、选择方式、生成计划和输出校验谱系。
- 三张本地验收 body 图都必须能肉眼识别小赛或赛先生；整组三张必须同时覆盖小赛和赛先生，且不得把人物
  缩成角标、Logo、玩具、背景装饰或无法辨认的剪影。场景仍须对应各自正文块，并保持 3:2、无水印、无
  额外文字和独立图片内容。
- 默认测试继续使用本地 bytes/fake transport，模型、Embedding 和生图外部请求为 0；明确授权的本地成品
  生成可调用图片模型，但仍禁止任何微信、企微、上传、发布或群发调用。

### R9 — 每周一次、三篇独立文章

- 自动化交付单位是一个自然周批次，不是单篇文章内的三条新闻，也不是晨/午/晚三个日更槽位。每个周批次
  固定包含三篇可独立阅读、复制和下载的完整文章：`official_anchor`（官方主推）、`industry_trend`
  （行业趋势）和 `application_case`（教育/科创落地案例）。
- 三篇文章必须分别拥有独立 run/Article/evidence/media/body/preview/ZIP 身份；不得把三个事件合并进同一个
  Article Package，不得复用一个事件或一个成品 fingerprint 填充多个槽位。周批次只聚合已通过 V2
  `quality_auto`、移动验收和完整性校验的三个子产物，不修改子产物字节。
- 选题先复用现有治理、资格、硬 veto 和确定性分数，再施加周刊槽位偏好。官方主推只能由持久化来源类型或
  已认证 priority policy 证明，不能靠标题出现“教育部/官方”字样推断；优先本周，允许向前回看至 14 天。
  若 14 天内没有合格官方项，可用最高质量的剩余行业项补位，但必须记录
  `official_source_unavailable_fallback`，不得冒充官方来源。
- `industry_trend` 优先 AI 教育、教育数字化、机器人、前沿科技和产业进展；`application_case` 优先学校、
  区域教育、课程、赛事、科学探究和家庭科创实践。槽位偏好只能给已合格候选排序，不能降低阈值、移除
  veto、改变事实证据或让同一事件重复出现。
- 周期使用 `Asia/Shanghai` 的版本化星期/时间配置和周起始日期；同一周、相同策略和相同三个子产物必须
  产生相同批次 fingerprint/ZIP。输出是新的本地目录，含周刊索引、三篇文章子目录、批次 manifest 和
  确定性 ZIP；仍不调用微信、企微、上传、草稿、发布或群发接口。
- 默认 fixture/测试不抓新闻、不调用模型、Embedding 或生图。真实生产路径可在各子文章运行中调用已批准
  的新闻、Embedding 和图片 provider，但周刊聚合阶段只消费已持久化的通过结果。

### R10 — 公众号主页置顶运营交接

- 周批次仍固定为三篇独立文章。`official_anchor` 必须声明主页展示意图 `pinned_primary`，封面用途为
  `homepage_pinned_large_card_candidate`；`industry_trend` 与 `application_case` 必须声明
  `standard` 和 `homepage_standard_thumbnail_candidate`。这些字段只表达运营意图，不声称能够控制微信
  主页的大卡片、缩略图裁切或最终 UI。
- 三篇文章继续复用各自已经通过 V2 校验的 `assets/cover-wide.*` 封面 bytes。周刊层记录封面相对路径、
  hash、实际宽高、2.35:1 来源比例约束和系统裁切安全提示，不重新生图、不修改子目录或子 ZIP 字节。
- 本地 `index.html`、`weekly-index.json`、批次 manifest、README 和确定性运营发布清单必须显示三篇文章
  的展示意图、封面用途及操作顺序。官方文章的清单必须给出公众号后台
  “群发功能 → 已发送 → 找到文章 → 更多 → 置顶到公众号主页”的人工步骤；两篇普通文章明确无需置顶。
- 发布/置顶状态采用严格本地状态机：初始只能是 `not_published`；只有一个显式、类型化、批次绑定且可
  审计的外部发布确认事件才能进入 `awaiting_manual_pin`；只有另一个显式运营确认事件才能进入
  `confirmed`。不得跳级、重复应用事件、使用不匹配的批次/文章身份，或把创建草稿等同于已发布。
- 不可变周批次只内含初始 `not_published` 投影。后续状态生成独立、确定性、no-clobber 的运营 sidecar，
  绑定批次 fingerprint、官方文章 fingerprint、事件时间和安全的操作者引用；不得回写周批次或三个子包，
  也不得仅凭本地代码声称微信置顶成功。
- 本轮不新增微信/企微/API/前端能力，不调用公开或私有公众号接口，不执行后台浏览器自动化。微信主页卡片
  样式和实际置顶状态始终是微信系统及运营人员掌握的外部事实；fixture、测试与导出外部请求均为 0。

### R11 — 周刊离线图片角色隔离

- 三篇周刊 fixture 不得继续复制同一套封面或正文图。三个主页封面必须由已批准的本地品牌/内容资产按
  `official_anchor`、`industry_trend`、`application_case` 分别确定性合成，保持 2.35:1，且 SHA-256 与
  解码像素均互异；只改标题、alt 或文件名不算不同图片。
- 每篇文章的三张 3:2 正文图必须保留可见小赛和赛先生，并绑定该角色文章的正文块、场景 brief、参考资产
  校验和及输出校验和。三篇文章的有序正文图 hash 集合必须互异，且九张正文图的 SHA-256 与解码像素摘要
  必须全局唯一；默认 fixture 不得读取被忽略的历史 `output/` 目录，也不得伪装成实时新闻、Embedding、
  模型或生图调用。
- 周刊聚合必须 fail closed：重复角色封面、重复角色正文媒体集合、封面像素完全相同、正文集合字节重用或
  正文集合仅元数据不同但解码像素相同时拒绝构建。回归测试须同时解码图片、比较尺寸/像素摘要与 SHA-256，
  并继续证明外部请求与微信/企微调用为 0。

### R12 — 显式联网的三条独立新闻周刊

- 在离线 fixture 之外增加一个 development-only、显式 `--live-input` opt-in 的本地入口；只有该入口可对
  输入清单中已注册的 HTTPS 来源页和同源新闻图片发起请求。默认 fixture/测试继续零外部请求，且任一路径
  都不得构造或调用微信、企微、上传、草稿、发布或群发客户端。
- 输入必须恰好包含 `official_anchor`、`industry_trend`、`application_case` 三个角色，来源 URL、事件日期、
  发布者和事件身份都必须互异。官方角色只接受注册表中明确标记为 `government` 的来源；不得从标题推断。
  每个子文章只能绑定本角色实际抓取的 canonical URL、标题、发布日期、发布者、正文摘要、响应 SHA 和
  精确证据摘录，禁止从一个 base article 继承另一个角色的来源、claim、context 图或新闻文字。
- 复用现有安全正文 fetch、HTML extraction、同源图片发现和 raster 校验边界：HTTPS/host/path allowlist、
  公网 DNS 校验、有限重定向、总时限、响应/图片字节上限、MIME 与解码尺寸一致、最多两张 context 图。
  页面标题/日期/URL 与输入不一致、正文过短、图片跨域/带 query、不合格图片或三条正文/事件重复时 fail
  closed；不得用离线占位图或另一篇新闻的图片伪装抓取成功。
- 新闻原图仅作 `context_only_not_evidence=true` 的上下文媒体；保存实际图片 URL、source page URL、响应
  media type、字节数、SHA-256、宽高、抓取时间、caption/credit 和
  `publish_permission_unverified`。原图已有来源标记/水印必须保留并披露，不去除、不据此声称转载授权。
- 三篇文章仍分别使用各自的本地小赛/赛先生正文图与封面，并重新绑定正文块、证据、source、context media
  和所有 fingerprints 后再聚合。一次真实运行必须输出独立子目录、周刊索引、抓取审计与 ZIP；调用计数
  如实区分 source page、news image、model、Embedding、image generation、WeChat 和 WeCom。

### R13 — 一个周主题、三个角度与多来源新闻簇

- R12 的 `official-account-weekly-live-input-v1` 单来源输入继续可用；新增向后兼容、显式 opt-in 的
  `official-account-weekly-live-input-v2`。V2 顶层必须声明一个非空周主题，并按固定顺序包含
  `official_anchor`、`industry_trend`、`application_case` 三个文章新闻簇。每簇恰有一个 `primary`
  来源和一个 `supporting` 来源，任何来源不得跨簇复用。这个有界 MVP 因 Article context 快照最多两项而
  固定为每篇两条真实来源；若未来需要一主多辅，必须先版本化扩展 Article context 契约。
- 三篇文章围绕同一周主题但角度必须分别为官方/政策、行业/方法、应用/实践。文章标题可以是编辑后的主题
  标题，不必逐字复制主来源标题；但所有事实 claim、证据摘录、上下文原图和来源说明必须绑定产生它们的
  精确 source record，不得把 supporting 来源的事实归给 primary，也不得用一个簇的内容补另一个簇。
- 输入仍只能引用代码注册的 HTTPS 来源及窄化 URL；不提供任意 URL、搜索或递归爬取能力。所有页面和图片
  继续经过既有公网 DNS、SSRF、重定向、总时限、字节、MIME、解码尺寸与同源边界。官方文章簇的 primary
  必须是注册为 `government` 的认证政府来源；supporting 可来自注册的权威政府或主流媒体来源。
- 一个 V2 周批次内所有 canonical source URL、页面 SHA、event/version identity、evidence ID 和被采用的
  context-image SHA 必须全局唯一。每簇须保留 primary/supporting 角色、抓取元数据、逐来源 evidence 与
  图片 lineage；跨簇来源、证据、图片或身份泄漏时 fail closed。
- 新闻原图仍只作 `context_only_not_evidence=true` 的上下文材料，逐图披露来源、caption/credit、完整标记
  和 `publish_permission_unverified`，不去水印、不声称转载授权。V2 的 Article JSON/HTML、周刊索引、
  manifest 与版本化 live audit 都必须显示周主题、文章角度、primary/supporting provenance 及精确可变
  页面/图片调用数。
- 默认 fixture、R12 V1 测试和所有普通周刊路径保持零网络。V2 单元测试使用 MockTransport 与受控 resolver；
  指定 live CLI 的真实验收必须在最终聚合前完成 320/430 Playwright 校验，证明全部图片加载、copy root
  精确、页面无溢出且浏览器外部请求为 0。本切片不调用模型、Embedding、生图、微信或企微，也不构造社交
  客户端。

### R14 — 公众号草稿箱接口适配

- 新增独立的微信公众号（不是企业微信）application port 和 infrastructure client，固定访问
  `https://api.weixin.qq.com`，支持稳定接口凭证、上传正文图片、上传永久封面素材和新增草稿。不得复用
  WeCom `corpid/corpsecret`、域名或响应模型。
- 凭据只允许从 SecretStr 配置读取：`AppID`、`AppSecret` 不得进入日志、异常、序列化响应、manifest、ZIP、
  OpenAPI 示例或 git；默认配置关闭，缺失、空白或非 development 显式启用时必须 fail closed。access token
  只在进程内按服务端 `expires_in` 提前过期缓存，并对明确的 token 失效错误最多刷新重试一次。
- client 必须使用严格 HTTPS host/path、有限超时/连接池、响应字节上限、重复 JSON key 拒绝、HTTP/JSON/
  微信 `errcode` 三层错误映射和安全脱敏。图片上传只接受调用方已校验的 JPEG/PNG bytes、受控文件名与大小；
  multipart 字段、query token、草稿 JSON 合同由 adapter 唯一拥有。
- 新增 `draft_only` application service：依次上传正文本地图片并把 HTML 中精确安全的相对 `src` 替换为
  微信返回 URL，上传独立封面取得 `thumb_media_id`，最后调用 `draft/add`。正文中外部 URL、data/blob URL、
  未引用/重复/缺失媒体、路径穿越、符号链接、hash/字节漂移、非 allowlist HTML 或未通过 V2/周刊门禁时
  必须在第一条微信写请求前失败。
- 每篇文章创建独立草稿；三篇周刊不得拼成多图文草稿。返回安全的 draft receipt（role、Article/content
  identity、draft media_id、已上传图片计数和时间），创建草稿仍保持本地状态 `not_published`，不得伪装成
  `publication_confirmed` 或 `awaiting_manual_pin`。
- 默认 fixture、测试、现有本地 CLI/API/worker 不构造该 client，微信调用继续为 0。合同测试必须使用
  `httpx.MockTransport` 精确验证 stable token、multipart、图片 URL 替换、cover media ID、draft payload、
  token 单次刷新、错误/超时/重复 JSON key、零凭据泄漏和无 `freepublish`/群发调用。本轮不使用真实凭据，
  不向微信发请求。

## Acceptance criteria

- [x] `manual_only` 仍复现 V1 pending/approved/rejected 行为；V1 identities/goldens/ZIP byte regression 全部
      不变。
- [x] `quality_auto` 在无 manual review 且所有 durable quality gates 通过时生成明确的 machine release；
      任一 deterministic/model/image gate 明确失败或已有人工 rejected 时返回稳定 blocking code。
- [x] 一次 development-only 本地流程可从已持久化 Article Package 自动生成正文、新闻图+IP 图交错排版、
      封面、预览和 ZIP，无人工批准动作、无 durable side effect。
- [x] 每张 context 图的 manifest/API placement 指向稳定 block；正文中两图不相邻，新闻图不替换现有 body
      image block，来源/署名/rights/事实边界完整。
- [x] 每个有可信候选的正文段落包含 1--3 个语义下划线短语；移除标签后正文文字与输入逐字一致；重复构建
      的 HTML、content fingerprint 和 ZIP 字节一致。
- [x] 长标题和 22--24 字目录项在 320px/430px 下无页面溢出；相同深蓝 callout 不再机械重复，锚点层不
      超过 5 处；最终纯正文通过 `gzh-design` 0 ERROR/0 WARNING。
- [x] 新离线新闻 fixture 包含至少 3 body + 1 context + 1 cover；Playwright 绑定 content/body/media hash，
      所有图片加载、320/430 无页面溢出、0 external requests，最终 ZIP 内状态为 `passed`。
- [x] runtime 未验浏览器时仍显示 `not_run`；只有 content fingerprint 精确匹配的报告才显示 passed。
- [x] 三张 body 图都有可见且可识别的小赛/赛先生人物，整组覆盖两名角色；每张图的正文块 brief、参考
      public ref/角色、选择方式、生成计划和输出 hash 可追溯，且生产语义检索结果确实作为生图参考输入。
- [x] 一个周批次稳定选择并导出三篇独立文章，顺序为官方主推、行业趋势、应用案例；事件、run、Article、
      content/artifact fingerprint 与子 ZIP 均互异，官方 14 天回看和非官方补位均如实记录。
- [x] 周刊调度在 `Asia/Shanghai` 下每周仅到期一次；重复执行不覆盖已有目录，三篇子产物逐字节不变，批次
      manifest/索引/ZIP 绑定完全一致，默认构建阶段外部请求为 0。
- [x] 官方主推与两篇普通文章分别导出 `pinned_primary`/`standard` 展示意图和绑定现有封面的用途规格；
      清单含确定性人工置顶步骤，主页裁切与 UI 明确标为微信系统所有。
- [x] 初始导出只能是 `not_published`；显式发布确认只生成 `awaiting_manual_pin` sidecar，显式运营置顶确认
      才生成 `confirmed` sidecar，非法跳级/身份错配均失败且三个子包与批次字节不变。
- [x] 三个角色封面保持 2.35:1 且 hash/解码像素互异，三套 3:2 正文图的有序 hash 集合互异并保留可见
      小赛/赛先生；默认 fixture 不依赖历史 `output/`，聚合会拒绝重复封面或重复正文媒体集合。
- [x] 一次显式 live 本地运行真实抓取三条不同来源事件和各自新闻原图；三个 Article 的 title/source/date/
      evidence/context-image SHA 均按角色独立，新闻页/图片调用数与最终 bytes 可审计，模型、Embedding、
      生图、微信和企微调用为 0；任一抓取/校验失败时不生成成功批次。
- [x] 一次 V2 live 运行以一个明确周主题聚合三个固定角度的文章新闻簇；每簇一个 primary 和一个
      supporting 真实来源，共抓取六个全局互异页面及六张全局互异原图，逐 claim/evidence/image 可回溯
      到精确来源，并在 Article、HTML、周索引、manifest 和 audit 中保持一致。
- [x] 默认关闭的公众号 adapter 能以 MockTransport 完成 stable token → 正文图上传/URL 替换 → 封面永久
      素材 → 三篇独立 `draft/add` 合同；缺失凭据、无权限、token 失效、超时、坏响应和本地媒体漂移均
      fail closed，任何输出/日志不泄漏 secret/token，且没有 `freepublish`、群发、置顶或真实微信调用。
- [x] focused Ruff/format/mypy/pytest、OpenAPI drift、frontend lint/typecheck/Vitest/build、Playwright、历史
      official-account regression 与 `git diff --check` 通过；默认测试没有微信/企微调用或账号凭据字段。

## Out of scope

- 微信发布、群发、主页置顶、公众号登录、后台浏览器自动化或真实编辑器自动粘贴；本轮只实现默认关闭的
  `draft_only` 服务端适配与 MockTransport 验收，不做真实微信联调。
- 自动判断新闻图片版权、把 `publish_permission_unverified` 改成已授权，或把品牌知识当作外部事实证据。
- 通用新闻 worker、数据库采集拓扑和 Embedding/生图 provider 本身；R12 只新增显式 opt-in 的本地安全抓取
  与文章投影，不改变默认 worker/fixture 行为。
- 微信多图文草稿的三篇排列、封面裁切、自动发布与群发；三篇文章仅允许分别创建独立草稿。
- 删除 V1 人工审核能力、迁移或重写历史包；`manual_only` 继续作为兼容/回滚路径。
