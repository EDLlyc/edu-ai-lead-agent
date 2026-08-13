# Prioritize science education and product-aligned sources

## Goal

让受控抓取与每日选题链路以科学教育和 AI 教育为真实内容边界，并显著提高与“科学第四主科 · AI 第五主科”产品方向相符内容的排序权重，同时保持事实证据、品牌资料、来源治理和历史回放边界清晰。

## User value

内容运营每天优先看到与科学素养、AI 素养、科创实践和青少年成长相关的可信新闻，而不是被泛 AI 发布、产业融资或泛科技信息淹没；产品团队也能从评分解释中看见内容匹配了哪些业务方向，但不会把产品宣传误当成新闻事实。

## Confirmed background

- 当前系统有 9 个受控信源。8 个一般信源使用详情抓取前的 `ai-title-v1`；教育部信源单独使用标题+有界正文的 `moe-science-v1` 和 `moe-science-top1-v1`。
- 当前 `science-policy-priority-v2` 只对携带教育部来源策略、同时命中科学教育主题和政策行动词的合格事件做绝对提前；它不是跨来源内容相关性机制。
- 选题已有不可变评分配置、硬性否决、`0.62` 阈值、十天新鲜度、七天重复控制、稳定排序、Top 1/`no_topic`、同日 revision 和审计回放。
- 事实治理只消费已保存快照，并将摘要/事实绑定到来源 passage；品牌检索与事实证据分离；下游只生成供人工审核的素材包，不自动发布。
- 用户提供的产品矩阵页面为 `https://resource.xiaosaiai.com/oss/upload/other/html/5694333bc05f40b089bc22898354d74b.html`。用户于 2026-08-13 确认：产品适配只做高权重软加分，不做硬过滤。
- 信源调研与当前网络探测记录在 `research/ai-education-source-candidates.md`；本地架构证据记录在 `research/current-ranking-and-ingestion-seams.md`。

## Requirements

### R1. Science/AI-education editorial boundary

- 建立一个中英双语、确定性、可版本化的科学/AI 教育相关性规则，覆盖科学教育、AI 教育、STEM/STEAM、课程与教学、师生 AI 素养、科学探究、机器人/工程项目、青少年科创竞赛、科学营和研学等语义。
- 显式科学/AI 教育短语可以直接满足主题条件；其他内容必须同时具备科学/AI/技术主题和教育、学习者、教师、课程、课堂或实践语境。
- 泛 AI 模型发布、算力芯片、融资、消费电子、企业产品、一般科学发现和泛教育内容不得仅凭单个关键词进入新候选池。
- 新抓取候选必须满足该规则；历史上已治理的泛 AI 事件在新评分版本中必须得到独立的范围外硬性否决。

### R2. Product-matrix fit is a soft signal

- 建立独立、可版本化的产品适配规则，覆盖以下稳定方向：
  1. 4–12 岁科学素养与探究、科学向物理/化学衔接；
  2. 数学、物理、化学、生物理科衔接；
  3. 7–15 岁 AI 素养和项目式学习；
  4. 具身机器人、AI Agent、RAG/LLM 应用、AI 安全、AI×数学、3D 打印、黑客松与创业实践；
  5. 科创竞赛、创新项目和人才发展路径；
  6. 高校、实验室、科技企业、大科学设施、研学和营地体验。
- 规则返回有上限的分数和稳定方向 ID。重复关键词不能无限叠加。
- 产品适配可以影响抓取探测顺序和选题数值总分，但不能决定科学/AI 教育资格、覆盖任何硬性否决或成为新闻事实证据。
- 未直接匹配当前产品矩阵、但属于合格科学/AI 教育的重要内容仍可进入候选池，并可依靠其他信号达到选题阈值。

### R3. Bounded acquisition and audit

- 所有现有活动信源创建使用新相关性规则的不可变 source version；旧 `ai-title-v1`、`moe-science-v1` 和旧 source version 继续可执行、可回放。
- 在现有扫描窗口内，先按标题科学/AI 教育强度排序，再用产品适配做软排序；保留固定数量的标题中性详情探测以发现正文命中，且不得扩大成无限抓取。
- 详情页必须使用标题+最多 6,000 个规范化正文字符复核资格；新鲜度未知、过期或范围外内容不得进入正常 evidence candidate 池。
- 候选 extraction metadata 和 observation 必须保存两条规则版本、资格/分数、原因码、标题/正文命中、产品方向、字符上限/截断、过滤/延后计数和现有新鲜度信息。
- 保持 HTTPS 默认、逐跳 host/path/DNS/响应限制、来源限速、租约、重试、快照、幂等和提示词注入防护。不得增加反爬绕过。

### R4. Controlled source expansion

- 首批活动注册表在独立激活门通过后由 9 个扩展到 12 个：
  - `xinhua-education`：新华教育，Tier B，`zh-CN`；
  - `cast-science-education`：中国科协科普/科学教育，混合作者来源按 Tier B 保守处理，`zh-CN`；
  - `edsurge-ai-education`：EdSurge AI 教育专业媒体，Tier B，`en`。
- 每个来源必须有精确 entry URL、host/path allowlist、robots/条款状态、语言/时区、限速、connector/parser/relevance 版本、固定列表/详情 fixture 和 sponsor/外链排除策略。
- 独立激活门包括条款/robots 复核、生产安全 fetcher 的入口+一篇详情探测、fixture 解析/漂移测试、相关性审计和语言链路测试。任何失败来源都不进入活动 seed，且不得为了达到数量放松安全规则。
- UNESCO 在“仅引用使用”合规结论明确前不激活；中国教育新闻网、中央电化教育馆、OECD、欧盟数字教育和 ISTE 保留为下一批，当前阻塞原因见研究文档。

### R5. Explainable topic scoring

- 新评分版本使用事件的已存代表标题、中文治理摘要和类别计算科学/AI 教育相关性及产品适配，不能仅凭来源身份推断。
- 新评分配置的正向权重为：科学/AI 教育相关性 `0.30`、产品适配 `0.25`、来源可信度 `0.15`、来源多样性 `0.10`、新鲜度 `0.10`、传播潜力 `0.10`；两条核心编辑信号共占 55%。
- 首个预览版本保留 `0.62` 阈值、现有处罚项、稳定 tie-break、Top 1/`no_topic` 和所有其他硬性否决。以后调权必须创建新的不可变版本。
- 新版本不使用教育部来源绝对提前。教育部合格内容通过 Tier A 可信度、内容相关性和其他数值信号竞争；历史配置继续保持原有教育部优先语义。
- 每个分数解释必须包含两条规则版本、原始/规范化特征、权重/分量、相关性原因码、产品方向、范围外否决、总分、阈值、排名和是否启用来源优先。

### R6. English evidence remains traceable

- 英文来源必须保留原始语言、URL、发布日期、正文和 passage；事实治理继续生成简体中文摘要/事实并绑定原始 passage ID。
- 英文内容的去重、事件组织、选题、中文成稿和引用不得降低事实校验、原文追溯、offset/quote 绑定或人工审核要求。
- 私有品牌文档继续只接受 `zh-CN`；本任务不改变品牌知识语言契约。

### R7. Compatibility and delivery boundaries

- 历史 source/scoring 配置必须按原特征键和规则语义读取，不能把旧 `ai_relevance` 静默解释为新的科学教育分数。
- 使用现有 JSON extraction metadata、评分 feature map、config snapshot 和 explanation；当前设计不新增数据库表或迁移。如果实现发现必须增加 typed column，需要先修订设计并重新进行最终规划评审。
- 保持事实证据/品牌上下文分离、`no_topic` 下游停止、人工素材审核和不自动发布边界。

## Acceptance criteria

- [ ] AC1: 固定中英双语样本中，科学/AI 教育、课堂/课程、青少年科创实践正确通过；泛 AI、泛科技和泛教育反例正确失败，并输出稳定原因码。
- [ ] AC2: 产品方向匹配产生有上限的分数和方向 ID；零产品匹配不影响科学/AI 教育资格，产品分数不能覆盖任何硬性否决。
- [ ] AC3: 同一固定发现列表无论重放多少次，标题相关性、产品软排序、正文探测窗口、候选集合和审计计数完全一致；不存在无关内容补足 item quota。
- [ ] AC4: 三个新增来源各自通过 fixture、host/path、canonical URL、日期/语言、sponsor/外链、解析漂移和安全 fetch 测试；活动 seed 总数为 12，失败来源不会被活动注册。
- [ ] AC5: 固定选题集合中，范围外泛 AI 事件被 veto；合格科学教育事件排在泛内容之前；产品适配提高总分但不形成硬过滤；所有解释字段可从持久化/API 回读。
- [ ] AC6: `scoring-v1-preview.5-science-education-product-fit` 权重和为 1，阈值/处罚/稳定排序/`no_topic`/revision/幂等保持正确；`.4` 历史配置继续按教育部旧优先语义回放。
- [ ] AC7: 一篇英文 EdSurge fixture 能完成抓取、中文事实治理、原始 passage 绑定、事件/选题和中文成稿链路，原始 URL、语言和引用保持可追溯。
- [ ] AC8: 现有硬性否决、十天新鲜度、七天重复、人工审核、事实/品牌分离及安全抓取测试继续通过。
- [ ] AC9: 后端、前端、API contract、Compose、doctor 和 diff 最终质量门通过；每个实际激活的新来源另有一次受控入口+单详情 live smoke 结果。

## Out of scope

- 任意 URL 抓取、通用网页搜索、浏览器自动化、验证码/WAF 绕过、代理或 User-Agent 轮换。
- 激活 UNESCO、JYB、NCET、OECD、欧盟数字教育、ISTE 或其他下一批来源。
- 用 LLM 产生最终相关性、产品适配或选题分数；大规模标注集和生产权重校准留给后续版本。
- 修改私有品牌知识语言限制、把产品页加入事实证据、自动发布社交媒体内容或扩大企业微信投递范围。
- 在未重新评审设计的情况下增加数据库迁移或新的公共 API 形状。

## Technical anchors

- Acquisition version: `acquisition-v4-science-education-fit`.
- Relevance policy: `science-ai-education-v1`.
- Product policy: `product-matrix-fit-v1`.
- Topic scoring version: `scoring-v1-preview.5-science-education-product-fit`.
- Detailed architecture, compatibility, activation, and rollback: `design.md`.
- Ordered execution and validation commands: `implement.md`.
