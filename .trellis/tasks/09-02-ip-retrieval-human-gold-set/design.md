# IP 检索真实图库 Seed Eval V1：技术设计

## 1. 边界

V1 是 backend-only 离线评测能力。它不增加网页、API route、数据库 schema 或用户操作入口。交付物由版本化 dataset、Codex seed、真实检索 run observation、指标引擎和报告组成。

```text
41 张 approved 本地图片 ──视觉检查──> 41-item safe asset snapshot
100 条脱敏 query ────────────────> query set v1 (80 dev / 20 holdout)
query × asset 独立标记 ─────────> 4,100 codex_seed grades
真实 production retrieval ─────> safe top-k run observation
run observation + seed labels ──> metrics + bootstrap CI + report
```

Labels 永远位于 ranking 之后，不能进入 query extraction、embedding、metadata scoring 或 RRF。

## 2. 文件布局

新增 `backend/evals/ip_asset_retrieval_grounded/`：

- `models.py`：Pydantic strict/frozen schemas 与版本常量。
- `dataset.py`：JSONL loaders、hash、类别/split、完整矩阵和敏感字段验证。
- `queries.v1.jsonl`：100 个 query records。
- `codex-seed.v1.jsonl`：100 个 label-matrix records，每条含完整 41 grades，共 4,100 judgments。
- `assets.py`：从批准 manifest 构建 safe asset snapshot/fingerprint，并在 live run 时映射动态 asset records。
- `metrics.py`：graded ranking metrics、no-answer 轨道、aggregate 和 paired bootstrap。
- `runner.py`：`validate-seed`、`preflight-live`、`run-live`、`compare-runs`、`write-reviewed-baseline` 子命令。
- `reporting.py`：canonical JSON/Markdown serialization。
- `README.md`：操作方法、口径和限制。
- `canonical-seed-report.json` / `.md`：只冻结 dataset/schema/label distribution 与 provider-free metrics-contract fixture，不冻结一次易漂移 live provider 排名。

Live run observation 默认写到用户显式指定的输出目录；输出目录不包含图片、向量、私有路径或 provider body。除非经过 review/write 命令，不自动覆盖 committed baseline。

## 3. Schema

### Query record

- `schema_version`
- `query_ref`：稳定 safe slug，不含业务/个人身份
- `category`：受控枚举
- `split`：`dev|holdout`
- `query`：1..200 的脱敏中文文本
- `expected_answer_kind`：`has_relevant|no_answer`

### Seed matrix record

- `schema_version`
- `query_ref`
- `label_source="codex_seed"`
- `evaluator_version`
- `rubric_version`
- `grades`：exactly 41 个 `{catalog_ref, grade}`，catalog ref 唯一、grade 0..3

### Safe asset snapshot

- `catalog_ref`：批准 catalog 的稳定 16-hex public ref
- `display_name` 与受控 category/character/role/scene/topic tags（仅用于审查和展示报告摘要）
- snapshot 导出不含 filename、relative path、SHA/checksum、asset/database UUID 或 media bytes

### Live run observation

- `run_ref`、timestamp
- dataset/query/seed/asset/rubric hashes
- search version、mode、embedding provider/model/dimension/input-policy identity
- 每条 query 的 top 8 safe catalog refs、typed failure/degraded reason
- 不含 labels、score/cosine、vector、provider body/request ID、private path 或 profile

## 4. 41 图身份与完整性

Dataset 用稳定 `catalog_ref`，不绑定动态数据库 UUID。内部 loader 从批准 manifest 验证 exactly 41 approved items，并以排序后的 safe refs + 受控 publication identity 计算 asset-set fingerprint。

Live runner 通过现有 checksum-aware catalog adapter 与动态 IP rows 映射；checksum 只在进程内使用。必须证明 41:41 唯一映射、动态 row `ready && shared`、embedding identity 兼容。任何缺项、重复或 drift 都在 provider call 之前失败。

## 5. Query 与 Codex 标记流程

查询主类别：character、asset_type、emotion、action、scene、intended_use、transparent_background、combined_constraints、paraphrase、noisy_alias、no_answer。文件显式写入 split，loader 强制 exactly 100 / 80 dev / 20 holdout 和每类最小覆盖。

Codex 标记顺序：

1. 创建临时 contact sheet/逐图视图，查看每张原图；临时视觉材料不提交。
2. 固定 queries 和 rubric，再建立不含检索排名的视觉事实笔记。
3. 逐 query 对完整 41 项评分；每条记录必须一次覆盖整个 asset set。
4. 执行 4,100 uniqueness、grade/category/split/no-answer consistency、敏感字段和 asset fingerprint checks。
5. 抽查同框、角色冲突、透明底、场景缺失、用途相近、hard negative 和“小赛和赛先生在空间站”。

`expected_answer_kind` 必须与 grades 一致：`no_answer` 的 41 项全部 `<2`；`has_relevant` 至少一项 `>=2`。

## 6. 真实检索适配

Runner 复用 `IpAssetService` 的生产 `search_text` 数据流。为防止污染业务匿名聚合，在 application service 增加一个仅内部可调用、默认关闭的 evaluation boundary，或注入 no-op outcome recorder；普通 HTTP search 始终保留现有写聚合行为。

Evaluation boundary 必须复用：

- current-turn filter extraction；
- metadata candidate pool/ranking；
- configured visual embedding identity 和 vector repository；
- `_merge_text_search_hits` 与 production V2/V3 selector；
- top-k 限制和 degraded/typed failure 语义。

它不得新增公开 API parameter 让普通用户选择 search version，也不得复制一份容易漂移的 ranking implementation。V2/V3 通过显式 runner configuration 各生成一个 observation，再离线 paired compare。

## 7. 指标

- usable relevant：grade `>=2`。
- Recall@3/5：top-k 命中的 usable relevant / 全部 usable relevant。
- MRR@5：首个 usable relevant 的 reciprocal rank。
- nDCG@5：gain=`2^grade-1`，使用 0–3 全等级。
- no-answer：当所有 grade `<2` 时单列 correct abstention、false-positive 和 returned-count；不进入普通 Recall/MRR 宏平均。
- aggregate：全局、category、dev/holdout、semantic/degraded mode。
- paired CI：以 query 为单位、固定 RNG seed、10,000 bootstrap resamples，报告 V3-V2 metric delta percentile 95% CI 与有效 sample count。

若 run failure 或 missing observation，报告 coverage/failure rate，不把缺失 query 计为零分后掩盖 provider 可靠性问题。

## 8. Offline review template

可选 CLI 导出空白 CSV/JSONL，字段为 query ref/text、catalog ref、grade、note。它只是未来人工复核模板，不含网站、共享进度、身份、数据库或 Gold promotion。任何手工填充结果在独立后续任务审查前不得替换 `codex_seed` 或生成 human agreement 声明。

## 9. 兼容、上线与回滚

- 保留 `backend/evals/ip_asset_retrieval/` 原 41-case suite 和 `make ip-asset-retrieval-eval`。
- 新增独立 Make targets：seed validation/canonical check、live preflight/run、paired compare。
- 普通 `make eval-check` 只加入 provider-free seed/schema canonical check；live target不加入。
- 新增 service internal boundary 时默认行为保持业务聚合开启；只有 runner 显式关闭。
- 回滚只需移除 grounded eval directory、Make/docs/spec 入口和 internal no-telemetry boundary；无数据库或前端状态需要迁移/清理。

## 10. 隐私与真实性

- 不读取或保存线上原始查询、profile、逐事件用户行为。
- 不提交私有图片、路径、文件名、checksum、object key 或 vector。
- 报告 title 与 maturity 始终使用 `Codex seed` / `seed`；只有未来独立人工任务可以升级为 reviewed/gold。
- 一次 live run 只能证明固定时间、固定模型和固定 41 图上的结果，不外推业务转化或通用多模态检索能力。
