# 图片质量评测 MVP

## Goal

把现有“图片文件可用、链路可交付”的门禁扩展成第一版可复现、可解释、可追溯的图片质量评测能力：建立 provider-free 图片评测 harness，并把可选图片审校结果绑定到最终 publication bytes。该 MVP 要形成可在 CI 复现的证据和诚实的简历口径，同时默认不改变现有发布放行行为。

## User Value

- 开发者可以在无 API key、无网络、无私有图片的环境中复现评测 policy、指标聚合和 canonical drift。
- 公众号正文图经过裁切/压缩后，其评测状态与最终 SHA-256、rubric 和 evaluator 版本绑定，不再把“ready”误表述为“已完成多模态质量审校”。
- 后续接入真实 VLM、DINO/CLIP-I 和人工标定时，可以复用稳定 schema 与报告格式，而不需要推翻 CI 基线。
- 简历只引用可追溯的离线契约结果；本阶段不宣称已经取得 human-aligned 图片质量指标。

## Confirmed Facts

- `backend/evals/visual_retrieval/` 当前 6 个 case 使用合成 metadata 和预置 semantic score，只证明排序与 fallback 契约。
- `backend/app/domain/image_validation.py` 已覆盖 bytes、MIME、签名、解码、尺寸和 exact visual text。
- `backend/app/application/ports/image_validation.py` 的可选 `ImageQualityAuditor` 当前只返回 accepted、provider/model/fingerprint 和 bounded issues，没有 rubric/versioned per-dimension observation。
- `backend/app/application/services/official_account_visual_generation.py` 会生成最终 1536×1024 JPEG publication bytes；裁切/压缩后没有持久化 per-image audit record。
- `StoredOfficialAccountGeneratedVisual` 和 `official_account_generated_visuals` 当前只保存状态、媒体属性、SHA-256、尺寸和错误。
- `official_account_editor_handoff_v2.py` 当前会把 ready generated visual 投影为 `durable_image_audit_accepted`，即使没有与最终 SHA-256 绑定的 per-image audit。
- 当前工作树的 `topic_rerank` canonical check 在 `priority-barrier` 失败，且相关文件已有用户修改；本任务不得修改或掩盖该漂移。
- 完整证据和行业指标边界记录在 `research/evaluation-image-audit.md`。

## In Scope

### R1 — Provider-free image-quality eval harness

- 新建 `backend/evals/image_quality/`，包含严格 schema、版本化 rubric、至少 40 个脱敏 fixture case、冻结 observation、runner、JSON/Markdown canonical report 和 README。
- case 至少覆盖 semantic、IP identity、OCR/text、aesthetics/artifacts、publication crop/layout、batch diversity 六个维度，并包含 critical defect、普通 warning、borderline 和 hard-negative 场景。
- 数据集不得包含 `private/` 图片、原始 prompt、provider body、向量或内部对象路径；可以使用安全 hash、public asset ref 和冻结 observation。
- README 与报告必须声明：这些 case 证明 schema、metrics 和 decision-policy conformance，不证明 live model 或人工一致性。

### R2 — Explainable metrics and decision policy

- observation 输出稳定 issue code、dimension、severity、score/confidence（适用时）、evidence ref、evaluator/rubric version。
- report 至少包含 per-dimension coverage、critical defect precision/recall/F1、false-pass rate、manual-review rate、case 分布、dataset SHA-256、rubric version 和 decision-policy version。
- hard gate 与 ranking/review signal 分离；关键语义、禁用元素、关键文字和 IP 身份失败不能被审美分抵消。
- runner 对 malformed、duplicate、未知 dimension/issue、非法分数、hash drift 和 canonical drift 给出 expected/actual 诊断。

### R3 — Final-publication visual eval record

- 新增 immutable `VisualEvalRecord`（命名可按项目 convention 调整），绑定 generated visual、最终 publication SHA-256、rubric/policy/evaluator 版本、decision、issues 和完成时间。
- record 的持久化必须经过现有 fenced run/transaction 约束；不得保存图片字节、raw prompt、provider body、向量或私有目录路径。
- 在 publication bytes 准备完成后、ready 状态交接前，允许可选 evaluator 产生 observation；本 MVP 默认 `off`，`observe` 模式只记录结果，不阻止发布。
- provider/evaluator 不可用必须被准确记录为 unavailable 或 no-record，不能伪装成 accepted。

### R4 — Truthful handoff projection

- 只有存在 accepted、版本合法且 publication SHA-256 匹配的 record 时，handoff 才能输出 `durable_image_audit_accepted`。
- off、unavailable、未审校或 hash 不匹配时，继续使用现有非自动审校语义（如 `passed_local_visual_inspection`），但不改变图片是否可进入现有人工交付流程。
- 旧数据没有 eval record 时必须可读取、可交付，不做回填和破坏性迁移。

### R5 — Tests, documentation, and resume evidence

- 增加 domain、runner、service/repository、数据库约束和 handoff 投影测试。
- Makefile 增加无网络 canonical check 入口。
- 更新作品集/评测文档，准确区分 file-valid、provider-free policy eval、observed audit 和 accepted audit。
- 输出当前可写的简历 bullet；真实 human agreement、误放率改善和业务收益继续保留为未来占位，不填假数字。

## Acceptance Criteria

- [x] `image_quality` 至少 40 个唯一 case、六个维度齐全，数据集和 canonical report 有稳定 SHA/version。
- [x] provider-free runner 可生成报告并通过 `--check`；故意改变 case、rubric 或 canonical 会以明确原因失败。
- [x] report 给出分维度指标、critical precision/recall/F1、false-pass/manual-review rate，不生成可掩盖 hard failure 的总分。
- [x] 最终 publication SHA-256 可关联 immutable eval record；记录不包含敏感图片、prompt、provider body 或向量。
- [x] 默认 off 与 observe 模式均不改变现有发布放行行为；observe 可持久化 accepted/review/rejected/unavailable 结果。
- [x] handoff 只有在 accepted record 与最终 SHA-256/版本匹配时才声称 `durable_image_audit_accepted`；旧数据保持可交付。
- [x] focused unit/contract/integration tests、format、lint、typecheck 和 eval canonical check 通过。
- [x] README/作品集清楚声明 fixture 与 live/human quality 的边界，不新增未经实测的简历数字。

## Key Decisions

- MVP 使用单一任务、按 harness → durable record 的依赖顺序实施；两个交付物共享 schema 和 decision policy，拆成并行子任务反而会制造重复契约。
- 默认模式为 `off`；`observe` 只记录不阻断，`gate` 延后到人工标定之后。
- provider-free fixture 使用冻结 observation，不声称这些 observation 来自多人标注。
- 评测对象是最终 publication bytes，而不是只评估原始生成结果。
- 角色一致性与场景多样性分开报告；不设置单一综合图片总分。

## Out of Scope

- 不执行付费或 live provider 调用。
- 不在本阶段实现 DINOv2/CLIP-I、ImageReward/PickScore 或新 OCR 引擎。
- 不伪造 2–3 人标注、Krippendorff's alpha、judge-human agreement 或业务提升数字。
- 不启用自动 release gate，不自动重生成，不改变人工发布边界。
- 不实现 320/375/430 screenshot visual diff dashboard；该项属于后续 Phase 4。
- 不修复或更新当前 `topic_rerank` 的用户修改和 canonical failure。

## Risks and Rollback

- 数据库迁移与旧数据兼容是最高风险；新增表/可空关系应保持 additive，回滚时可以停用 evaluator 而不影响 ready visual。
- VLM judge 可能存在偏差；MVP 只支持 observe 和离线 policy 证据，不把它作为最终真值。
- 工作树已有大量用户修改；实施必须限制在任务相关文件，禁止重置或覆盖其他改动。
- 若全量 backend check 被既有 `topic_rerank` 漂移阻断，必须报告 focused checks 与既有失败，不能更新无关 canonical 使其变绿。
