# Design — 品牌资料结构化父子切片

## Decision

新增一层持久化 `BrandSection`，而不是把父级信息重复塞进每个 chunk，也不把 parent 当成另一种
可向量化 chunk：

```text
private original
  -> bounded deterministic parser
  -> ParsedBrandDocument canonical text
  -> BrandSection (page / interview QA / heading / generic)
  -> BrandChunk raw_text + deterministic embedding_text
  -> existing 2048-d embedding provider
  -> section-aware FTS/vector RRF
  -> raw child + safe parent metadata
```

这样保留 exact offsets、不可变版本与引用正文，同时让检索获得标题/问题上下文。MVP 不调用
模型完成结构识别或分类，也不改变当前向量模型。

## 1. Domain contracts

新增闭集枚举：

```python
BrandSectionKind = page | interview_qa | heading | generic
BrandContentType = positioning | product_profile | audience_insight |
    safety_capability | digital_ip_values | tone_example |
    external_claim | visual_guidance | other
BrandClaimScope = brand_statement | external_claim | normative_rule
```

`ParsedBrandSection`/`BrandSection` 保存：

- stable section ID/key、version ID、global ordinal；
- section kind、section title；
- raw parent text、char start/end；
- optional 1-based source page、question number、question text。

`BrandChunk` 保留 `text` 作为 raw text，新增 section ID、section child ordinal、content type、
claim scope、verification flag、embedding text/hash。Domain 同时校验：

- parent/child exact slice；
- external claim => verification required；
- embedding text 有界且包含 raw child；
- keys/hashes/ordinals/page/question 组合有效。

`ParsedBrandDocument` 携带 ordered parsed sections。OCR/纯文本兼容路径可生成 generic/heading
section，避免让 OCR adapter 拥有第二套结构协议。

## 2. Deterministic parsing

### PDF

逐页抽取并归一化，而不是先拼整篇：

1. 保留 1-based page number；空白页只计入 page count。
2. 使用第一条有内容、长度受限的行作为候选标题；无可靠标题时使用中性 `第 N 页` locator，
   但不把中性 locator 写入 raw text。
3. 在单页内按空行、列表/编号、句子和行边界建立 child；绝不跨页 overlap。
4. 仅移除确定性的纯页码和受限页眉/页脚 boilerplate；无法安全识别时保留原文。

MVP 不依赖坐标级卡片重建。页面内块是 best-effort text structure，页面仍是权威 parent。

### DOCX

复用 `python-docx` 1.2 的 block-order traversal，按 document XML 顺序读取 Paragraph/Table。
版本化问答识别器接受受限 `Q1.`、`Q1：`、`问题一` 等形式：

- 问题行开始新 `interview_qa` section；
- 后续 block 直到下一问题都属于其回答；
- 文档标题/章节 heading 不并入前一个回答；
- 没有问答模式时按 heading/generic section 回退；
- 表格文本留在原出现位置，不在文档末尾重复追加。

### Generic OCR Markdown budget fallback

OCR adapter 返回的 Markdown 没有可靠页级 offset 时仍使用一个或多个既有 generic parent；
chunker 不能把每个微小空行块机械地视为独立 child。v3 对每个 generic OCR parent 独立执行：

1. 提取 exact non-whitespace block spans，保留原始 canonical offset；
2. 将相邻微小 block 贪心合并到不超过 `chunk_characters` 的连续 span，内部空行 separator
   仍属于 raw child；输出 span 边界处被 trim 的纯空白 separator 可不进入任何 child；
3. 用与实际生成相同的 bounded splitter 预计算 child 数。若加上既有 parent 的 child 后超过
   `max_chunks`，只对当前 generic OCR parent 退化为一个连续 parent range，再按段落/Markdown/
   句子/行/硬边界和同父 overlap 切分；
4. 若连续父内切分仍超过剩余预算，终止为 `brand_chunk_limit`。不提高 hard cap、不截断正文、
   不跨 parent/page 合并。

PDF page、DOCX Q&A/heading 和 frozen v2 不使用这条 fallback。section key 不变；child key/hash/
ordinal 继续从最终 exact span、上下文输入和现有版本确定性派生。

### Classification

一个纯函数按 section title、question 和 child 局部文本匹配冻结规则。`content_type` 与
`claim_scope` 独立判断：例如“安全认证”可以同时是 `safety_capability` 和
`external_claim`。内容类型的优先级为安全/产品/audience/digital-IP values/
positioning/tone/visual/other；数字、比例、政策/认证/获奖/第三方合作信号触发 external
claim 时保持 verification required。规则版本进入 chunk/input version；不使用 LLM 或当前
业务配置隐式改变结果。

## 3. Embedding and search text

新 `brand-embedding-input-v2-section-context` 的 canonical 模板由一个共享函数拥有：

```text
文档：<bounded document title>
章节：<bounded section title>
问题：<optional bounded question>
类型：<content type>
正文：<raw child text>
```

模板字符串用于 embedding 和 FTS，raw child 单独保存与返回。`embedding_input_hash` 而不是
raw `text_hash` 绑定 provider request。历史 v1 rows backfill `embedding_text=text` 和
`embedding_input_hash=text_hash`，不伪造 section。

本任务保持 `BrandChunkEmbedding` 2048 维。未来多模态模型必须新建独立 provider/model/dimension
版本和 re-index 任务，不能把 1024 维 Qwen 向量混入现表。

## 4. Persistence and migration

新 revision 基于实现时真实 Alembic head：

- 创建 `brand_sections`，version FK cascade、stable key unique、version+ordinal unique、offset/
  kind/page/question checks 和 version index；
- 给 `brand_chunks` 增加 nullable `section_id` 及 parent-version composite binding、child ordinal、
  content/claim type、verification flag、embedding text/hash；
- backfill existing rows的 embedding text/hash和安全默认 content/claim values；section 保持 NULL；
- 新 v3 persistence 强制 section 非空并先 sections -> flush -> chunks -> flush -> embeddings；
- search vector改为由 embedding text生成，迁移重建 GIN 表达式；pgvector数据不重算。

若 PostgreSQL 不能以 generated column 安全替换而不长时间锁表，revision 使用显式 drop/recreate
并在本地真实数据库验证。Downgrade 保留 raw chunk/vector，删除结构元数据，明确属于结构信息
丢失；不得删除 brand document/version/original。

## 5. Retrieval and consumers

`BrandRetrievalHit` 新增 section ID/title/kind/page/question number/question text、content type、
claim scope 和 verification required。Raw `text` 语义不变。

RRF 候选过滤仍按 active version、audience、validity、document kind、provider/model。选择器从
“跳过相邻 ordinal”升级为：

1. 保留融合 rank；
2. 第一轮每个 section 最多一个 child，并保持 document cap；
3. 结果不足时允许同 section 的第二个 child；
4. 历史无 section rows 用 `(version_id, ordinal)` 作为独立兼容 key；
5. identical raw text 继续去重。

HTTP mapper、copy-generation context 和 Agent Workbench registry 共用 domain projection。API 只
返回安全 locator，不返回 parent full text、私有路径、object key 或 embedding text。

## 6. Versioning and rollout

默认身份建议：

- `brand-parser-v3-source-structure`
- `brand-chunk-v3-parent-child`
- `brand-embedding-input-v2-section-context`
- `brand-hybrid-rrf-v3-parent-diverse`

上传同一 body 时这些 version values 令 derivation key 产生新 immutable version；旧 active version
不自动切换。任务只实现/验证，不重新处理私有文件。回滚默认值即可让新上传恢复 v2 行为；已经
存在的 v3 rows 仍由兼容查询读取。

## 7. Validation

- Unit: synthetic PDF page boundaries/blank/repeated title/card/long block；DOCX XML block order、
  9-like Q&A、table、fallback；exact offsets/keys/hashes/classification。
- Service: embed request uses canonical embedding text/hash；OCR generic fallback；lease failure。
- PostgreSQL: migration clean upgrade、historical row backfill、新 parent FK/insert order、v2/v3
  coexistence、activation/filter/RRF diversity/deactivation。
- API/Agent/copy: one typed projection and null-safe historical mapping；OpenAPI drift。
- Private local acceptance: process the three controlled originals offline and retain only aggregate
  counts/structural assertions outside committed fixtures。

## 8. Provider-free brand-text retrieval evaluation

新增 `backend/evals/brand_retrieval/`，与现有 visual/digital-IP/Agent eval 目录并列但不共享
报告身份：

```text
cases.v1.jsonl (36 sanitized cases + graded relevance)
  -> strict typed loader + dataset hash
  -> shared production RRF fusion
  -> shared v2/v3 diverse selector
  -> Recall@5 / MRR@5 / nDCG@5 / parent diversity / safety
  -> canonical-report.json + canonical-report.md
```

每个用例包含 query category、固定候选 chunk 的 FTS/vector rank、document/section identity、
content/claim metadata 与独立 relevance grade。候选正文只使用短的脱敏合成文本，不复制私有
资料。runner 只从候选 rank 生成融合顺序，再调用生产 selector；oracle 仅进入评分器，不能参与
排序。这样既防止自证，又能稳定比较冻结 v2 和当前 v3 的 parent-diversity 行为。

生产数据库函数中现有 RRF 公式应抽成一个小的纯函数，由真实 SQL 投影和 eval 同时调用；数据库
仍负责 FTS/vector candidate 生成、过滤与投影，纯函数只拥有 rank fusion。selector 保持同一
实现，不建立 eval-only 排序副本。

报告使用两个明确 track：同一 dataset 下的 `legacy_v2` 与 `structured_v3`，Top K 固定为 5。
门禁要求 v3 的三项 relevance 指标不回退、parent diversity 严格提升、external-claim
verification 覆盖 100\%、evidence violation 为 0。指标保留 6 位小数并按 case ID 稳定排序。
报告 disclaimer 明确这是 fixture policy regression，而非 live embedding/production claim。

本轮不依赖 PostgreSQL、MinIO、私有目录或 provider，因此可进入 `make` 门禁；真实私有语料
评测需要独立 gold labels 与供应商调用授权，延后处理。

## Failure matrix

| Condition | Result |
|---|---|
| PDF page has no usable text | Count page, no retrievable section/chunk |
| Page/card exceeds child maximum | Split only inside that page/section |
| OCR generic parent has pathological tiny blocks | Coalesce exact adjacent spans within that parent, then bounded-split under the existing global cap |
| OCR generic parent cannot fit even after continuous parent-local splitting | Terminal `brand_chunk_limit`; never raise the cap or truncate text |
| DOCX has malformed/missing Q marker | Deterministic heading/generic fallback |
| Classification is ambiguous | `other`; do not invent a confident type |
| External-claim signal is present | verification required; still evidence ineligible |
| Historical chunk has no section | Null-safe retrieval with compatibility diversity key |
| New section/chunk FK or exact offset fails | Terminal typed ingestion failure; no partial ready version |
| Embedding provider/model differs | Existing provider identity mismatch behavior |

## Operational boundary

The implementation phase is local code, migration and deterministic tests only. A later explicit user
authorization permitted exactly one isolated existing-provider OCR HTTP request against the single sparse
controlled PDF, with no retry and no retained raw output; it exposed the local chunk-budget issue above.
The fix turn itself made no provider call. After implementation and independent review, a separately
authorized post-fix validation made exactly one additional HTTP attempt with no retry and retained only
aggregate evidence; it proved the local cap issue resolved. Across both gates there were two HTTP attempts
and zero retries. Private corpus persistence, embedding, index rebuild, activation, business workflow,
SSH, deployment, push and delivery remain out of scope.
