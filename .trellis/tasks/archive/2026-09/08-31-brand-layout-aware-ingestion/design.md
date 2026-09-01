# Design — 品牌语料 Layout-aware 解析与重建

## Decision

复用现有智谱 `glm-ocr` 文档解析能力，不部署本地 Layout 模型；把 provider 的多页 layout
结果先投影为严格、provider-neutral 的 page/block DTO，再由版本化品牌 parser 生成 canonical
text、page section 与 layout-aware child。版面块只作为可重建的解析提示，不新增数据库列：

```text
private PDF
  -> bounded local page-quality profile
  -> local text (ordinary PDF)
     or one Zhipu /layout_parsing call (slide/layout risk)
  -> typed OCR pages + bounded blocks
  -> parser v4 canonical text + page sections + ephemeral block spans
  -> chunker v4 page/card/table-aware children
  -> existing contextual embedding input v2
  -> Alibaba qwen3-vl-embedding (2048d)
  -> existing brand_sections/chunks/embeddings + RRF v3
```

这条路径把 provider schema、文档结构和持久化结构分开：adapter 不创建数据库实体，parser 不
读取原始 provider dictionary，repository 不解释 bbox/Markdown。

## 1. Version and ownership

建议的新 bundle：

- `brand-parser-v4-layout-aware`
- `brand-chunk-v4-layout-blocks`
- `brand-embedding-input-v2-section-context`（模板没有改变）
- `brand-hybrid-rrf-v3-parent-diverse`（检索策略没有改变）

`SUPPORTED_BRAND_DERIVATION_VERSIONS` 明确列出 v2、v3、v4 三套完整组合。v3 的全文稀疏
OCR -> generic Markdown 行为保持冻结；只有 v4 消费 layout pages。parser/chunker/input 的行为
选择集中在同一 bundle dispatch，不能以字符串 `startswith` 或散落条件实现。

## 2. Local page-quality profile

`BoundedBrandDocumentParser._parse_pdf` 在一次受限 `pypdf` 遍历中产生：

```python
PdfPageQualityProfile(
    page_count: int,
    usable_characters: int,
    blank_pages: int,
    sparse_pages: int,
    landscape_slide_pages: int,
)
```

单页 sparse 继续使用已有 `sparse_text_threshold`；slide-like 使用 mediabox 的有限正数宽高和冻结
宽高比。v4 的纯函数根据以下信号决定 `requires_ocr`：

1. 既有全文平均字符不足；或
2. 至少 80% 页面为横向演示比例，并且至少 25% 页面为空白或低文本。

具体常量在实现前由两份合成正例、普通纵向报告和横向密集表格负例冻结。原始文件名、Producer、
页文本和 WPS 标识不参与规则。日志只记录计数和 parser version。

选择 Layout 后不合并 local page text。这样一个 derivation 内只有一种 canonical source，避免页间
separator、offset 和 hash 因混合路径不可回放。

## 3. Provider boundary

### 3.1 Safe response types

扩展 `BrandDocumentOcrResult`，增加不可变的：

```python
BrandOcrLayoutPage(page_number, width?, height?, blocks)
BrandOcrLayoutBlock(ordinal, kind, text, normalized_bbox?)
```

`kind` 为 `text | table | formula`；image element 在 adapter 内验证后丢弃，不成为业务 DTO。
空页面保留 page identity 与空 blocks，保证外层 page ordinal 与 `data_info.num_pages` 一致。

原始 envelope decoder 与图片 OCR 共享：

- pages -> elements 的形状与数量上限；
- `data_info.num_pages/pages` 和 optional element width/height 交叉检查；
- nonnegative unique index、closed label；
- unit/pixel bbox shape、scale、range validation；
- content-free Pydantic diagnostics 和 raw/source-conflict gate。

能力-specific projection 分开：图片 OCR 拒绝 table/formula、限制 1 页/8 行；品牌 OCR 允许
最多配置页数、每页有界 blocks 和文档总字符上限，并把 table/formula 作为文本块。任何 image
content 都不进入字符串 normalizer。

### 3.2 Ordering

外层数组顺序是 page order，必须与声明页数一致。页内首先保留 provider element sequence，并
校验 index 唯一；只有当所有可见 blocks 都有合法 bbox 时，解析层才用稳定的几何分组辅助判断
“标题与正文是否属于同一卡片”，而不是重排 provider 的完整阅读顺序。bbox 缺失时降级为单独
blocks。

这避免简单 `(y, x)` 排序把多栏卡片读成“所有标题 -> 所有说明”，同时仍能使用空间关系做
保守关联。

## 4. Canonical layout document

新增 ephemeral `ParsedBrandLayoutBlock` 并由 `ParsedBrandSection.layout_blocks` 引用。它保存 block
kind、page-local ordinal、global exact offsets、raw text 和 optional normalized bbox。该对象只存在
于 `parse -> chunk` 的一次执行中，不持久化、不进入 HTTP/MCP。

parser v4 对每页执行：

1. 丢弃空 visible block；规范化 CRLF/控制字符但保留 table 的 Markdown 行列与公式文本。
2. 用 `\n\n` 连接 blocks，页与页同样使用现有 section separator。
3. 在 append 时计算 page 和 block 的 global offsets，构造 exact-slice assertions。
4. 从顶部短 text block 选择 section title；无可靠候选时使用 `第 N 页`，但不把 locator 注入 raw。
5. 空/image-only 页只保留 `page_count`，不创建 section/chunk。

`md_results` 不再作为 v4 canonical body，避免它再次丢失外层页面映射；它只保留在 adapter 内用于
兼容响应验证，并继续供 frozen v3 使用。provider layout 无有效可见 blocks 时返回 typed terminal
failure，不回退一个 generic parent。

## 5. Layout-aware child selection

chunker v4 在一个 page section 内按 `layout_blocks` 形成候选：

- table/formula 各自是优先边界；
- text block 默认独立；
- 一个短、heading-like text block 只有在 bbox 与后继正文有足够水平重叠、位于其上方且垂直
  间距受限时，才把两者的连续 source span 合成 card candidate；
- 两个不连续 source spans 不允许伪装成一个 raw chunk。若中间存在别的 block，就不合并；
- 超过 `chunk_characters` 的 block/card 使用既有 paragraph/Markdown/sentence/line/hard splitter；
- overlap 只在同一个 page parent 内，600 hard cap 和 generic OCR pathological fallback 不放宽。

布局 hint 影响 child boundary，因此由 `brand-chunk-v4-layout-blocks` 标识。section/chunk key 与
hash 继续从最终 exact span、版本和 contextual embedding input 确定性派生。

## 6. Persistence, re-index and rollback

现有表已经拥有所需的 durable facts：section kind/title/source page、chunk raw/contextual text、
offset/hash 和 provider/model/version。bbox 没有当前消费者，因此不迁移。

本地 rollout：

1. `plan` 只报告旧 active 与 v4 derivation drift；
2. mutating 命令必须通过重复的 `--document-id` 显式选择两份 PDF；只接受 active-ready PDF，
   不按标题、文件名或对象路径筛选；
3. `migrate --execute` 只从上述 immutable private originals 创建 v4 jobs，并把 target version ID
   allowlist 传入 repository claim；fresh queued 与 stale recovery 使用同一过滤，普通 worker 不受影响；
4. 外部 OCR/embedding 全部在事务外，现有 lease/heartbeat 继续工作；
5. sections -> flush -> chunks -> flush -> embeddings -> ready；
6. 先做结构与 retrieval 验收，再激活 v4；
7. 任一步失败不改变旧 active version；回滚只需重新激活旧 ready version/恢复 v3 defaults。

两份 PDF 允许各一次文档 OCR 请求；网络层只使用现有 bounded retry 配置，不由任务脚本额外重试。
重建命令输出只保留 document/version IDs、counts、versions 和状态，不打印 title/path/body/query。

## 7. Retrieval and evaluation

`embedding_text` 模板和阿里 provider/model/dimension 不变，因此 repository SQL、RRF、HTTP/MCP/
copy projections 无需修改。新 page/card 边界会产生新 embedding inputs 和新向量，这是新 immutable
derivation 的预期结果。

在脱敏 brand-text eval 增加 layout-sensitive cases，但继续调用生产共享的 RRF/selector。另加一个
本地 aggregate-only smoke：对产品矩阵、安全能力等预定义 query hash 检查 top-5 的 document/
page IDs，不保存 query 或 hit text。fixture 指标仍标注为 policy regression；真实语料 smoke 不
转换为公开准确率。

## 8. Failure matrix

| Condition | Result |
|---|---|
| Ordinary text PDF has adequate pages | Keep bounded local page parser; zero provider calls |
| Slide-like PDF has many blank/sparse pages | One whole-document Layout request |
| Local parse says Layout but OCR is disabled/unavailable | Existing typed OCR-unavailable/retry path; no local/OCR merge |
| Response page count conflicts with outer layout pages | Terminal `brand_ocr_page_count_invalid` |
| Unknown label, mixed bbox scale, invalid index/content | Terminal content-free OCR contract code |
| Page contains only image elements | Count page; no retrievable section |
| Card relation is ambiguous | Keep independent layout blocks |
| Table/formula block exceeds bounds | Terminal invalid output or bounded parent-local split; never truncate silently |
| v4 layout pages missing but Markdown exists | Terminal; do not create one generic parent |
| Chunk count still exceeds 600 | Existing terminal `brand_chunk_limit` |
| OCR/embedding/persistence/eval fails during re-index | Old active stays authoritative |
| Layout metadata consumer requests bbox later | Separate migration/API task; not hidden JSONB |

## 9. Validation strategy

- Unit: PDF quality profile/routing; layout DTO/domain invariants; page/block assembly; spatial card merge;
  exact offsets; tables/formulas; empty pages; frozen v2/v3 and unchanged DOCX.
- Provider contract: multi-page raw MaaS fixtures, unit/pixel bbox, optional dimensions, source conflicts,
  all closed labels, bounds, typed errors, sentinel privacy, and no image-content projection.
- Application: v4 OCR handoff builds page sections; v3 remains generic; lease/provider identity/failure and
  external-call transaction boundaries remain.
- PostgreSQL: v3/v4 immutable coexistence, ready/activation/failure rollback, existing schema/head drift and
  provider/model filtering using real PostgreSQL/pgvector.
- Eval: canonical brand-text check plus new layout-sensitive cases and oracle isolation.
- Local controlled corpus: two PDFs re-indexed/activated with aggregate-only 48/50 page, section/chunk,
  exact-slice and page-hit evidence; DOCX equivalence check without new OCR.

## Operational boundary

Implementation is local only. It may call the already configured Zhipu OCR for the two explicitly scoped
PDF originals and Alibaba embedding while rebuilding their v4 versions. It must not connect to the server,
deploy, push, run news/business jobs, publish content, or expose private corpus/provider payloads. The final
commit must be path-scoped because the shared worktree contains unrelated user changes.
