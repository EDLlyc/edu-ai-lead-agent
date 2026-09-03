# IP 资产检索过滤与元数据修复

## Goal

让“头像、透明底、小赛”等自然语言检索不再因为推断出的分类条件而把相关图片全部过滤掉，
同时修复当前 41 张真实 IP 图片的结构化元数据，使后续向量、元数据与 RRF 排名使用一致、
可解释的数据基础。

用户价值是减少“明明有图却返回空结果”的情况，并让 AI 辅助识别不只是上传表单建议，
还能够安全地复核已有资产，而不静默覆盖人工确认的数据。

## Background

- 2026-09-02 的真实 Seed V2 成对评测已覆盖 41 张图片和 124 条查询；V2/V3 均有 6 条
  `degraded_metadata/partial_index`。
- 只读诊断证明这 6 条不是 provider 或向量缺失，而是自然语言中的角色/资产类型被转成 SQL
  硬条件后，41 图语料没有满足组合的候选。
- 当前 41 图元数据分布为 `full_body_action=31`、`scene_illustration=5`、
  `identity_reference=3`、`expression=2`，而 `portrait_avatar`、`meme_sticker`、
  `transparent_cutout` 均为 0；这与图片实际用途和 Seed V2 相关性判断不一致。
- 当前任务只处理过滤语义与元数据基础。拒答阈值、RRF 调参、单向量双策略回放和扩充 holdout
  属于后续独立评测任务。
- 已发生两次安全停止的历史 canary：首个 legacy 请求未保留可区分的错误类别，第二个修正后的
  `glm-4.6v-flash` 请求返回闭集 `provider_rate_limited`；均未继续批次或写库。用户随后明确将
  生命周期累计上限提高到 43 次，并允许改用高规格视觉模型。根据智谱官方文档，本次固定选择
  `glm-5v-turbo`；获批的剩余 41 次已用于一个成功 canary，以及复用该结果后继续的其余 40 张，
  最终累计调用恰好为 43/43。

## Requirements

### R1. 区分显式过滤与文本推断

- API/UI 显式传入的角色、资产类型、方向、来源、部门和标签继续作为硬过滤条件。
- 从自然语言文本自动识别出的角色、资产类型和方向只能作为软提示参与排序/解释，不能进入 SQL
  硬过滤。
- 文本检索仍使用生产向量路径；软化推断不得禁用 embedding、扩大到私有资产或绕过 ready/shared
  边界。
- 当显式硬过滤后确实没有候选时，返回闭集原因 `no_filtered_candidates`；只有过滤后存在资产但没有
  兼容向量时才使用 `partial_index`。

### R2. 已有 41 图的 AI 元数据复核

- 复用现有 AI 辅助识别能力和图片安全读取边界，为 41 张 approved/ready/shared 资产生成结构化
  建议；图片读取、栅格或内容级失败保持逐项隔离，共享的限流、超时或不可用失败则熔断剩余调用，
  并在诊断计划中把后缀明确标记为未调用。
- live plan 固定使用 `glm-5v-turbo`、关闭 thinking、并发 1、默认间隔 2 秒、每图最多一次请求；
  完整批次最多新增 41 次。canary 复用为首项，失败时不切换模型或继续批次；连同已发生的两次
  历史 canary，任务生命周期累计不得超过 43 次。
- 默认先生成本地 dry-run 审计产物，包含安全 asset ref、旧值、新建议、差异、模型/规则版本和
  闭集状态，不包含原始图片、对象路径、动态 UUID、provider body 或密钥。
- apply 必须绑定 dry-run 的资产内容哈希与旧元数据指纹；发生资产或元数据漂移时 fail closed，
  防止覆盖并行修改。
- 只更新实际变化且通过领域校验的结构化元数据；不修改图片二进制、下载统计、收藏状态、个人素材
  归属、生成记录或现有 embedding。
- 更新后产生新的可复核资产元数据快照；真实 Seed V2 复跑属于后续步骤，本任务只运行
  provider-free 检索回归与元数据一致性检查。
- AI 建议属于 `ai_suggestion_unreviewed` 证据，不宣称人工 Gold。apply 使用确定性的保守合并：
  已有非 `other` 角色优先保留；有效的新资产类型可替换导入时的粗分类；可选字段只用非空建议
  更新；free tags 规范化合并并受现有上限约束。最终 plan 同时保存 provider suggestion 与实际
  proposed metadata，便于审计和恢复。

### R3. 兼容与可观测性

- 保持现有上传页面“用户点击 AI 辅助识别后才调用”的交互不变。
- 保持图片搜索、列表、下载、收藏、AI 创作和翻页相册 API 兼容。
- 批处理命令必须显式 opt-in；普通启动、测试和 `make eval-check` 不得调用外部模型。
- 记录安全的 scanned/changed/skipped/failed 聚合和闭集失败原因，不记录图片内容或用户信息。

## Acceptance Criteria

- [x] 不带显式筛选的“头像/透明底/角色”等文本查询不会再因推断条件产生零候选硬过滤；显式筛选
      仍能严格限制结果。
- [x] `no_filtered_candidates` 与 `partial_index` 具有不同、可测试的触发条件和前端安全文案。
- [x] 41 图 AI 元数据 dry-run 具有确定 schema、身份/漂移校验、隐私约束和每项闭集状态；未显式
      apply 时数据库零写入。
- [x] apply 只接受与 dry-run 身份一致的资产，并以幂等方式更新有效差异；第二次 apply 为零变化，
      漂移输入被拒绝。
- [x] 元数据修复后至少不再错误地把全部真实图片集中到少数资产类型；最终分布与逐图差异记录在
      本地忽略产物中，不把 AI 建议宣称为人工 Gold。
- [x] live plan 使用 `glm-5v-turbo` 且 provider/model identity 严格匹配；本轮最多新增 41 次请求、
      生命周期累计最多 43 次，canary 失败即停止，实际调用数进入安全审计产物。
- [x] 单元/集成/契约测试覆盖软提示、显式硬过滤、零候选、部分索引、dry-run、apply、漂移、幂等、
      隐私和旧 API 兼容；Ruff、Mypy、相关评测门禁与 `git diff --check` 通过。
- [x] 不推送、不部署，不自动复跑 248 次真实检索，不修改无关并行任务文件。

## Out of Scope

- 选择性拒答阈值校准、RRF 权重调优或切换线上默认检索版本。
- 新增网页评测/标注区域、人工 Gold 或用户鉴权。
- 重新生成图片、重建现有图片 embedding、上传服务器或发布生产环境。

## Key Decisions

- 本任务把软提示视为 V2/V3 排名器之前的候选正确性修复，保留两个 rank selector 版本和权重；
  live/canonical 证据仍必须绑定 Git SHA，不能只凭 `search_version` 比较不同代码版本。
- 本地 repair audit 使用 Git 忽略的 plan/result/restore artifact，不新增数据库 revision 表或 Alembic
  迁移。若未来需要多操作员、长期生产审计，再单独设计持久版本表。
- metadata apply 逐资产短事务、`FOR UPDATE` 与 before/proposed fingerprint CAS；第二次 apply
  返回 `already_applied`，并可从 result artifact 反向 restore。任何并行元数据变化都会 fail closed。
- 新模型执行使用 canary-v2/plan-v2/result-v2 schema、v2 fingerprint domain 和 v2
  acknowledgement；旧 `glm-4.6v-flash` v1 artifact 与旧 acknowledgement 均不能进入
  GLM-5V-Turbo plan/apply/restore。
- 识别只接收从已验证 MinIO 原图重新编码的像素；plan/result 不包含路径、文件名、对象 key、动态
  UUID、原始图片、provider body、请求 ID、凭据或用户信息。

## Risks and Deferred Items

- `IpAssetRecord.tags` 当前丢失数据库 tag dimension，不能用于 before/rollback；实现必须在仓储事务
  内读取 `dimension='free'` 的原始 tag rows。
- 修改分类必须同时重新派生 canonical name，否则名称与分类会冲突；稳定 `asset_ref`、图片 bytes、
  embedding、收藏/下载/归属/生成关系保持不变。
- 模型建议可能有业务语义误差，因此保留完整 before/suggestion/proposed/result 和可逆 restore；
  本轮不把 AI 建议升级成人工真值。
