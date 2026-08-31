# IP 图片检索 V3

## Goal

把现有元数据分数与多模态相似度直接相加的检索升级为可解释、可回滚、可评测的 weighted RRF 排名融合，并用严格匿名的日聚合漏斗回答“是否更容易找到、预览、收藏和下载合适 IP 图片”。

## Background and confirmed facts

- `IpAssetService.search_text` 当前同时取得最多 500 个结构化元数据候选与兼容的 `vector(2048)` 候选。
- `_merge_text_search_hits` 将 metadata score 乘 `0.65`、归一化 cosine 乘 `0.35` 后相加；两个分数并非同一校准空间。
- 显式角色、类型、方向和归属过滤优先于当前轮推断；历史对话只提供语义上下文，不能恢复陈旧过滤。
- 缺失 embedding、provider 不可用或部分索引时必须保留 metadata-only 可用性。
- 现有下载排行榜只按资产与业务日期聚合，不记录 actor/profile/IP/UA；V3 不能降低这一隐私标准。

## Requirements

### R1 — 版本化 weighted RRF

- 新增 `ip-asset-hybrid-v3-rrf`，冻结 V2 直接加权函数作为比较和快速回滚路径。
- 元数据和语义候选先各自形成稳定的一基排名，再以代码拥有的 weighted RRF 融合；默认 `k`、两路权重和 tie-break 必须版本化并由单一纯函数拥有。
- 精确元数据证据仍应优先于仅有弱相似度的候选；metadata-only 和 semantic-only 资产都可进入结果，部分向量索引不能隐藏未索引资产。
- 显式过滤、当前轮推断优先级、退化原因、解释文本和安全文件名边界保持兼容。

### R2 — 离线检索质量集

- 新增至少 40 条脱敏、provider-free 查询用例，覆盖角色、资产类型、表情、动作、场景、用途、透明底与多条件组合；每类至少有正例、困难负例和允许无结果用例。
- 每例独立保存 graded relevance、元数据候选排名和向量候选排名；生产 RRF 函数直接参与评测，runner 不复制排序逻辑，也不能从期望顺序构造结果。
- 同一候选输入同时评估冻结 V2 和 V3，至少输出 macro Recall@5、MRR@5、nDCG@5、零结果率、类别分解和 dataset/hash/version。
- V3 的 macro Recall@5、MRR@5、nDCG@5 不得低于 V2；精确角色/类型/表情用例不得被 semantic-only 弱匹配压过。报告必须明确不代表真实线上 embedding 或用户效果。

### R3 — 严格匿名的聚合漏斗

- 新增按 `business_date + search_version + mode + event_kind` 聚合的计数，事件闭集为 `search_results`、`zero_results`、`preview_from_search`、`favorite_from_search` 和 `download_from_search`。
- 不保存原始/哈希查询、asset/profile 标识、浏览器会话、随机用户 ID、IP、UA、referrer、Cookie 或逐事件时间线。
- 搜索计数由成功的搜索响应服务端更新；预览、收藏和下载来源计数由前端显式携带闭集 `origin=search` 触发，失败操作不计入成功漏斗。
- 提供内部只读日/30 日汇总投影，返回计数和可解释比率；小样本不显示为“准确率”，未知版本/事件拒绝。

### R4 — 兼容、发布和界面

- V3 在离线门禁通过后成为默认搜索版本；一个显式配置可以回退 V2，API 始终返回实际版本、模式和退化原因。
- 图库交互保持现有页面结构；只增加无侵入来源标记和必要的请求 wiring，不新增公开运营分析后台。
- 现有无鉴权/本地 profile 不是安全身份，指标实现不得把 profile token 当用户标识。

## Acceptance Criteria

- [x] 同一合成候选输入下，V2 与 V3 输出字节稳定；V3 对 metadata-only、semantic-only、重叠候选和稳定 tie 均有单元测试。
- [x] 至少 40 个用例通过 schema、隐私和 oracle-isolation 检查；canonical JSON/Markdown 可用 `--check` 检测漂移。
- [x] V3 macro Recall@5、MRR@5、nDCG@5 不低于 V2，所有硬过滤和精确元数据优先用例通过。
- [x] provider 禁用、异常和 partial index 时仍返回正确的 metadata 结果与真实 `degraded_reason`，且聚合计入实际模式。
- [x] 真实 PostgreSQL 测试证明聚合键并发 upsert、业务时区边界、30 日窗口和失败操作不计数；数据库/API/日志中不存在禁止字段。
- [x] 前端测试证明搜索、零结果、搜索来源预览/收藏/下载只发送闭集匿名指标，不改变普通浏览和个人资产访问控制。
- [x] migration/ORM/OpenAPI/生成类型、任务范围内 backend/frontend gates、隐私扫描和 `git diff --check` 通过；全仓库既有失败已独立记录，未归因于本任务。

## Out of Scope

- 保存原始查询、逐用户漏斗、用户画像、A/B 分流、推荐系统或公开数据看板。
- 新 embedding 模型、向量维度迁移、在线 provider benchmark、学习排序或 Elasticsearch/BM25。
- 修改图片生成、上传识别、收藏授权、下载排行榜口径或现有个人素材访问规则。

## Risks and deferred items

- 聚合漏斗不使用用户/会话关联，因此只能回答总体动作比率，不能计算独立用户转化或完整路径归因。
- fixture V3 不回归并不保证真实图库提升；上线后应观察至少一个完整统计窗口，再决定是否调权重或增加盲标集。
