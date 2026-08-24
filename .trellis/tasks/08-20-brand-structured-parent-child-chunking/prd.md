# 品牌资料结构化父子切片

## Goal

把现有品牌资料从“整篇提取后按固定字符数切片”升级为可回放的结构化父子切片：演示型
PDF 以页面为父级、页面内主题块为子级；访谈型 DOCX 以问题—回答为父级、长回答中的语义
段落为子级。检索使用带标题、问题和类型的 embedding 输入，展示与引用仍返回原始正文。

用户价值是让“品牌理念、产品、受众、安全能力、数字 IP 价值、外部声明”等问题准确命中
对应内容，并避免把不同页面、不同问题或不同语义角色拼成一个无上下文的片段。

## Background and confirmed facts

- 两份受控私有 PDF 分别为 48 页和 50 页、16:9 演示稿，均未 Tagged；文本层可提取，
  但存在重复页标题、空白/低文本页和一页多卡片，不能把全文拼接后跨页 overlap。
- 受控私有 DOCX 是 9 个问题的访谈。当前实现先收集全部段落、再收集全部表格，无法保证
  段落与表格穿插时的原始顺序，也没有问题—回答边界。
- 当前 `brand-parser-v2-glm-ocr` 将 PDF 各页文本用空行拼成一段；
  `brand-chunk-v2-structure-aware` 仍以 900 字符上限、120 字符 overlap 为主。
- 当前 `BrandChunk` 和 `brand_chunks` 仅保存全局 ordinal、原文、字符偏移和 hash；没有父级
  section、页码、问题、chunk 语义类型、事实属性或独立 embedding 输入。
- 当前文档级 `BrandDocumentKind` 只有 positioning、tone、approved example、prohibited
  language、safety rule、visual guidance 和 other；一份宣传册内部会同时包含多种语义，
  因此不能继续用文档级枚举表达每个子块。
- 当前品牌向量固定为 2048 维并按 provider/model 隔离，检索为 PostgreSQL FTS + pgvector
  weighted RRF；品牌上下文始终 `evidence_eligible=false`。
- 版本 derivation 已包含 parser、chunk 和 embedding-input version，适合通过版本 bump 生成
  新的不可变派生，而不是改写既有 ready/active 版本。
- 2026-08-21 的一次受控 OCR-only 验证证明供应商/model envelope 可用，但 OCR Markdown 的
  generic fallback 将大量微小空行块各自保留为 child，超过既有 600 chunk 硬上限并以
  `brand_chunk_limit` 失败；这属于本地确定性切片问题，不应通过提高上限或截断正文规避。

## Requirements

### R1. 结构化父级 section

- 新增不可变 `BrandSection` 领域和持久化结构，至少包含 version、全局 ordinal、稳定 key、
  section kind、标题、原文、精确字符偏移，以及可选的 1-based PDF 页码、问题编号和问题文本。
- PDF 默认一页一个 `page` section；空白页不产生可检索内容，页面边界永不被 overlap 跨越。
- DOCX 按真实 XML block 顺序遍历段落与表格，识别 `Q1` / `问题一` 等受控问答标记；一个
  问题及其连续回答构成一个 `interview_qa` section。
- TXT、Markdown、无法恢复结构的 OCR Markdown 和不匹配问答模式的 DOCX 使用确定性的
  heading/generic fallback，不调用 LLM，不丢失可用文本。
- 所有 section 与 child offset 都以同一个 canonical `ParsedBrandDocument.text` 为坐标系；
  exact slice invariants 必须成立。

### R2. 父内子切片与 embedding 输入分离

- 子 chunk 只能在一个 section 内切分；900 字符保留为硬上限而非统一目标，优先卡片、段落、
  列表、句子边界。只有同一父级内的超长内容可以使用受控 overlap。
- v3 的 generic OCR Markdown fallback 必须在同一 parent 内确定性合并连续微小块；先尽量保留
  有意义的块边界，若预计 child 数仍超过剩余全局预算，再退化为父内连续有界切分。不得跨
  section/page 合并，不得提高 600 硬上限或静默丢弃正文。只有正文在既有最大长度、child
  大小和 overlap 下确实无法装入 600 个 child 时才终止为 `brand_chunk_limit`。
- 每个子 chunk 保存 `raw_text`（现有 `text`）和单独的 `embedding_text`；展示、引用和品牌
  snapshot 使用 raw text，FTS 与 embedding 使用 embedding text。
- embedding text 使用有界、确定性的上下文模板：文档标题由调用侧绑定，section 标题、问题、
  content type 和 raw text按固定顺序组成；不得引入生成式摘要或改写原文。
- chunk key、raw hash、embedding-input hash、父级/子级 ordinal 和版本共同保证重放稳定；
  `parsed.text[char_start:char_end] == raw_text` 继续成立。

### R3. Chunk 级语义与声明边界

- 保留文档级 `BrandDocumentKind`；另新增 chunk 级、闭集且版本化的 `BrandContentType`：
  `positioning`、`product_profile`、`audience_insight`、`safety_capability`、
  `digital_ip_values`、`tone_example`、`external_claim`、`visual_guidance`、`other`。
- 新增 `BrandClaimScope`：`brand_statement`、`external_claim`、`normative_rule`；
  `external_claim` 必须 `verification_required=true`。
- 分类仅使用版本化、确定性、保守的标题/问题/局部文本规则；不确定时归入 `other` 或更严格的
  `external_claim`，不得用一次 LLM 判断制造不可回放元数据。
- 政策、市场规模、奖项、认证、比例和第三方合作等品牌材料内容可以参与品牌叙事检索，但
  不能成为事实证据；所有新旧品牌 chunk 仍为 `evidence_eligible=false`。

### R4. 持久化、检索与 API

- 新增 Alembic revision：建立 `brand_sections`，并给 `brand_chunks` 增加 nullable historical
  section binding、section-child ordinal、content/claim 类型、verification flag、embedding text
  与其 hash。核心身份用 FK/check/unique 约束，不用无类型 JSONB 代替。
- 历史 chunk 不回写伪造的 section；只对可安全等价的 embedding text/hash 做原文 backfill。
  新 parser/chunk/input 版本产生的新 chunk 必须拥有 section。
- repository 先持久化 section，再持久化 child，再 flush 后写 embedding；外部 embedding 调用
  继续在数据库事务之外。
- FTS 与向量使用同一 embedding text 语义；检索结果返回 raw text 和安全的 section metadata。
  默认先按不同 parent section 多样化，再在结果不足时放宽到同一 parent 的第二个 child。
- copy generation、Agent Workbench tool 和 HTTP projection 共用扩展后的 typed
  `BrandRetrievalHit`；不得由消费者各自解析 metadata。

### R5. 不可变版本与兼容

- 当前默认升级为独立的 parser v3、chunk v3、embedding-input v2 和 retrieval v3 标识；
  历史 v1/v2 版本、chunk、向量、active 绑定和 API 读取保持可用。
- 不修改当前 2048 维 embedding/provider 合同，不接入 Qwen3-VL API，不混用不同模型或维度。
- 同一原文件在新版本 bundle 下创建新的 immutable version/job；不得就地修改旧 ready 版本。
- 回滚默认版本后旧版本继续可读；迁移 downgrade 的数据损失边界必须在 revision 和测试中明确。

### R6. 安全与私有材料验证

- 私有 PDF/DOCX 正文、问题回答、文件路径、对象 key 和向量不得出现在日志、API 错误、测试
  fixture、任务文档或公开仓库。
- 自动化测试使用脱敏合成 PDF/DOCX/Markdown fixture；可选的本地真实材料检查只记录页数、
  section/chunk 数量、类型覆盖和结构断言，不保存正文摘录。
- 解析继续受既有页数、字符数、chunk 数、DOCX archive、PDF encryption 和 OCR 限制约束。

### R7. 品牌文本 RAG 离线评测

- 新增独立、provider-free、可复现的品牌文本检索评测，不复用多模态图片检索的六例报告，
  也不把 Agent Workbench 的 Tool/引用指标冒充为文本 RAG 召回质量。
- 使用 36 个脱敏合成用例覆盖 9 类 chunk 内容类型，每例保存独立的 graded relevance oracle、
  FTS/vector 候选排序和 parent/document 归属；fixture 不包含私有原文、文件名、对象 key、向量、
  供应商响应或真实内部 ID。
- 评测同一批候选在冻结 retrieval v2 与当前 retrieval v3 下的 Top 5，至少计算 macro
  `Recall@5`、`MRR@5`、`nDCG@5`、Top-5 parent diversity、外部声明 verification 覆盖率和
  brand-as-fact violation count。
- RRF 融合与 parent-aware selection 必须由生产共享的纯函数拥有；评测 runner 不复制一套
  排序逻辑，也不得读取 expected final order 形成自证。
- canonical JSON/Markdown 报告必须固定 dataset/hash、版本身份、逐例失败码和聚合指标；
  `--check` 检测漂移，`--write-canonical` 仅在全部门禁通过后写入。
- 报告必须明确其含义是“脱敏 fixture 下的检索策略回归基线”，不能宣称真实私有语料的
  embedding 召回率、线上生成质量或生产效果。

## Acceptance Criteria

- [ ] 合成多页演示 PDF 产生稳定 page sections；chunk 不跨页，空白页不产生检索片段，重复
      运行得到相同 section/chunk key、ordinal、offset 和 embedding-input hash。
- [ ] 一页多卡片内容优先按页内块切分；超长块只在同一 parent 内切分/overlap，raw slice
      invariant 对全部 child 成立。
- [ ] 超过 600 个微小 Markdown 块的合成 OCR generic parent 被确定性压缩到既有 hard cap
      内；所有 child 不超过最大尺寸、稳定回放且不跨 parent。除切片边界处纯空白 separator
      可省略外，全部源字符均被覆盖；真正无法装入 hard cap 的正文仍终止拒绝。
- [ ] 合成访谈 DOCX 按 XML 原始顺序形成问题—回答 section；穿插表格顺序保持，长回答的
      每个 child embedding input 均包含对应问题，raw text 不重复问题前缀。
- [ ] positioning、product、audience、safety、digital-IP、tone、external claim、visual 和
      unknown fixtures 获得确定性类型；外部声明始终 verification required 且 evidence ineligible。
- [ ] 真实 PostgreSQL migration/integration test 证明 section -> chunk -> embedding FK 顺序、
      新旧版本并存、activation、provider/model filtering、parent-aware RRF diversity 和 deactivation。
- [ ] retrieval HTTP、copy generation 与 Agent Workbench 映射返回同一 typed section metadata；
      OpenAPI 和生成的前端类型无漂移，历史 chunk 的新增字段保持 null-safe。
- [ ] 三份受控真实材料的本地离线结构检查通过，只输出安全聚合：PDF 页级边界与 DOCX 9 个
      Q&A 被识别，不持久化或提交私有正文。
- [ ] 36 个脱敏品牌文本检索用例全部可加载且类别均衡；同一候选输入下 v3 的 Recall@5、
      MRR@5、nDCG@5 不低于 v2，parent diversity 高于 v2，外部声明 verification 覆盖率为
      100\%，brand-as-fact violation 为 0。
- [ ] 评测 oracle-isolation 回归证明删除/篡改 graded relevance 会使对应指标或门禁失败，
      runner 不能从 expected order 直接构造结果；canonical JSON/Markdown `--check` 字节稳定。
- [ ] Ruff、strict mypy、focused unit/contract/real-PostgreSQL tests、migration tests、API drift、
      full backend gate、`git diff --check` 与定向隐私扫描通过。

## Out of Scope

- Qwen3-VL-Embedding、其他多模态 embedding/reranker API、本地模型部署和向量维度迁移。
- 把 PDF 页面渲染图、产品图片或数字 IP 图片写入 pgvector；这属于后续多模态检索任务。
- 用 LLM 自动摘要、自动改写、自动分类或自动核验品牌材料声明。
- 自动相信或发布材料中的政策、市场、认证、奖项和合作信息。
- 新建面向公众的品牌搜索产品、大规模前端重构或人工标注后台。
- 本轮不调用真实 embedding/LLM，不对私有语料做批量在线查询，也不把 fixture 指标描述成
  真实语义召回或线上效果；真实语料盲标与 live-provider benchmark 另行授权。
- 生产重建索引、重新上传/激活三份私有材料、SSH、部署、供应商调用或企业微信推送。
- 本轮病理小块修复不调用 OCR/provider；修复通过独立检查后，另行使用已授权的一次调用完成
  aggregate-only 验证。

## Risks and deferred items

- PPT 文本层不包含完整视觉布局，v3 只能确定性恢复页面和文本块，不能保证识别所有视觉卡片；
  页面图像融合向量和 layout-aware OCR 延后到多模态任务。
- 保守自动类型会产生 `other`，这是可接受降级；错误地把外部声明标成普通品牌事实比少分类更
  危险，因此安全规则宁可提高 verification required。
- 新 schema 与当前尚未提交的其他工作共享 `models.py`、OpenAPI 和 migration head；实现时必须
  保留现有改动并基于最终 head 创建单一新 revision。
- fixture 排名可以证明 RRF、父级多样化和安全边界可回放，但不能单独证明 embedding 模型在
  私有真实语料上的语义质量；报告和简历表述必须保留这一边界。
