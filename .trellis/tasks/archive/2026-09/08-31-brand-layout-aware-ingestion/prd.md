# 品牌语料 Layout-aware 解析与重建

## Goal

在现有品牌 RAG 的结构化父子切片之上，为演示型 PDF 增加受控的 Layout-aware 解析：先用
逐页质量信号判断文本层是否足以保留版面语义；对版式高风险的 PDF 复用已经配置的智谱
`glm-ocr` `/layout_parsing`，保留页、文本块、表格/公式块、顺序和安全坐标提示，再生成现有
`BrandSection -> BrandChunk`。完成后在本地对两份受控演示稿建立新的不可变索引版本并验证
检索，不部署服务器，不改变新闻、文案生成、发布和数字 IP 图片链路。

用户价值是让产品卡片、安全能力、价格/功能矩阵和品牌主题能够以正确页面与局部上下文被
检索，避免“有文本但阅读顺序错”和“整份 OCR Markdown 只有一个 generic 父节点”。

## Background and confirmed facts

- 受控语料包含两份 16:9、未 Tagged 的演示型 PDF，分别为 48 页和 50 页。第一份本地文本层
  总量不低，却有 5 个空白页、31 个低于 40 字符的非空页；第二份有 33 个空白页。文档总字符
  阈值不能表达这种逐页质量差异。
- 第一份当前以 `local` 方式形成 43 个 page section，但多栏卡片和表格的标签、说明、行列顺序
  会被文本层打散；第二份已经走 `glm-ocr`，但 33,064 字符的 OCR Markdown 被压成 1 个
  `generic` section 和 38 个 chunk，页码与版面块全部丢失。
- 智谱原始接口已经返回 `layout_details`（pages -> elements）、`data_info` 和 `md_results`；当前
  品牌 OCR adapter 只投影 Markdown。项目中的图片 OCR adapter 已经实现了同一供应商原始
  layout envelope、页信息、bbox 两种坐标尺度和安全错误投影，可抽取共享边界而不能复制一套。
- 现有 v3 已具备 `BrandSection`、`source_page`、父内 chunk、精确 offset、上下文 embedding text、
  600 chunk 硬上限、父级多样化检索与不可变 re-index，因此本任务不需要新增持久化结构。
- 访谈 DOCX 的 XML block-order、问题—回答切分已经正确；数字 IP 图片走独立的阿里
  `qwen3-vl-embedding` 视觉索引。两者不应被 Layout PDF 路径改写。
- 历史决策要求保留 PostgreSQL/pgvector、品牌/事实证据隔离、严格 provider/model 过滤、精确
  `document.text[offset] == chunk.text`、短事务和不可变版本；OCR 品牌文本始终
  `evidence_eligible=false`。

## Requirements

### R1. 逐页质量路由，而非单一全文字符阈值

- PDF 本地解析必须计算有界、确定性的页级质量摘要：总页数、空白页数、低文本页数、可用字符
  数，以及页面方向/宽高比；正文、文件路径和页面原文不得进入日志或任务证据。
- v4 对“多数页面为横向演示比例，且空白/低文本页占比达到冻结阈值”的 PDF 触发一次整文档
  Layout 解析；已有“全文过稀”规则仍然有效。普通文本型 PDF 和非 PDF 不因本任务增加供应商
  调用。
- 路由规则与阈值属于 parser v4 的可回放行为。它们必须集中在一个纯函数中并由合成 fixture
  覆盖，不能依赖文件名、WPS 元数据或私有语料标题。
- 同一 PDF 不拼接 local/OCR 两套正文，也不逐页混用不同坐标系；一旦选择 Layout，整份文档
  使用同一 provider result 生成 canonical text。

### R2. 严格且可复用的智谱 Layout 边界

- 品牌 OCR adapter 必须在既有请求/响应字节、页数、超时、并发和重试上限内，严格投影
  `layout_details` 的二维页结构、`data_info` 页数/可选页面尺寸和每页有界 element；不允许
  untyped provider dictionary 越过 adapter。
- element 只接受供应商闭集 `text`、`table`、`formula`、`image`。文本、表格和公式只投影有界
  可见内容；`image` 内容、URL、裁剪图和布局可视化永不投影、记录或持久化。
- bbox 可接受官方支持的单位坐标或有权威页轴的像素坐标，必须校验有限、正序和页内范围；缺失
  bbox 可以安全降级为 provider block order，但混合/未知尺度、页数冲突、重复/非法 index 和
  未知 label 必须以稳定的内容无关错误码终止。
- 与图片 OCR 共用原始 layout envelope、页尺寸与 bbox 验证 primitives；品牌文档和图片 OCR
  各自拥有不同的内容/页数/表格策略，不能互相放宽安全门。
- `md_results` 只作为 v3 兼容回退；v4 canonical text 只能来自已验证的 layout pages，成功后
  不得再次退化为单个 generic parent。layout 缺失或无有效页面结构时失败关闭，不猜测页面边界。

### R3. 页、版面块和精确来源

- 新增 provider-neutral、不可变的 OCR page/block DTO，以及仅存在于解析/切片阶段的
  `ParsedBrandLayoutBlock`；至少包含 1-based source page、页内 ordinal、闭集 block kind、原文
  和精确 global offsets，并可携带规范化 bbox。
- v4 每个有可检索内容的 OCR 页面生成一个 `BrandSectionKind.PAGE`；image-only/空白页面只计入
  `page_count`。section 和 block 按 provider page 顺序与受控阅读顺序稳定重放。
- canonical page text 以明确 separator 连接版面块；每个 section/block/chunk 都必须是同一个
  `ParsedBrandDocument.text` 的精确切片。不得在 embedding text 中伪造正文，也不得跨页 overlap。
- 表格块保留可读的 Markdown 行列结构；公式块保留有界公式文本；纯图片块不成为文本 chunk。
- page title 优先使用顶部、短且有内容的 text block；否则使用既有中性页定位标题。标题复制到
  metadata 时不从 raw page text 删除。
- v4 chunker 优先使用 layout block 边界；只有 bbox 足以证明水平对齐与垂直邻接时，才把短标题
  块与对应正文块合并为一个卡片候选。信息不足时保留独立块，不做猜测式卡片重建。超长块只在
  同一 page 内使用既有有界 splitter/overlap。

### R4. 不可变版本、兼容和本地重建

- 新增一个完整、闭集的 v4 derivation bundle：parser v4 + chunk v4 +现有 contextual embedding
  input v2；v2/v3 bundle 行为和既有 IDs/hashes 必须由回归测试冻结。混合或未知 bundle 继续在
  创建 job 前失败。
- 本任务不新增或改写 `brand_sections` / `brand_chunks` schema；bbox/block 元数据属于可重建的
  解析提示，不进入数据库。只有未来需要页面区域高亮时才另立 migration 任务。
- 复用现有 development-only re-index 命令，从 immutable originals 创建新版本；使用已配置的
  智谱 OCR 和阿里 `qwen3-vl-embedding`，不得改写旧 vector 的 provider/model/version。
- 本地重建两份演示型 PDF；只有新版本达到 `ready` 且结构/检索验收通过才激活。任何 OCR、
  embedding、持久化或评测失败都保留当前 active version，不留下部分 ready 版本。
- 访谈 DOCX 可随同一致 bundle 重放，但 v4 输出的 section/question/chunk 语义必须与 v3 等价；
  数字 IP visual index、图片向量和视觉 manifest 不参与本轮重建。

### R5. 检索、评测、隐私和运维边界

- 检索仍使用现有阿里 2048 维品牌向量、PostgreSQL FTS + pgvector weighted RRF、父级多样化和
  audience/validity/kind/provider/model 过滤；HTTP/MCP/copy projection 不新增 bbox 或私有字段。
- 在现有品牌文本离线评测中增加脱敏的 layout-sensitive 用例，覆盖卡片标题—正文、安全能力和
  表格/产品矩阵。v4 不得降低当前 canonical Recall@5 与 nDCG@5 门禁，且新增用例必须命中正确
  page parent。
- 自动化测试只能使用脱敏合成 layout response/PDF；本地真实语料验收只保留 page/section/
  block/chunk 数量、最大长度、exact-slice、provider/model/version 和检索命中 ID 等聚合。
- 日志/异常/任务结果不得包含私有正文、文件路径、对象 key、Markdown、layout element content、
  bbox 数组、Base64、向量、query、provider body 或密钥。
- 实现、测试、两份本地索引重建和一个仅包含任务范围变更的本地 Git commit 在范围内；SSH、
  push、服务器部署、新闻重跑、企微/公众号发布均不在范围内。

## Acceptance Criteria

- [ ] 合成的 48/50 页演示稿质量摘要稳定，v4 会触发一次整文档 Layout；文本型 PDF 保持 local，
      v3 对同一输入的路由和解析结果不变。
- [ ] 严格 adapter 接受合法的多页 `layout_details`、单位/像素 bbox、可选页尺寸、text/table/
      formula/image；拒绝页数冲突、越界、混合尺度、重复 index、未知 label、超限内容和 layout
      缺失，且错误/日志不含响应 sentinel。
- [ ] 合成多页 layout 生成 page sections 而不是 generic section；空白/image-only 页无 chunk，
      table 行列可读，短标题只在空间关系成立时与对应正文合并。
- [ ] 所有 page/block/chunk 都满足 exact-slice，ordinal/ID/hash 在重复运行中稳定，chunk 不跨页、
      不超过既有大小和 600 hard cap，超限仍以 `brand_chunk_limit` 失败。
- [ ] DOCX 问答/表格顺序、TXT/Markdown、v2/v3 parser/chunker/input bundle 的冻结回归全部通过；
      数字 IP visual index 和现有 retrieval/API/MCP projection 无行为漂移。
- [ ] 不需要 Alembic revision；模型 metadata 与当前数据库 head 无漂移，真实 PostgreSQL 测试证明
      v3/v4 不可变版本并存、失败不激活、ready 后原子切换和旧版本回滚。
- [ ] 两份受控演示稿在本地以 v4 重建为 ready/active：`page_count` 保留 48/50，OCR 结果不再只有
      一个 generic parent，非空页具有正确 1-based `source_page`，旧 active versions 保留。
- [ ] layout-sensitive 脱敏检索用例命中正确 page；现有 canonical Recall@5、nDCG@5、安全验证和
      brand-as-fact 门禁不回退。真实语料只报告聚合命中，不宣称线上准确率。
- [ ] Focused unit/contract/real-PostgreSQL tests、Ruff、strict mypy、brand retrieval eval、full
      backend gate、`git diff --check` 和凭证/私有内容扫描通过。
- [ ] 仅提交本任务拥有的代码、测试、spec/task 文档；不提交私有原文、供应商响应、生成向量或
      无关 dirty-worktree 改动，不 push、不部署。

## Out of Scope

- LayoutLM、LayoutLMv3、DocLayout-YOLO、PaddleOCR-VL 或其他本地 Layout 模型/推理服务。
- 新的 embedding/reranker 模型、向量维度、向量索引类型或数据库 migration。
- 对 DOCX、数字 IP 图片库、新闻事实语料和网页抓取统一使用 Layout。
- 页面截图向量、区域高亮 UI、bbox API/MCP projection 和人工版面标注后台。
- LLM 自动修复阅读顺序、生成摘要、重写原文、分类事实或替代确定性 fallback。
- 服务器部署、业务重跑、公众号/企微推送、生产数据库/MinIO mutation、Git push。

## Risks and deferred items

- 供应商 layout block 是版面恢复信号，不等同于人工标注。v4 只在坐标关系足够时合并卡片，宁可
  少合并也不错误拼接；复杂信息图仍可能需要后续页面视觉检索。
- 两份演示稿重建会发生两次受控 OCR 请求和若干阿里 embedding 请求，可能受配额或网络影响；
  provider failure 只会留下 failed immutable version，不切换 active corpus。
- bbox 当前不持久化，因此不能直接实现点击检索结果跳转到页面矩形区域；若未来 UI 确有需求，
  再以独立 schema/API 任务实现，避免为了面试展示预先增加无消费者字段。
- 工作区存在大量其他任务的未提交改动。实现必须按 owned paths 复核 diff，并在无法隔离提交时
  停止 commit，不能把无关内容混入本任务。
