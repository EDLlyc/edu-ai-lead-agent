# Research: 公众号自动化、小赛 AI 案例与本地优化基准

- Query: 公众号文章的可靠自动化生成、人工门禁、导出包；教育/科学/亲子内容的写作和移动端排版；“小赛AI / 小赛 AI / 小赛ai / 赛先生”在青少年科学教育语境下的公开案例
- Scope: mixed（内部代码 + 公开网页/开源项目；不访问 `mp.weixin.qq.com`、`api.weixin.qq.com`，不登录、不调用微信接口）
- Date: 2026-08-22（Asia/Shanghai）

## Findings

### 1. 结论摘要

当前实现的工程骨架是可靠的：受治理素材、事实/品牌/观点分型、严格 JSON、确定性校验、模型审校、不可变版本、固定 HTML renderer、本地媒体与模拟草稿均已存在。下一轮不应推翻这条链路，而应补上运营级的五个缺口：

1. **人工审稿必须成为独立且可持久化的门禁**，不能让技术状态 `ready` 暗示“文章已批准”。
2. **生成提示词需要从“满足 schema”升级为“满足读者任务”**，加入目标家长/年龄段、单一核心信息、证据边界、可行动任务、反方/适用边界和移动阅读规则，并提升 prompt/rule 版本，保留 v1 字节兼容。
3. **封面与正文视觉要分工**。当前两种角色复用同一源文件；应本地派生独立横版封面和方形安全裁切信息，正文图则服务于某个具体段落。
4. **导出必须成为正式 CLI 能力**，原子地产出文章、图片、截图、审稿/预检/来源/哈希清单和 ZIP，而不是人工拼装输出目录。
5. **平台预检应是版本化、可配置、纯本地门禁**。公开二手资料对标题上限存在 32/64 字冲突，不能把未经账号实测的数字伪装成绝对真值；应选择保守默认、记录规则来源和版本，并允许后续在新任务中用真实账号校准。

“小赛 AI”方面，能高置信确认的是其青少年科学教育品牌表达与内容方法，而不是某套可复制的公众号 HTML 模板。官方站可验证的关键词是“安全、聚合、可控”“AI+人工双重审核”“成长与监护”“懂教育、有边界”，案例采用“年级 + 孩子做了什么 + 可见产出”的短卡片结构。由此最值得借鉴的是**内容结构和信任机制**，不是照抄宣传口号或未验证的视觉样式。

### 2. Files found

| 文件 | 一句话说明 |
| --- | --- |
| `.trellis/tasks/08-21-wechat-official-account-local-draft-mvp/prd.md` | MVP 明确只做本地模拟草稿、零微信请求、双入口、事实/品牌隔离和可恢复状态。 |
| `.trellis/tasks/08-21-wechat-official-account-local-draft-mvp/design.md` | 定义 Article Package v1、固定 renderer、不可变工件和本地媒体/草稿边界。 |
| `.trellis/tasks/08-21-wechat-official-account-local-draft-mvp/implement.md` | 现有实施与验证顺序；优化不能破坏短文、素材、WeCom 兼容合同。 |
| `.trellis/spec/backend/agent-pipeline.md` | 已实施的公众号本地草稿可执行规范，尤其是零外联 fixture 与不得出现 publish 控件。 |
| `backend/app/domain/official_account_local.py` | Article Package、claim 绑定、校验、v1/v2 renderer 和样式 token。 |
| `backend/app/application/services/official_account_local.py` | prompt、审校 prompt、持久化 stage workflow、正文/封面媒体与模拟草稿组装。 |
| `backend/app/infrastructure/ai/official_account_local.py` | Zhipu/OpenAI-compatible 严格 JSON、禁用 thinking、有限 correction 和安全指标。 |
| `backend/app/infrastructure/official_account_local.py` | 离线 fixture、确定性 generator/auditor、单源媒体适配器和本地草稿适配器。 |
| `backend/app/official_account_local_cli.py` | 目前只有 `fixture` / `live`，尚无正式 `export`。 |
| `frontend/src/features/official-account-local/OfficialAccountLocalPanel.tsx` | 开发态工作台、阶段时间线、来源/claim/preview 展示，但没有人工批准动作。 |
| `output/official-account-local/editorial-v2-b6f8307d/` | 当前 7 文件本地成品；正文图与封面图 SHA-256 相同，运行详情的 `manual_review_status` 为 `pending`。 |

### 3. Internal code patterns and concrete gaps

#### 3.1 已经正确、应该保留的合同

- Pydantic 模型冻结并 `extra="forbid"`，适合把模型输出限制为不可变 Article Package，而不是让模型生成 HTML（`backend/app/domain/official_account_local.py:52`）。
- `external_fact` 只能绑定 evidence，`brand_statement` 只能绑定 brand chunk，`opinion` 不能绑定两者（`backend/app/domain/official_account_local.py:113`）。这是比多数公开“公众号生成器”更强的事实治理能力，应保留。
- Article Package 记录 renderer/style/template 版本和内容指纹（`backend/app/domain/official_account_local.py:226`、`backend/app/domain/official_account_local.py:238`）。v1 和 v2 renderer 分派已能保护历史输出（`backend/app/domain/official_account_local.py:727`、`backend/app/domain/official_account_local.py:850`）。
- 生成请求只接受受限数据投影，模型系统消息禁止 HTML/URL，temperature=0，响应走 JSON object，输出再过 schema correction 上限（`backend/app/application/services/official_account_local.py:102`、`backend/app/infrastructure/ai/official_account_local.py:125`）。
- workflow 在每个不可变工件后持久化并可恢复；正文/封面角色 ID 分离，模拟草稿不含任何账号参数（`backend/app/application/services/official_account_local.py:360`、`backend/app/infrastructure/official_account_local.py:258`）。
- 前端持续展示“本地模拟，未同步公众号”，没有 publish/send/login 控件（`frontend/src/features/official-account-local/OfficialAccountLocalPanel.tsx:54`）。

#### 3.2 人工门禁缺口（P0）

- `ArticleQualitySummary` 虽有 `manual_review_status` 字段（`backend/app/domain/official_account_local.py:218`），fixture 将其设为 `pending`（`backend/app/infrastructure/official_account_local.py:83`），但模型 audit 接受后仍会继续 render/media/draft（`backend/app/application/services/official_account_local.py:340`）。当前成品 `run-detail.json` 同时出现 `status="ready"` 与 `manual_review_status="pending"`。
- UI 只有技术 stage、错误重试和详情展示，没有“批准/退回”以及批准所绑定的 content/render 指纹（`frontend/src/features/official-account-local/OfficialAccountLocalPanel.tsx:230`、`frontend/src/features/official-account-local/OfficialAccountLocalPanel.tsx:336`）。
- 建议新增独立的本地 editorial review 工件，而不是复用模型 audit：`pending|approved|changes_requested`、reviewer display name、五维分数/阻断项、content/render fingerprint、时间戳。正文或 renderer 指纹变化后旧批准必须失效。
- 技术 `ready` 可以继续表示流水线完成，但 UI、export manifest 和 README 必须明确 `editorial_approval=pending|approved`；若定义“可交付包”，则只有 approved 才能产出无水印 final，pending 只能产出 review bundle。

这一建议与 2025 年 UTS 对多家编辑机构准则的汇总一致：AI 结果要经过人类核验，发布前由具备权限的编辑批准；典型生产链是 `human → machine → human`。开源内容工作室也把 `draft.md` 和 `article.md` 分离，只有 `decision=pass / publishable=true` 才生成成稿。

#### 3.3 生成 prompt 偏“结构正确”，缺少“读者任务”（P0）

当前 prompt 规定 schema、claim 引用、作者、长度和 3–7 个章节，但没有明确：

- 目标读者是哪个年龄段孩子的家长；
- 一篇只解决哪个核心问题；
- 开头两段给出什么结论/价值；
- 科学术语如何解释、未知与适用边界如何表达；
- 至少一个怎样可执行的家庭探究任务；
- 是否禁止虚构“某位家长/孩子说过或做过”；
- 手机端段落和标题的可扫描性。

证据见 `backend/app/application/services/official_account_local.py:102-116`。建议保持 schema v1 不变，新增 `official-account-generator-v2` / `official-account-rules-v2`，把以下内容作为版本化写作策略：

1. 先确定 `audience_age_band`、`parent_question`、`one_sentence_takeaway`；没有受治理输入时不得编造具体家庭故事。
2. 开头使用“可识别的家庭问题/观察”，但只能是一般化场景；若写具体人名、学校、比赛、对话，必须有对应 evidence。
3. 正文采用：`问题场景 → 核心判断 → 科学解释/证据 → 家庭小任务 → 观察与复盘 → 边界/下一步`。
4. 每节只承担一个任务，标题前 8–12 个汉字尽量携带信息，不写纯情绪化标题。
5. 必须提供一个可执行模块：材料、3–5 步、观察问题、家长可说的话、安全提醒/适龄边界。不要把“课程转化 CTA”混入普通科普文章。
6. 外部事实写明来源和不确定性；品牌观点不能冒充科学事实；“突破、唯一、第一、保证、升学硬通”等词需要直接证据且应触发额外复核。
7. 生成阶段建议正文段落 1–3 句；以 110–130 个汉字作为本项目的软提示而非行业硬标准，超长段落拆分为列表/步骤/提问卡。

NIH/CDC 的公开写作指南支持“一个主要信息、重要内容先放、短章节、标题、通俗语言、必要术语解释、视觉靠近相关正文、明确行动建议”；科学传播还要求避免夸大研究显著性和误用“突破/奇迹”等措辞。

#### 3.4 小赛 AI 可验证内容模式及其应用（P0/P1）

**高置信品牌证据：**

- 官方站 `xiaosaiai.com` 自称“小赛AI星球”，把核心能力组织为安全护栏、AI 创意工坊、成长与监护，并明确写有 13 类动态敏感词库和“AI+人工”双重审核。
- 官方站的三个案例卡都是“年级 + 孩子动作 + 具体产出”：五年级用 AI 把古诗做成动画；四年级用多模态工具做非遗作品；三年级探究丁达尔原理并生成互动实验。
- 官方站用“星球 / 宇宙 / 探索 / 成长伙伴”作为持续叙事词，并把家长角色从单纯监管扩为可感知的协作与反馈。
- 2026-01-30 的 IT之家品牌报道、2026-03-13 东方网企业频道稿和 2026-04-27 界面转载稿均把小赛 AI 与“赛先生科学”关联，并强调 PBL、真实问题、孩子完成判断、家庭协作和 AI 安全；这些媒体稿含企业宣传成分，具体荣誉/首创/规模不能在本项目中无条件视作事实。

**可以转化成文章结构的模式：**

- `孩子做了什么`，而不是 `AI 有多强`；
- `过程证据/作品`，而不是抽象的“能力提升”；
- `家长如何协作`，而不是制造家长焦虑；
- `安全边界和人工复核`，而不是暗示全自动可靠；
- `问题—创作—验证—表达`，与当前 fixture 的科学探究循环一致。

建议在生成规则中引入“小赛式案例卡”的**结构**，但不复制未授权内容：

```text
孩子的任务：今天要观察/制作/验证什么
看见的证据：记录到什么变化或产出
家长的角色：问哪两个问题，不替孩子得出结论
下一次迭代：改变哪个条件再试一次
```

具体学生案例只有在素材包提供已授权、去隐私化证据时才能生成。fixture 可以继续用泛化任务，不应把官网三个孩子案例复制进脱敏样例。

**视觉方向只能作为推断：** 官方索引可确认“AI星球宇宙探索插图”“数字绿盾/安全围栏”等意象，但本次没有直接访问其公众号文章，也没有取得可归属的小赛公众号长截图。因此可新增“探索任务卡/轨道编号/安全提示”一类语义模块；具体配色、字体和公众号模板不能宣称来自小赛 AI。当前温暖教育杂志主题可保留为默认，另做版本化的 science-explorer 主题时需要独立视觉评审。

#### 3.5 不同名主体必须隔离

搜索结果里至少有三组容易误判的主体：

1. **小赛AI / 小赛AI星球 / 赛先生科学**：本次目标相关的青少年科学教育品牌；官方域名 `xiaosaiai.com`，教育品牌网站为 `sxsstem.com`，媒体公开稿给出两者关系。
2. **“赛先生”科学文化公众号**：公开索引使用 `mrscience100` 或旧资料中的 `iscientists`，是科学文化/公共传播品牌，不等同于少儿教育机构“赛先生科学”。它的权威科普内容定位可以作为通用写作参照，但不能当作小赛案例。
3. **中新赛克“小赛AI”与赛轮轮胎“小赛”助手**：企业内部知识问答/办公助手，与青少年教育无关，必须排除。

#### 3.6 移动写作和版式（P1）

- 135 编辑器公开参数建议一般正文 15px、字间距约 1.5、行距约 1.75、深灰正文；2026 年页面建议正文 15–16px、小标题 16–18px、一级标题 20–24px、来源 12–14px、正文行距 1.6–1.8、段距 10–16px、单一点缀色。
- 当前 v2 的 15px / 1.85–1.9 / 20px 段距总体合理（`backend/app/domain/official_account_local.py:629-725`），无需大改字号体系。
- 当前朱砂色 `#b9573f` 作为 12px 小字时，在 `#f2ede2` 上的本地计算对比度约 3.999:1，在 `#fbf8f1` 上约 4.402:1，低于 WCAG 2.2 普通文本 4.5:1。建议调为 `#ad4f39`（在 `#f2ede2` 上约 4.549:1）或更深，并为所有 token 写自动对比度测试。
- 当前正文使用 `text-align:justify`。W3C 的 AAA 可视呈现说明指出两端对齐可能制造不规则空隙；中文公众号常用两端对齐，两种建议存在语境差异。较稳做法是对 390/430px 截图做人工视觉验收，并优先避免超长连续文字，而不是仅靠对齐方式解决密度。
- 小标题应承载信息而非只写“写在最后”；第一屏应在题头/摘要后迅速回答“这篇对家长有什么用”。本地 preview 可以显示完整题头，未来真正平台正文片段应能选择不重复平台已经展示的标题、作者和摘要。
- 图片应靠近它解释的段落，图片内少放小字号文字，alt/caption 说明“读者应该看什么”，而不是复述标题。

#### 3.7 视觉与媒体工件（P0）

- Article Package v1 只允许 `body-0` 与 `cover-0`（`backend/app/domain/official_account_local.py:206-215`），而且 builder 永远把唯一正文图插在第一节（`backend/app/domain/official_account_local.py:361-378`）。
- worker 对 body 和 cover 使用同一个 `source_media.sha256`、media type 和 byte size，只用 role 改变指纹（`backend/app/application/services/official_account_local.py:375-439`）。当前导出两张 PNG 均为 1,392,227 bytes，SHA-256 都是 `120295d1743380b584239c385dfd93266d7b30c850c3e98291cd9e3f7a29b9af`。
- 短期不必破坏冻结的 Article Package v1：可以在本地媒体适配层从已验证源图确定性派生 `cover-wide` 与 `cover-square`，保留原始 checksum + transform version + 输出 checksum。不得静默覆盖源图。
- 中期若要 2–3 张正文图，应该新增 Article Package v2/visual plan，不要扩大 v1 literal。视觉槽按章节语义决定，不应按固定字数机械插图；每个槽记录用途、对应段落、alt、裁切安全区、正/负提示和验收状态。
- 远程生图不属于默认 fixture。若未来启用，也必须显式授权数量/费用，只重做不合格槽位，并维持 default tests/fixture 零外联。

#### 3.8 平台预检（P0）

当前 schema 允许 title 120、digest 240、author 80（`backend/app/domain/official_account_local.py:179-186`），这是内部 Article Package 上限，不应该直接等同于平台字段上限。

非微信域的 WxJava 4.4.0 Javadoc 记录：正文 HTML 少于 2 万字符、小于 1 MiB、JS 会被移除，外部图片会被过滤，正文图片要使用专门上传得到的 URL。其他 2026 二手文档对标题上限给出 32 字，而一些开源项目仍写 64 字；这说明平台约束资料有版本/口径差异。

建议实现 `wechat-draft-preflight-v1`，但保持纯本地：

- 规则表带 `rule_version`、来源 URL、访问日期、保守/已验证状态；
- 对 title/author/digest 同时检查内部上限与保守平台上限，错误明确指出是哪层约束；
- 检查 UTF-8 字节数、HTML 字符数、HTML 字节数、允许标签/属性、placeholder 清零、图片 URL 来源类别、封面角色、图片 media type/byte size/dimensions、链接协议；
- 输出 `preflight.json`，每条含 code/severity/field/observed/limit/rule_version；
- 未经真实账号验证的上限标为 conservative，而不是声称“官方已验证”；
- 未来真实微信适配器必须是另一个新任务。本任务不能因为有 preflight 就加入任何微信调用。

#### 3.9 正式一键导出包（P0）

CLI 目前只定义 `fixture` 和 `live`（`backend/app/official_account_local_cli.py:19-29`），现有 `output/` 目录是人工导出的演示成品。可靠实现应新增类似：

```text
python -m app.official_account_local_cli export \
  --run-id <uuid> \
  --output-dir output/official-account-local
```

建议的不可变本地包：

```text
<run-prefix>-<content-prefix>/
├── README.md
├── article.json                 # 安全 Article Package 投影
├── article.md                   # 人工复核友好的纯文本成稿
├── article-body.html            # 平台正文片段，不含本地工作台 chrome
├── preview.html                 # 自包含本地预览
├── preview-mobile.png           # 固定 390 或 430px 视口
├── assets/
│   ├── body-00.png
│   ├── cover-wide.png
│   └── cover-square.png
├── sources.json                 # 来源、claim 绑定、核验状态
├── review.json                  # 模型 audit + 人工 editorial approval
├── preflight.json
├── manifest.json                # 文件名、大小、sha256、版本和指纹
└── <same-name>.zip
```

实现约束：

- 写入临时 sibling 目录，全部校验通过后原子 rename；目标已存在且 manifest 不同则拒绝覆盖。
- manifest 路径只能是规范化相对路径，禁止绝对路径、`..`、凭据和内部对象路径。
- ZIP 内路径与目录结构一致；打包后重新校验每个成员的 hash/size。
- screenshot 不可用时明确 fail 或 `not_run`，不能悄悄冒充成功。
- review bundle 可导出但必须带 `NOT-EDITORIALLY-APPROVED` 水印/清单状态；final bundle 必须绑定批准指纹。
- fixture 导出不得访问任何网络；HTML 不含 API 地址依赖；图片必须是本地相对路径或发布稳定版内嵌形式。

公开的 `wechat-article-pipeline` 项目采用了原稿 hash、正文顺序、图片证据、390px 截图、HTML 校验、隐私审计和 workflow result，这些工件比“只给 HTML 和 ZIP”更可复核。另一个内容工作室把 brief/claims/sources/draft/article/review/layout/quality-gates 分文件保存，值得借鉴其工件边界，而非复制其发布实现。

### 4. Prioritized local-only implementation map

#### P0 — 本轮最值得做

1. `official-account-generator-v2` / `rules-v2`：加入目标读者、单一主旨、反虚构、移动段落、可执行家庭任务、科学不确定性和小赛式“孩子行动—证据—复盘”结构；保留 v1。
2. 本地 editorial review 工件/API/UI：模型审校和人工批准分离，批准绑定 content/render fingerprint；`ready + pending` 不再被呈现为“可发布”。
3. `WechatDraftPreflight`：版本化保守限制、HTML/媒体/字段/安全检查，输出机器可读报告；零微信调用。
4. 正式 `export` CLI：原子目录、manifest、hash、preview、mobile screenshot、review/preflight、ZIP；可重放、拒绝覆盖不一致工件。
5. 确定性独立封面：wide + square 安全裁切；正文图/封面不再同字节；记录 transform version 和 lineage。
6. 颜色 token：`#b9573f` 至少加深到 `#ad4f39`，增加所有小字前景/背景对比度测试。

#### P1 — P0 稳定后

1. 文章正文片段与本地 preview chrome 分离，避免未来平台题头重复。
2. 增加写作质量报告：核心信息、受众、行动建议、段落长度、标题信息量、术语解释、夸大词和具体案例证据覆盖；启发式只做 advisory，事实/隐私/虚构才 hard block。
3. Article Package v2 + visual plan：支持 0–3 个语义正文槽；不修改 v1。
4. 新增可选 `science-explorer` renderer 主题，使用“探索任务/观察记录/安全提示/下一次迭代”等语义模块；视觉归因必须写“基于品牌公开语言的设计推断”，不得声称复刻小赛公众号。

#### P2 — 需要另开任务

1. 真实账号平台约束校准、媒体上传或草稿箱接入。
2. 公众号实际渲染差异的截图回归。
3. 内容表现数据回流、A/B 标题或自动发布。

这些全部超出当前明确的 no-WeChat-call 边界；尤其自动发布不应作为本地 MVP 的“下一小步”。

### 5. Related specs

- `.trellis/spec/backend/agent-pipeline.md:1156-1252`：公众号本地草稿必须无账号凭据、无上传/发布操作，fixture 零网络，模型不拥有 HTML/URL/媒体身份，preview 是唯一 HTML API 响应。
- `.trellis/spec/backend/quality-guidelines.md:382-389`：模型/来源内容均为不可信输入，必须限界、消毒并采用出站策略。
- `.trellis/spec/frontend/quality-guidelines.md:83-91`：不可信内容只按文本呈现，URL/下载元数据需校验，不能 `dangerouslySetInnerHTML`。
- `.trellis/spec/frontend/agent-workbench.md:29-33`：工作台 fixture/截图必须无后端/provider/网络并清楚标注，不可冒充真实运行。

### 6. External references

#### 自动化与人工审稿

- UTS, *Gen AI and Journalism: Toward common principles*（2025；访问 2026-08-22）：https://www.uts.edu.au/contentassets/6834071656d444529921cbb8ef8b4a9a/gen-ai-and-journalism_towards-common-principles_7-aug.pdf
- `WeChat-Official-Account-content-studio`（访问 2026-08-22；开源项目，需视作工程案例而非平台规范）：https://github.com/wengzige/WeChat-Official-Account-content-studio
- `wechat-article-pipeline`（访问 2026-08-22；开源项目，不自动发布）：https://github.com/davinci-seven/wechat-article-pipeline
- `wechat-publisher`（访问 2026-08-22；包含自动草稿路径，仅用作行业能力对照，本任务不得执行）：https://github.com/jiji262/wechat-publisher

#### 科学/家长内容与移动可读性

- CDC Clear Communication Index，单一主旨与行动建议（访问 2026-08-22）：https://www.cdc.gov/ccindex/tool/page-1.html
- CDC/NIOSH clear communication，信息优先、短章节、标题、通俗语言、视觉贴近正文（2017-05-25；访问 2026-08-22）：https://www.cdc.gov/niosh/blogs/2017/clear-communication.html
- NIH，面向公众传播科学研究检查表（访问 2026-08-22）：https://www.nih.gov/about-nih/science-health-public-trust/tools/checklist-communicating-science-health-research-public
- NIH，通俗科学写作、主旨先行与小标题（2016-08-09；访问 2026-08-22）：https://stagetestdomain3.nih.gov/node/36611
- Nielsen Norman Group，移动扫描与信息型标题（2017；访问 2026-08-22）：https://www.nngroup.com/articles/f-shaped-pattern-reading-web-content/
- 135 编辑器，一般公众号排版参数（2020-09-09；访问 2026-08-22）：https://www.135editor.com/essences/5544.html
- 135 编辑器，2026 年长期输出/审校与版式建议（访问 2026-08-22）：https://www.135editor.com/geo/gongzhonghaobianjiqi/6640/
- W3C WCAG 2.2（Recommendation 2024-12-12；访问 2026-08-22）：https://www.w3.org/TR/WCAG22/

#### 小赛 AI / 赛先生科学

- 小赛 AI 星球官方站（页面版权 2025；访问 2026-08-22）：https://www.xiaosaiai.com/
- 赛先生科学官方网站（访问 2026-08-22）：https://sxsstem.com/
- IT之家品牌报道（2026-01-30；含企业宣传信息）：https://www.ithome.com/0/917/793.htm
- 东方网企业频道稿（2026-03-13；页面标记广告/企业宣传）：https://qiye.eastday.com/n35/20260313/e57fdf599267470a8223fa9dc126e20e.html
- 界面新闻转载稿（材料发布时间 2026-04-27；页面免责声明提示商业传播材料）：https://www.jiemian.com/article/14386003.html
- 新浪科技关于赛先生科学 AIGC 课程（2025-02-20；品牌报道）：https://finance.sina.com.cn/tech/roll/2025-02-20/doc-inemcxuv3518327.shtml

#### 非微信域平台约束对照

- WxJava 4.4.0 serialized API docs（访问 2026-08-22）：https://javadoc.io/static/com.github.binarywang/weixin-java-mp/4.4.0/serialized-form.html
- HuanCode `draft/add` 整理（访问 2026-08-22；二手文档，标题上限与其他资料冲突）：https://docs.huancode.com/blog/wechat-draft-add-api

## Caveats / Not Found

1. 按任务安全边界，本次没有直接请求任何 `mp.weixin.qq.com` 或 `api.weixin.qq.com` 地址，也没有登录微信。因此没有验证真实账号权限、接口返回或微信客户端最终渲染。
2. 公开搜索没有找到可高置信归属且可在非微信域完整查看的“小赛 AI 公众号文章正文 + 长截图”样本。不能声称当前 renderer 复刻了小赛公众号，也不能从搜索缩略图推断其精确字体、色值、间距或模块实现。
3. `xiaosaiai.com` 是品牌自述来源；IT之家、东方网、界面和新浪页面均可能承载企业宣传材料。它们可用于识别品牌叙事和公开主张，但“首个、独创、学校采用数量、奖项、销售额”等具体主张进入文章前仍须绑定受治理证据并人工复核。
4. “赛先生”科学文化账号、赛先生科学教育机构、中新赛克小赛AI、赛轮轮胎小赛助手名称接近但主体不同；本研究没有把它们混为一体。
5. 非微信域平台文档对 title 上限出现 32/64 字冲突，且某些页面对 content 限制自身也有矛盾。实现只能使用版本化保守 preflight；任何“已验证平台上限”都需要以后在另一个获授权任务中用官方文档/真实账号重新确认。
6. 开源公众号流水线是工程模式样本，不是安全审计结论。不得复制其中的凭据管理、浏览器自动化或发布路径到当前 MVP。
7. 当前导出目录属于运行产物，不是产品内正式导出合同；上述文件树是建议方案，不代表代码已经实现。
