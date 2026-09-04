# 生产新闻未推送只读诊断结果

## 结论

- **这是一个真实的日常企业微信新闻链路事故，不是发送时间尚未到，也不是企业微信发送器故障。**
- 最早的持久化断点是 `copy generation`。生产内容 Worker 的
  `BRAND_EMBEDDING_PROVIDER_MODE=auto` 在当前配置组合下解析为 `disabled`，因此 Worker 没有构造
  品牌检索器，也没有构造文案 generator/auditor。所有已选中的新闻在任何文案 Provider 调用之前
  以 `copy_provider_unavailable` 进入 `review_required`。
- 从 `2026-09-02 17:06 Asia/Shanghai` 起到本次诊断结束，共有 **18 个**已选中的文案运行受到影响，
  全部没有 active draft。`2026-09-04` 的 morning、noon 各有 3 个选题，均在这一断点终止；当天
  copy provider attempt、图片、素材包、发送窗口、企业微信 job 和企业微信 attempt 均为 **0**。
- 企业微信 Dispatcher 正常运行、restart 为 0，并且自动发送门禁已启用。它没有发送，是因为上游没有
  生成 eligible package，而不是它领取任务后发送失败。
- 微信公众号是另一条链路。它只创建未发布草稿；调度器当前持续报告 `due=false`，首个合法时间仍是
  **2026-09-07 09:00 Asia/Shanghai**。9 月 4 日公众号周任务和草稿表为 0 是预期行为。
- 根因置信度：**高**。证据同时来自运行时解析后的安全配置、部署提交代码、数据库终态和
  最近 48 小时的投影日志。

本次只完成诊断，没有修复、重启、补跑、模型调用、Provider smoke、消息重发、部署或推送。

## 观察窗口与生产身份

- 只读观察：`2026-09-04 13:40:36` 至 `13:47:01 Asia/Shanghai`。
- 主机时区：`Asia/Shanghai`；时钟与 UTC/+08 换算一致。
- 当前应用 OCI revision 与完整 release marker：
  `40e4dec0ae82569fc798355d4515ab0009697c6f`。
- 应用 image ID：
  `sha256:cda49d5666c4e42e9d3c9ad0aac18c743f9a5ebcc800f0395b7e3c4169352bf0`。
- Alembic：`20260901_0042`。
- 根文件系统使用率：35%。
- PostgreSQL、MinIO、API、采集、治理、内容、周调度、周 DAG、公众号草稿和企业微信服务均为
  `running`；具有 healthcheck 的 PostgreSQL、MinIO 和 API 均为 `healthy`。全部相关服务 restart
  count 为 0。

### 次要发布证据漂移

旧的短 marker `RELEASE_COMMIT` 仍是 `7a45a65`，但完整 marker、应用镜像 OCI revision 和全部应用
容器一致指向 `40e4dec...`。文件元数据进一步确认：完整 marker 在 9 月 2 日 14:16 的激活阶段由 root
更新，而短 marker 的内容、11:57 的 8 月 27 日修改时间及旧 owner 都原样保留。精确问题是这次特性激活
只更新了 canonical full marker，没有原子更新 legacy short marker；不是镜像实际运行了旧代码。
因此短 marker 不是本次运行时故障根因，但它会误导只读取短 marker 的巡检或回滚工具，应在下一次
受控发布时一并校正，并增加 full marker / OCI revision / short marker 一致性门禁。

## 运行时门禁

| 能力 | 安全配置结果 |
|---|---|
| 采集 | 上海时区；legacy schedule 06:30；catch-up 12 小时 |
| 治理 | `GOVERNANCE_ENABLED=true`，scheduler/worker 均启用，AI mode 为 `zhipu` |
| 内容 | scheduler/worker 均启用；slot mode 及 morning/noon/evening 均启用 |
| 时段 | target 07:30 / 12:30 / 18:30；提前 90 分钟准备；迟到窗口 60 分钟 |
| 图片 | enabled；provider mode `comfly`；图片 OCR 和图片质量模型门禁关闭 |
| 企业微信 | enabled；`group_webhook`；auto delivery 开启；发送前人工审核关闭 |
| 公众号草稿 | enabled；`draft_only`；auto enqueue/production 均开启；minimum week 2026-09-07 |
| 品牌检索 | configured `auto`；visual embedding mode `disabled`；**resolved brand mode `disabled`** |

门禁没有关闭企业微信发送，也没有关闭选题或图片生成。真正不一致的是：内容生成整体启用，但其必须的
品牌向量 Provider 被解析为 disabled。

## 2026-09-04 因果链

### Morning

1. 06:00 采集运行完成为 `partially_succeeded`：11 个 source job 中 8 succeeded、3 failed，形成 2 个
   new item。失败安全码为既有 source 级 `conflict`；仍有足够输入进入下游。
2. 治理运行完成为 `partially_succeeded`：36 个 job 中 32 succeeded、4 review-required、0 failed。
3. 时段选题运行 `succeeded`：405 个 score、82 个 eligible、选出 3 个、unfilled 0。
4. 3 个 copy run 全部 `review_required/copy_provider_unavailable`，active draft 0。
5. Copy provider attempt、image、package、WeCom window/job/attempt 全为 0。

### Noon

1. 11:00 采集运行完成为 `partially_succeeded`：11 个 source job 中 10 succeeded、1 failed，形成 12 个
   new item。
2. 治理运行完成为 `partially_succeeded`：45 个 job 中 40 succeeded、5 review-required、0 failed。
3. 时段选题运行 `succeeded`：415 个 score、87 个 eligible、选出 3 个、unfilled 0。
4. 3 个 copy run 全部 `review_required/copy_provider_unavailable`，active draft 0。
5. Copy provider attempt、image、package、WeCom window/job/attempt 全为 0。

因此采集中的局部失败和治理中的 review-required 不是这次“完全没有新闻”的阻断点：两个时段都明确
产生了 3 个有效 selection。首个导致整条链路归零的阶段是 copy generation。

### Evening

诊断结束时为 13:47，evening 的 preparation time 17:00、target 18:30、expiry 19:30，尚未产生当日
evening run。这是下一次自然调度窗口，而不是当前已有失败记录。

## 根因证明

1. 当前应用镜像和完整 release marker 都是 `40e4dec...`，该提交包含 `719d9f9` 引入的品牌向量
   Provider 解耦改动。
2. 运行时安全配置是：
   `BRAND_EMBEDDING_PROVIDER_MODE=auto`、`AI_PROVIDER_MODE=zhipu`、
   `VISUAL_EMBEDDING_PROVIDER_MODE=disabled`。
3. 由正在运行的应用 Settings 实际解析得到 `resolved_brand_embedding_provider_mode=disabled`。
4. 部署版本的代码在该 mode 为 disabled 时不创建 `brand_repository`/`brand_embeddings`；只有两者存在
   才创建 copy generator、auditor 和 `BrandRagContextRetriever`。
5. Copy executor 在品牌 retriever、generator 或 auditor 任一个缺失时，直接持久化
   `copy_provider_unavailable`，不会进行 Provider 请求。
6. 数据库与日志完全吻合：最近 48 小时有 18 条
   `copy_generation_review_required/copy_provider_unavailable`；相应日期 copy Provider attempt 为 0。
7. 生产并非没有品牌数据：全历史共有 120 个 chunk 和 120 个 embedding，其中 113 个是 Zhipu
   `embedding-3/2048`、7 个是历史 fake identity。当前 4 个 active 文档版本合计 58 个 chunk/embedding，
   其中 57 个是 Zhipu、1 个仍是 fake。故障来自运行时初始化策略与已存在向量身份不一致，不是品牌库为空。
8. 回看部署前后：9 月 2 日 morning/noon 仍产生 accepted copy、图片、素材包和 delivered WeCom job；
   当前镜像上线后的第一个 evening 时段从 17:06 开始统一出现该错误。9 月 3 日三个时段和 9 月 4 日
   已发生的两个时段继续复现。

## 影响

- 受影响时段：9 月 2 日 evening、9 月 3 日 morning/noon/evening、9 月 4 日 morning/noon。
- 每个时段 3 个 selection，共 18 个 copy run；active draft 0。
- 这些工作没有形成 image、material package、delivery window 或 WeCom job，因此没有当前事故对应的
  `failed`、`partial` 或 `delivery_unknown` 发送终态。
- 全库历史 WeCom 记录仍显示 95 个 delivered job；另有 1 个早期、与本次日期无关的 provider-rejected
  job。这进一步说明 Dispatcher 本身不是当前首个断点，但不代表历史链路从未发生过单次发送失败。
- 9 月 4 日 morning 和 noon 的发送窗口已经分别在 08:30、13:30 结束，不能通过简单重启恢复。

## 微信公众号周链路

- `official-account-weekly-scheduler`、DAG worker 和 draft worker 均 running，restart 0。
- 周调度器启动契约为 Monday 09:00、Asia/Shanghai、24 小时 catch-up、minimum week 2026-09-07。
- 最近 48 小时的有界安全日志中，566 次 `official_account_weekly_reconciled` 均为 `due=false`。
- 周 run/node/attempt 和公众号 draft job/item/attempt 总计均为 0。
- 草稿 Worker 最近的 reconcile 结果持续为 discovered 0、enqueued 0、existing 0、skipped 0。

这部分符合设计，不是 9 月 4 日没有日常企业微信新闻的原因。即使 9 月 7 日成功，它也只创建未发布
公众号草稿，不会自动发表、群发或替代企业微信日常推送。

## 最小安全处置建议（未执行）

### P0：修复下一自然时段

推荐新建修复任务，对当前部署版本做一个 Zhipu 品牌向量兼容热修，而不是直接切换到另一个视觉/向量
Provider：

1. 为 brand embedding 增加明确的 `zhipu` runtime identity，恢复使用既有 Zhipu
   `embedding-3/2048` 的查询 adapter；不要让 `AI_PROVIDER_MODE=zhipu + brand=auto + visual=disabled`
   静默解析为“内容 Worker 正常运行、copy 实际不可用”。
2. 检索必须按 provider/model/dimensions/input-version 严格匹配，不能混用现存的 7 个 fake embedding；
   对 active 版本中仍存在的 1 个 fake embedding 所属版本应先 fail closed，再在受控任务中重新索引。
3. 加入启动/doctor 门禁：当自动内容发送启用而 resolved brand mode 为 disabled 时，内容 Worker 应启动
   失败或明确进入 unhealthy，而不是持续消费并终结业务任务。
4. 增加告警：任一生产时段出现 `copy_provider_unavailable > 0`，或 selection > 0 且 package = 0，立即告警。
5. 用 immutable image 完成 focused tests、provider-compatible brand retrieval smoke 和单个新任务验收后再部署；
   同时修复短 release marker。所有 live smoke、部署和重启都需要新的明确授权。

诊断时距离 17:00 evening preparation 尚有时间，但任何修复都应以测试和去重门禁为先，不能仅重启当前
Worker：当前配置重启后仍会复现相同错误。

### P0：历史任务处置

18 个 copy run 已是 terminal `review_required`，修复 Worker 后不会自然重试。9 月 4 日 morning/noon 及更早
窗口也已过期：

- 不要批量 replay 或自动补发。
- 持久化证据显示这些任务的 Provider/WeCom attempt 为 0，因此当前系统内没有对应外部副作用；但若要
  补发，仍应创建新的、显式批准的 business identity 和 delivery window，而不是篡改旧终态。
- 可选择只修复未来时段，或人工挑选少量历史 selection 进入新日期的受控 backfill；两者都属于本次
  只读诊断之外的生产 mutation。

## 最近 48 小时安全日志交叉验证

日志只在服务器端投影固定 event、safe error/status/count 后输出，没有保留原始日志：

- acquisition scheduler：6 次 slot reconcile；worker 有 51 次 succeeded，以及少量 `conflict`、
  `parse_failure`、`network_failure`。
- governance scheduler：6 次 reconcile；worker 有 211 次 completed，另有安全码
  `provider_request_rejected` 和 `invalid_provider_output`，但时段仍产生足量 eligible selection。
- content worker：18 次 `copy_generation_review_required/copy_provider_unavailable`，6 次 slot job succeeded；
  没有 material package reconcile。
- WeCom Dispatcher：正常启动；没有本次日期的 durable job 可领取。
- weekly scheduler：持续 `due=false`；draft worker 持续 reconcile 但发现 0 个输入。

## 零副作用证明

诊断前后数据库总行数完全一致：

| 表族 | 前 | 后 |
|---|---:|---:|
| acquisition runs / attempts | 95 / 874 | 95 / 874 |
| governance runs / attempts | 97 / 2161 | 97 / 2161 |
| content slot runs | 61 | 61 |
| copy runs / attempts | 184 / 479 | 184 / 479 |
| image artifacts / material packages | 112 / 112 | 112 / 112 |
| WeCom jobs / attempts | 96 / 191 | 96 / 191 |
| weekly runs / draft jobs | 0 / 0 | 0 / 0 |

相关容器前后均 running、restart count 均为 0、image ID 不变。诊断仅执行了主机/容器状态读取、
allowlisted 配置读取、应用 Settings 的只读解析、catalog introspection、SQL `SELECT` 和经字段投影的
有界日志读取。

结果中未保存凭据、环境文件、用户/收件人 ID、新闻正文、标题、来源 URL、prompt、Provider body、
对象路径、图片或私有文件列表。
