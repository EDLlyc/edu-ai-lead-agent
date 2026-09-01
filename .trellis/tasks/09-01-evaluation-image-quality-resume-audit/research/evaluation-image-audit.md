# 评测体系与图片评测审计

## 结论先行

项目当前最强的部分不是“某个模型分数很高”，而是已经具备一套可复现、可审计、对能力边界表述较诚实的离线门禁：数据集有哈希，报告可做 canonical drift 检查，检索、Agent、图片格式/OCR/相似度和移动端交付都有契约验证。

最大的缺口是：现有图片门禁主要回答“文件能不能用、文字是否精确、是否近重复、产物能不能交付”，还不能稳定回答“图片是否忠实表达文章、品牌角色是否画对、最终裁切后是否仍然可读和好看”。因此最值得作为简历主线的下一步，不是再接一个通用 CLIPScore，而是建设 **Human-Calibrated Multimodal Eval Harness（经人工标定的多模态图片评测平台）**。

这条主线能把项目从“有图片生成和若干检查”提升为：

1. 用原子化断言评测语义、角色身份、中文文字、视觉瑕疵、版式和多样性；
2. 用人工双标/三标校准自动评测器，量化一致性与关键缺陷召回率；
3. 同时保留 deterministic offline CI 与 opt-in live judge 两条轨道；
4. 在最终发布字节（裁切、压缩后）上做门禁，并记录模型、提示词、评测器、rubric 和数据集版本；
5. 用真实 A/B、置信区间、误放率和人工拒绝率形成可核验的简历结果。

## 研究范围与方法

- 审阅 `backend/evals/` 下现有评测套件、canonical 报告和 README 的能力边界。
- 沿图片生成、检索、选择、校验、裁切、存储、编辑器交接和移动端检查追踪数据流。
- 检查作品集图片、最近一次公众号交付产物和移动端截图。
- 复跑五套 canonical check，记录当前工作树下的实际结果。
- 对照 TIFA、GenEval、DreamBooth、LPIPS、ImageReward、PickScore、MLLM-Bench、VIEScore 等公开研究，选择适合本项目的指标角色，而不是把任何单一指标当作总分。

## 当前能力地图

| 能力 | 当前证据 | 能说明什么 | 不能说明什么 |
| --- | --- | --- | --- |
| 视觉检索契约 | `backend/evals/visual_retrieval/runner.py::_evaluate_case`；6 个 provider-free case | 文本/图片/同义词/失败 fallback 的排序契约稳定 | 没有真实图片字节，没有真实 embedding，没有用户相关性标签 |
| IP 素材检索策略 | `backend/evals/ip_asset_retrieval/runner.py`；40 个脱敏排序观察 | 固定 rank observation 下 V3 策略 Recall@5=0.92、nDCG@5=0.970204 | 不是端到端视觉检索质量；候选 rank/score 已预填 |
| 品牌 RAG 排序 | `backend/evals/brand_retrieval/runner.py`；36 个独立标注候选观察 | V3 Recall@5=0.95、nDCG@5=0.928633，父资产多样性 1.00 | 不覆盖 live embedding、真实语料库和生成效果 |
| Agent 契约 | `backend/evals/agent_workbench/runner.py`；42 个 synthetic fixture | 工具 allowlist、预算、引用、拒答和 trace 可复现 | fixed policy 的 100% 不是 live LLM 智能水平 |
| 话题 rerank | `backend/evals/topic_rerank/runner.py`；10 个 synthetic fixture | 优先级、硬排除、回退、稳定 tie 等安全契约 | 不衡量真实编辑质量；当前工作树存在一个失败用例 |
| 图片文件硬门禁 | `backend/app/domain/image_validation.py::validate_image_output` | bytes、MIME、签名、解码、尺寸、像素上限 | 不衡量语义、角色身份、构图、审美和瑕疵 |
| 图片精确文字 | `backend/app/domain/image_validation.py::validate_exact_visual_text` | 缺字、多字、重复、顺序；OCR provider 可选 | OCR 关闭时无此能力；未量化小屏可读性、CER/WER 和置信度 |
| 模型图片审校 | `backend/app/infrastructure/ai/image_validation.py::_audit_prompt` | 可选 VLM 对视觉 brief 与最多 8 张参考图给 accepted/issues | 只有布尔结果和 issue；没有分维度分数、置信度、rubric 版本或人工一致性 |
| 相似度/多样性 | `backend/app/domain/image_similarity.py`、`visual_diversity.py` | 近重复和计划维度门禁 | 不是场景语义多样性；未区分“角色应一致”和“场景应多样” |
| 最终发布处理 | `backend/app/application/services/official_account_visual_generation.py::_create_generated_body_publication` | 统一 JPEG、尺寸、无 EXIF/ICC，裁切后文件可用 | 裁切后未再次做语义、身份、文字和构图审校 |
| 移动端交付 | `frontend/e2e/official-account-editor-handoff.spec.ts` | 320/430 宽度、图片加载、顺序、正文一致、无横向溢出和外部请求 | 没有截图 diff、最小文字尺寸、对比度、主体安全区、视觉节奏指标 |

### 当前基线复跑（2026-09-01）

| Check | 结果 | 正确解读 |
| --- | ---: | --- |
| `visual_retrieval` | 6/6 | provider-free 排序与 fallback 契约通过 |
| `ip_asset_retrieval` | 40 cases；Recall@5 0.92；nDCG@5 0.970204 | 脱敏 rank-policy 基线，不是 live 图片相关性 |
| `brand_retrieval` | 36/36；Recall@5 0.95；nDCG@5 0.928633 | 脱敏品牌排序策略基线 |
| `agent_workbench` | 42/42 | fixed-policy 工具与安全契约通过 |
| `topic_rerank` | `priority-barrier` 失败 | 实际 final order 为 `[2,1]`，fixture 期望 `[1,2]`；当前相关文件已有未提交修改，本研究不覆盖或修复它 |

这次失败本身说明 canonical check 能发现漂移；同时也暴露出报告层应输出“哪个断言、实际值、期望值、关联策略版本和可能变更来源”，而不是只打印 failed case id。

## 图片链路的关键发现

### 1. 原始生成结果与最终发布结果之间存在评测断点

`material_package.py` 的另一条图片链路支持确定性校验、可选 OCR 和可选 VLM audit，但公众号正文图通过 `official_account_local.py::_generate_body_visuals` 生成后，主要执行格式准备、存储和状态持久化。`official_account_visual_generation.py::prepare_generated_visual_result` / `_create_generated_body_publication` 会把图片转成 1536×1024 JPEG 并可能中心裁切，之后没有对最终发布字节重新做语义、角色身份、文字或构图审校。

`official_account_editor_handoff_v2.py::_durable_body_visual_lineages` 会把 ready 图片记录成 `durable_image_audit_accepted`，但 `StoredOfficialAccountGeneratedVisual` 本身只持久化状态、媒体类型、尺寸、哈希和错误，没有 per-image audit、维度分数或 judge metadata。这个名字容易让读者误以为每一张最终图片都已经过多模态质量验收。

建议新增 `VisualEvalRecord`，绑定最终 publication SHA-256；只有对应版本的硬门禁全部通过，才允许把该状态称为 `image_quality_audit_accepted`。早期应做 versioned opt-in，不应直接改变现有发布行为。

### 2. 当前“语义相似”不等于“主题表达准确”

作品集中的 `docs/portfolio/assets/content-showcase/brain-computer-interface-ai.png` 视觉完成度较高，但画面标题和主体更像泛化的“人工智能/机器人反馈”，对“脑机接口”这一主题的独特实体与关系表达不足。通用图文 embedding 很可能因为出现 AI 语义而给出不低分；原子断言“是否出现脑信号/神经接口/信号到设备的关系”更容易发现问题。

这说明图片语义评测应从单一全局相似度改为场景 brief 的原子断言覆盖率，并对标题中的核心实体设置 critical assertion。

### 3. 最新交付可在 semantic unavailable 时通过工程 preflight

最近交付目录 `output/official-account-weekly-live-distinct-news-final-reviewed-20260831/` 中，`03-application_case/article.json` 的素材选择状态为 `semantic_unavailable`，使用 deterministic tag fallback；`body-visuals.json` 的 `similarity_band` 为空；`preflight.json` 仍可通过。这不是错误——系统有意允许可靠降级——但它证明当前“可交付”不能等价为“图片语义质量已量化”。

作品集文档目前使用“图片校验通过”加 checksum 的说法。对招聘者应进一步说明校验范围，例如“格式/尺寸/OCR/相似度/移动端完整性门禁”，避免被理解为已经完成审美和语义的人类水平评测。

### 4. 移动端检查偏结构，缺少感知质量

现有 Playwright 用例在 320/430 宽度验证无横向溢出、图片加载、正文一致和零外部请求，是很扎实的交付契约。实物截图可读且没有明显溢出，但部分图注较小、视觉卡片存在重复感；当前 JSON 报告只记录状态、哈希和 viewport，无法量化这些问题。

下一步应把最终 HTML 的截图回归、文字最小像素高度、WCAG 对比度、主体安全区和图片节奏纳入单独的 publication-layout 维度。

## 建议的图片评测分层

### L0：确定性文件与合规硬门禁

保留现有 bytes/MIME/decode/dimensions/EXIF/ICC/外链/哈希检查，并补充：

- 最终发布字节重新校验，而不是只校验生成原图；
- 二维码、水印、未授权 logo 和禁止文字检测；
- 每一项输出稳定 code、severity、evidence region 和 evaluator version。

这些项适合 CI hard fail，不需要模型总分。

### L1：原子化语义忠实度

把每张图片的 `visual_brief` 拆成可验证断言：

- 必须出现的角色、物体、动作、场景和关系；
- 数量、颜色、位置等组合约束；
- 核心主题实体和不可出现元素；
- 是否允许图片内文字。

主指标：

- `atomic_assertion_recall = 通过的必需断言 / 必需断言总数`
- `critical_violation_rate = 含关键错误的图片数 / 图片总数`
- 按 object / count / relation / action / text / entity 分桶的 precision、recall

TIFA 证明了 VQA 问题可提供细粒度解释；GenEval 证明对象、计数、颜色和空间关系需要单独评估。但自动 VQA judge 存在 yes-bias 和视觉捷径，因此必须配合 hard negatives 与人工校准。

### L2：品牌/IP 角色身份一致性

- 从批准的角色参考库建立正样本与 hard negative：错误猫头鹰、交换主色、缺少/修改胸前 AI 标识、多角色混淆、脸部特征漂移。
- 先用检测/分割得到角色 crop，再用 DINOv2 或 CLIP-I 相似度，避免背景把分数抬高。
- 将“身份一致性”和“场景多样性”拆成两个正交目标：角色应稳定，姿态/场景/构图应变化。
- 阈值由人工标签上的 false-pass budget 决定，不直接照搬公开数据集阈值。

DreamBooth 的研究支持用 DINO 和 CLIP-I 分别观察主体/提示词忠实度，但这些分数与人类判断的相关性仍有限，不能单独做发布门禁。

### L3：审美、瑕疵与偏好

维度建议：构图层级、色彩协调、风格一致、主体清晰、肢体/物体结构、遮挡、伪影、教育场景可信度。使用每样本 criteria 的 VLM judge 输出结构化 evidence，再用 ImageReward/PickScore 进行候选图的相对排序。

偏好模型只适合 A/B 排序或人工复核分流，不适合作为绝对 hard gate：公开偏好数据与本项目的少儿科普品牌域存在分布差异。

### L4：中文文字与小屏可读性

- OCR exact match、CER、WER、line recall、重复/多余文字率；
- 320/375/430 三档截图中的最小汉字像素高度、对比度和截断；
- 标题安全区、图注字号、正文图片内文字与 HTML 文字的职责边界。

关键文字 exact match 应 hard fail；装饰文字/小字 OCR 可作为 warning + 人工抽检。

### L5：构图、裁切和发布版式

- 在 1536×1024 正文图、2.35:1 封面和 320/375/430 viewport 上分别测量；
- 主体/品牌 logo/关键文字 bounding box 必须处于对应 safe area；
- 用 saliency 或检测框衡量裁切前后主体保留率；
- 对 HTML 生成稳定截图，并对批准 golden 做感知 diff；
- 统计图文间距、连续视觉卡片重复、首屏内容密度和图片节奏。

LPIPS 适合做裁切/压缩派生图的感知差异和近重复分析，不代表语义正确性。

### L6：批次多样性

现有 SHA/pHash 继续负责 exact/near duplicate。新增：

- 批次内 LPIPS/DINO pairwise distance 的分布；
- 场景、视角、动作、色调、构图五个离散轴的 coverage；
- 相邻图片的视觉重复率；
- “identity consistency × scene diversity” 二维报告，不把二者压成一个总分。

### L7：人工校准与评测器元评测

建议首版 100–200 张脱敏图片，2–3 名标注者，20% 重叠样本：

- 每维 1–5 分，同时保留关键缺陷多标签和 A/B 偏好；
- 计算 Cohen's kappa / Krippendorff's alpha；低一致性维度先修 rubric；
- 评测自动 judge 与人类的 Spearman/Kendall、关键缺陷 precision/recall、false-pass rate；
- 对分歧样本裁决并进入 hard set；
- provider/model/prompt/judge/rubric 任何一项变化都触发重新标定。

MLLM-Bench 的 per-sample criteria + pairwise judge 方案比通用“这张图好不好”更适合本项目；VIEScore 和后续 judge-bias 研究则提醒，即便整体相关性不错，评测器仍可能忽略图像、偏爱特定视觉模式或在编辑任务上失效。

### L8：运行与漂移

每条 observation 应记录：

`dataset_version`、`case_id`、`publication_sha256`、生成 provider/model/prompt fingerprint、judge provider/model/prompt fingerprint、rubric version、分维度结果、evidence、latency、cost、attempt、timestamp。

离线 CI 和 live eval 分开：

- **offline deterministic**：固定观察、固定数据集、每次 PR 运行，检查 schema、聚合、门禁和 canonical drift；
- **live judge**：显式 opt-in，按周或候选发布运行，固定模型版本，多次采样，报告均值、方差、置信区间、成本和失败率；
- live 输出不直接覆盖 canonical；经人工确认后再 promote baseline。

## 数据集设计

建议建立 `backend/evals/image_quality/`：

```text
image_quality/
├── README.md
├── dataset.v1.jsonl
├── assets/                 # 脱敏、可再分发或只存 hash/fixture observation
├── observations/           # OCR / detector / embedding / judge 的冻结观察
├── runner.py
├── rubric.v1.json
├── canonical-report.json
└── canonical-report.md
```

### 样本构成

| 分组 | 建议占比 | 目的 |
| --- | ---: | --- |
| 正常发布图 | 30% | 测量真实通过分布 |
| 真实失败/人工退回 | 20% | 校准误放率和缺陷召回 |
| 单因素 hard negative | 30% | 错角色、错颜色、缺实体、多文字、错数量、裁切伤害 |
| 边界样本 | 10% | 小文字、相似角色、压缩、低对比度 |
| 跨版本 holdout | 10% | 防止对当前 prompt/judge 过拟合 |

首批可用作品集图和最近公众号正文图作为 seed，但必须补充失败样本；只有成功图会让指标虚高且无法标定 threshold。

### 不建议压成一个总分

发布策略应使用分层门禁：

1. 格式、关键文字、禁用元素、关键角色身份、critical assertion 是 hard gate；
2. 审美和非关键构图用于候选排序或人工复核；
3. batch diversity 在整篇/整周层面检查；
4. 报告可提供 dashboard index，但不能让高审美分抵消错误角色或错误文字。

## 优先级与预期证据

| 优先级 | 工作 | 成本 | 产生的证据 | 简历价值 |
| --- | --- | ---: | --- | --- |
| P0 | 定义 rubric/schema；澄清“图片校验通过”的口径；用现有图片建立 30–50 个 seed case | 1–2 天 | 数据版本、缺陷 taxonomy、首个 baseline | 中 |
| P1 | 建 provider-free `image_quality` harness、冻结 observation、分维报告、hard negative、canonical drift | 3–5 天 | 可在 CI 复现的图片评测报告 | 高 |
| P1 | 对最终 publication bytes 增加 `VisualEvalRecord`，把状态与 hash/judge/rubric 绑定 | 3–5 天 | 端到端可追溯质量门禁 | 很高 |
| P2 | OCR + DINOv2/CLIP-I + criteria-based VLM judge 的 opt-in live track；100–200 图人工标定 | 1–2 周 | judge-human 一致性、关键缺陷召回、误放率、成本/延迟 | 很高 |
| P2 | 320/375/430 screenshot regression、安全区/可读性/对比度 | 3–5 天 | 版式回归和小屏质量报告 | 高 |
| P3 | 模型/提示词 A/B、周批次多样性、漂移 dashboard | 1–2 周 | 置信区间、版本对比、人工拒绝率趋势 | 很高 |

最优实施顺序是先做数据和 rubric，再接自动 judge。否则评测器没有 gold set，得到的高分无法证明可信。

### 与 8 月 18 日求职审计的关系

已有 `.trellis/tasks/08-18-agent-internship-project-improvement-audit/` 给出的总排序仍然成立：如果公开作品集、一键 fixture demo 和真实 Agent eval 尚未完成，它们对投递转化的优先级高于新增图片平台。本报告不是替代那份总审计，而是把其中“数字 IP 真实评测”和“live eval”细化成一条可单独展示的多模态评测项目。

因此建议按目标选择：

- **马上投 Agent 应用/平台岗**：先完成公开可复现 Demo 和 Agent live eval，再做图片 P0/P1。
- **强化 Agent Evaluation / 多模态应用方向**：图片 P0–P2 是最有辨识度的第二主线，优先级可提升到 P0。
- **只想快速多写一个模型名**：不建议实施；没有 gold set 与人工一致性时，接入 CLIP/VLM 不会增加可信证据。

旧审计记录的 topic rerank 为 8/8；当前工作树已扩展为 10 个 case 且 `priority-barrier` 失败。简历和作品集应以最终修复并固化后的 canonical report 为准，不能继续引用旧口径。

## 通用评测体系还应提升的部分

1. **失败诊断**：canonical check 输出 expected/actual、失败断言、策略/数据/代码版本，而不只是 case id。
2. **统计可信度**：真实质量型指标报告 bootstrap confidence interval、paired test 和 effect size；契约型用例继续用 pass/fail。
3. **分层声明**：明确 `contract conformance`、`frozen observation policy`、`live model quality`、`human outcome` 四类证据，禁止横向混用。
4. **数据覆盖**：为每个评测集报告来源、时间、类别、hard-negative 比例、泄漏风险和 holdout 策略。
5. **人工结果**：加入审核通过率、首轮通过率、每篇人工修改时长、发布后点击/完读等业务 proxy；不要用离线分数替代业务结果。
6. **成本与稳定性**：live track 记录 p50/p95 latency、失败率、重试率、token/图片成本与 provider drift。
7. **基线升级流程**：baseline 变好不自动更新；必须输出 diff、人工抽检并显式 promote。

## 容易误导的指标与使用边界

- FID/KID：适合大样本分布比较，不适合判断单张图是否符合文章或品牌角色。
- 单一 CLIPScore：可能奖励泛化主题词，不能可靠检查计数、关系、文字和具体角色身份。
- 通用 VLM `accepted=true`：没有 rubric、evidence 和人工校准时只是另一个模型意见。
- ImageReward/PickScore：更适合候选偏好排序，不能证明品牌身份或事实正确。
- DINO/CLIP-I：可作为主体身份 proxy，但可能过度依赖形状/颜色，需要 crop、hard negative 和人工阈值。
- LPIPS/pHash：衡量感知差异或重复，不是内容质量。
- 6/6、42/42：说明 fixture 契约通过，不应写成“模型准确率 100%”。
- 把所有维度平均成一个总分：会让高审美分掩盖错误文字、错误角色和禁用元素。

## 简历表达

### 现在可以诚实写

> 建立 6 类 provider-free 离线评测与 canonical drift 门禁，覆盖 Agent 工具选择/引用/拒答、话题重排、品牌 RAG 与多模态检索；在 36 例脱敏品牌排序集上达到 Recall@5 95%、nDCG@5 92.86%，并明确区分契约回归、冻结观察与 live-model 质量边界。

> 设计公众号图片可靠性交付链路，覆盖格式/尺寸、可选 OCR 与 VLM 审校、近重复、资产 lineage、SHA-256 和 320/430 移动端完整性检查；支持语义不可用时的确定性降级与可审计交付。

第二条必须保留“可选 OCR 与 VLM 审校”，不能暗示当前每张最终发布图均已完成多模态自动验收。

### 完成 P1/P2 后再写（数字必须由报告回填）

> 构建 `N` 张、`K` 类缺陷的品牌图片评测集，覆盖语义原子断言、IP 身份、中文 OCR、审美瑕疵与移动端版式；通过 2–3 人重叠标注将 Krippendorff's α 提升至 `X`，自动评测器对关键缺陷召回率 `Y%`、误放率 `Z%`。

> 搭建 deterministic offline + opt-in live judge 双轨评测平台，对生成模型/提示词做 paired A/B 与 bootstrap 置信区间；将图片首轮人工通过率从 `A%` 提升至 `B%`，每篇审核时长降低 `C%`，并用版本化门禁阻止质量回退。

> 将图片评测绑定最终 publication SHA-256，在裁切/压缩后重新校验角色身份、关键文字和主体安全区；覆盖 320/375/430 三档视口，关键版式回归漏检率降至 `X%`。

没有真实结果前必须保留占位符，不能把目标值写成项目成绩。

## 推荐的作品集叙事

用一张“生成图 → 最终裁切 → 分层 evaluator → 人工校准 → 发布 gate → 版本/成本/漂移”的架构图，再展示一个真实失败案例：泛 AI 图片虽然全局相似，但缺少脑机接口核心实体；原子断言评测发现并阻止误放。比单纯展示“接入某视觉模型”更能体现：

- 评测科学性：construct validity、human calibration、置信区间；
- 多模态技术深度：OCR、VLM、embedding、perceptual metric、browser rendering；
- 工程能力：typed schema、canonical artifacts、CI、versioning、lineage、rollback；
- 业务闭环：人工误放率、审核时长、首轮通过率。

## 公开研究依据

- [TIFA: Accurate and Interpretable Text-to-Image Faithfulness Evaluation with Question Answering](https://arxiv.org/abs/2303.11897)
- [GenEval: An Object-Focused Framework for Evaluating Text-to-Image Alignment](https://arxiv.org/abs/2310.11513)
- [ImageReward: Learning and Evaluating Human Preferences for Text-to-Image Generation](https://papers.neurips.cc/paper_files/paper/2023/hash/33646ef0ed554145eab65f6250fab0c9-Abstract-Conference.html)
- [Pick-a-Pic / PickScore](https://proceedings.neurips.cc/paper_files/paper/2023/hash/73aacd8b3b05b4b503d58310b523553c-Abstract-Conference.html)
- [DreamBooth](https://openaccess.thecvf.com/content/CVPR2023/papers/Ruiz_DreamBooth_Fine_Tuning_Text-to-Image_Diffusion_Models_for_Subject-Driven_Generation_CVPR_2023_paper.pdf)
- [LPIPS: The Unreasonable Effectiveness of Deep Features as a Perceptual Metric](https://openaccess.thecvf.com/content_cvpr_2018/papers/Zhang_The_Unreasonable_Effectiveness_CVPR_2018_paper.pdf)
- [MLLM-Bench: Evaluating Multimodal LLMs with Per-sample Criteria](https://aclanthology.org/2025.naacl-long.256/)
- [VIEScore: Towards Explainable Metrics for Conditional Image Synthesis Evaluation](https://aclanthology.org/2024.acl-long.663/)
- [What Makes a Good Metric? Analyzing Evaluations for Text-to-Image Alignment](https://arxiv.org/abs/2412.13989)
- [Fooling Multimodal LLM Evaluators via Visual Preference Biases](https://aclanthology.org/2025.emnlp-main.1182/)
