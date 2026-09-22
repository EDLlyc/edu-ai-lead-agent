# 9 月 21 日单篇草稿补建与前向自动化修复设计

## 1. 目标边界

生产现状是 M/W/F 单篇模式已经调度成功，9 月 21 日失败在视觉阶段。设计分成两个相互独立、可单独停止的交付：

1. **精确历史补建**：只处理现有 2026-09-21 edition，复用已通过的 Article/render，创建一个未发布草稿。
2. **前向修复部署**：让新日期冻结 V4 容错几何视觉策略，并修复 schema 健康声明；不让普通 scheduler 自动回放过去日期。

第 1 个交付已完成官方回查和幂等复核，用户已确认处理第 2 个交付。当前实施前向自动化与服务器部署，保留历史补建状态；不再次触发已完成的补建操作。

不从当前根目录构建生产镜像。实现基线从 release-hardening 已提交的 `720305b...` 派生到隔离 worktree；现有未跟踪/并行文件保持不动。

## 2. 只读生产基线与恢复分流

在任何模型或微信调用前，通过现有 SSH 主机别名和生产脚本采集安全摘要：release/image/schema、12+2 服务健康、互斥模式开关、目标 edition/run/Article/render/visual/attempt 聚合、owner、journal 与远端草稿存在性。

恢复只接受闭集：目标是 9 月 21 日唯一 failed edition，Article 与 render 均已通过，未 prepared、未 receipt、未 local draft、无 lease；第 0 个视觉 slot 的三个物理请求均已持久化为 unknown（503、timeout、timeout）。这些请求和原 V3 run 保持不可变；本次补建通过新的显式跨日授权优先生成文章专属图片，并保留整套品牌素材兜底。任何目标、所有权、文章/render 或 journal 漂移都停止，不创建新的模型或微信 intent。

## 3. 历史补建 operator

普通 edition 的截止日与 business date 绑定，不能安全地把 9 月 21 日的 `expires_at` 改到 9 月 22 日。使用现有私有 journal 与 checkpoint 建立 operator-owned backfill 状态，不改变调度规则，也不为一次性补建新增数据库迁移：

- 稳定键：account fingerprint + business date + target edition/run + operator version；同一目标最多一个 backfill。
- 状态：planned → authorized → generating → preparing → draft_intent → delivered，另有 failed/outcome_unknown。
- 冻结内容：原 Article/render/selection/event/owner 指纹、三次 unknown 尝试摘要、五个新 visual intent 的稳定身份与调用上限、五张已选品牌素材的 catalog/version/checksum、两小时当前日截止、账号身份和目标 draft-only 权限。
- 视觉优先路径：旧请求绝不重放。为 body slot 0..4 分配五个新的、可审计的 recovery physical identity，按顺序调用，每个 slot 最多一次、整篇最多五次；每次先写 durable intent。五次全部明确成功且逐字节/几何/身份校验通过，才使用文章专属图片构建 prepared contract。
- 视觉兜底路径：任一新请求明确失败或结果 unknown 时，停止后续 provider 调用；已成功图片和未知 attempt 只保留为证据，不进入草稿。读取并逐字节复核 Article 已冻结选择的五张小赛品牌素材，整套 media origin 记为 `approved_catalog_fallback`，不混用生成图与品牌图。
- 组装：用原正文、render、选定的完整五图集合、封面、程岳头图、小赛营销尾图和无来源链接规则构建 versioned prepared contract；不重新生成新闻正文。
- 微信：沿用持久化 private journal 和 `JournaledSingleDraftClient`，逐步 intent-before-write；只调用临时素材上传和一次 `draft/add`，绝不调用 publish/mass-send/delete/update。
- 对账：ACK 后官方只读查询匹配目标标题/作者/内容指纹；再以 ACK 为事实源把 backfill 标记 delivered，并对账 edition receipt/owner。数据库提交失败可从 journal ACK 恢复，不能再次 `draft/add`。

operator 默认是 plan，仅显式 `--apply` 可产生外部副作用。重复 plan/apply 必须复用冻结授权、素材校验结果与 draft ACK；任何 unknown 终止整条恢复。

## 4. 前向运行修复

新日期采用 `official-account-visual-pipeline-v4-resilient-tolerant-geometry`：provider 原始图仍必须满足有界尺寸/比例/像素数，之后确定性裁剪缩放为 1536×1024。每 slot 最多三次持久化物理请求；身份不匹配、鉴权、配置、lease 丢失、过期和无法解码继续硬失败。三次耗尽或 unknown 时，不再发第四个图片请求，而是使用该 Article 已冻结、逐字节验证的五张合规品牌素材构建新的 fallback prepared identity；界面和审计记录必须如实显示视觉兜底。事实审查、素材来源、HTML、五图一封面、draft-only 均不放宽。

同步把 release migration compatibility 头改为实际 `20260916_0048`，构建不可变 digest。发布前停写、做完整备份和二次预检；只替换应用服务，不重建 PostgreSQL/MinIO，不降级 schema。

当前生产使用既有离线 OCI 发布路线，缺少标准 registry release manifest/current.json。此次沿用已验证的基线镜像层，从新提交的 Git blobs 构建本任务的离线候选与独立发布记录，不伪造标准流水线来源。数据库已经处于 0048，发布不执行迁移或 seed。发布失败时优先以前向兼容的新镜像和原 V3 配置恢复，不能证明健康则停止公众号 writers。

健康检查区分已过期且无 lease 的历史 `outcome_unknown` 与当前/活动未知任务。历史状态及原有 attempts/ACK 全部保留并显式显示历史告警；当前未知任务、过期 lease 或正在交付的异常仍阻断健康验收，不因部署删除或重放历史记录。

## 5. 部署顺序

1. 本地 fake-client 和隔离 PostgreSQL 完成 exact-target operator 检查，建立不可变 operator 包和哈希。
2. 生产只读预检和稳定双采样；若状态漂移则停止。
3. 在当前生产镜像边界内运行 operator plan 并独立复核；只执行一次 apply：最多五次 journaled 生图调用，全部成功则使用专属图，任一失败/unknown 则立即整套 fallback；随后 prepared、journaled `draft/add`、只读回查和数据库对账。
4. 再次运行 plan/apply，证明没有新增媒体/`draft/add` 写；至此先完成 9 月 21 日草稿补建。
5. 再构建包含前向 catalog fallback、V4 修复和 0048 健康对齐的不可变应用候选、manifest 与恢复手册。
6. 备份后部署候选，验证 0048 健康声明、12+2 服务、模式互斥、零异常重启和下一个 M/W/F 窗口。

## 6. 失败与恢复

- 候选部署前失败：不改生产。
- 停写后、迁移/切换前失败：恢复原应用服务和保护文件。
- schema 已是 0048：禁止降级；使用兼容候选前向恢复，必要时保持公众号 writers 停止。
- 品牌素材缺失、checksum 漂移或 prepared 校验失败：在微信写入前停止，不临时改用未冻结素材。
- 新生图明确失败或 unknown：停止后续模型请求，保留 intent/结果和已成功图片证据，整套切换到已冻结品牌素材；不复用请求身份，不混合视觉来源。
- `draft/add` unknown：保留 intent/unknown，不重发；转人工核对。
- `draft/add` ACK 后数据库对账失败：只从 journal ACK 恢复数据库状态，不再调用微信。

## 7. 隐私与证据

任务记录只写 commit/digest、schema、状态、计数、错误码和不可逆 fingerprint。不得记录 token、AppSecret、media_id、草稿 URL、签名素材 URL、正文、provider 原始响应或私有 journal 内容。

## 8. 小赛 AI 胸牌候选图修正

已建草稿使用生产旧镜像中的旧提示词，旧提示词明确禁止任何字母或胸牌，因此五张图缺少小赛胸前的 `AI`。修正批次不重放首批请求，也不修改草稿或数据库：它以已经冻结的 Article、render、参考角色和五个原视觉位置为只读输入，采用 `720305b...` 中已经审查的胸牌规则，为五个位置建立新的 durable intent 和内容寻址结果。

提示词把胸牌设为角色身份的硬约束：小赛胸前必须出现居中的蓝色小面板与白色 `AI`；除该 `AI` 外禁止其他可读文字、字母、数字、logo、水印或二维码。每个位置只允许一次新请求，本批次总调用数最多五次。结果只写私有 journal 与对象存储，不构造微信 client，不执行媒体上传、`draft/add`、`draft/update`、发布或数据库对账写入。

生成后将五张内容寻址图片导出到任务证据目录并逐张目视检查。只有五张都清楚显示规定胸牌时才把该批次记为候选图验收通过；任一张不通过则记录位置和结果、停止本轮，不自动追加调用。用户确认候选图之前，现有公众号草稿保持不变。

## 9. 同一草稿原位替换

用户确认五张候选图后，在微信 draft-only runtime 内执行独立的 exact-target replacement operator。operator 从补建 journal 的原始 `draft/add` intent/ACK 解析既有草稿 media identity，以官方 `draft/get` 先验证当前草稿仍等于已回查通过的原始内容；再从胸牌生成 selection receipt 和 MinIO 读取并逐字节校验五张 JPEG，不接受本地未绑定文件或其他批次图片。

替换只改正文 HTML 中原有五个 generated body image URL，保留程岳头图、小赛营销尾图、全部文本/链接、图片位置与顺序、标题、作者、摘要、封面 media identity 和评论设置。五次 inline image upload 均 intent-before-call；五个上传 ACK 齐全后才写一个 `draft/update` intent。`draft/update` 返回 ACK 后必须通过官方 `draft/get` 验证同一 media identity、非图片字段不变、正文可见 token/链接不变、七图拓扑不变且中间五图恰好是新上传 URL。

任一 upload 或 update 结果 unknown 时不得重放。若 update unknown，operator 只比较官方读回：完全匹配则写 readback receipt，否则报告 `outcome_unknown_reconcile_only`。整个流程禁止 `draft/add`、publish、mass-send、delete 和数据库业务写入；重复 apply 只能复用既有 intent/ACK/readback，不产生新的微信写入。

## 10. 已发布文章的修正版再入草稿箱

生产只读预检已证明原 draft media identity 返回 40007、草稿列表中不存在目标，而发布列表存在唯一的标题/作者/摘要/链接/七图结构匹配记录。用户随后明确授权重新创建草稿。新 operator 不尝试修改或删除已发布记录，而是从官方 `freepublish/batchget` 唯一匹配项冻结当前发布 article：标题、作者、摘要、正文 HTML、链接、封面 media identity、评论设置以及第一/第七张头尾图均以发布记录为准。

operator 从 `badgefix-...-v1` manifest/selection/results 和 MinIO 逐字节读取五张人工验收图。写阶段为五次 intent-before-call 的 inline upload；齐备后将发布正文中第 2–6 张图片 URL 原位替换，形成一个新的 `draft/add` request。新的 namespace 与原补建、胸牌生成和失败的同稿替换完全分离，并绑定发布 article fingerprint、原发布记录身份 fingerprint 和五个候选 SHA。

`draft/add` 只有一个 intent。ACK 后用官方 `draft/get` 验证新草稿字段、正文投影、七图拓扑和五张新 URL，再通过 `draft/batchget` 证明目标草稿唯一。若 add 结果 unknown，禁止再次 add；只允许 batchget 对比完整 request 寻找唯一新增项，唯一精确匹配时才写 reconcile ACK，否则保持 unknown。重复 apply 只能复用五个 upload ACK 和同一 add ACK/readback，外部写入为零。

整个修正版流程禁止 `draft/update`、`freepublish/submit`、publish、mass-send、delete 和数据库业务写入；当前发布文章保持不变。
