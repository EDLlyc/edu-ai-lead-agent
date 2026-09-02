# Reviewer Observe 治理接入：技术设计

## 1. 生产路径

`off` 继续走现有 generator -> deterministic validation -> legacy auditor，不创建任何新治理或 review
数据。新 run 冻结为 `observe` 时：

1. initial generation 使用不变的 provider request/prompt，但由 `official.writer.initial` worker allocation
   和 `official.article.generate` capability 治理；已持久化文章的 compatible resume 不重复调用。
2. 文章通过 deterministic validation 与 legacy hard auditor 后，注册 exact Article SHA artifact。
3. durable review request 先进入 `calling`，再由 `official.reviewer.r1` 和 artifact-scoped
   `official.article.review` capability 调用新 editorial Reviewer。
4. 严格解析后持久化 immutable record 和 safe execution artifact；任意 verdict 都不改变既有 render、
   handoff、manual review 或发布资格。

如果 legacy hard gate 未通过，不调用 editorial Reviewer；记录仍真实表示“未执行”，不伪造 accepted。

## 2. 配置与冻结身份

新增版本化 `OFFICIAL_ACCOUNT_REVIEWER_MODE=off|observe|enforce`，默认 `off`。本子任务只允许 off/observe
生效；请求 enforce 在生产状态机接入前 fail closed。mode、prompt/schema/rubric/policy、provider/model
identity 和预算进入新 run snapshot/fingerprint，历史 run 不被环境变化重解释。

Reviewer provider 可以复用现有模型基础 client，但必须使用独立 port、Prompt/schema identity 和预算；
不能复用 Writer allocation，也不能更改 legacy auditor payload。

## 3. 数据与 exactly-once

- additive review request 表保存精确 run/Article ID+SHA、上下文 fingerprints、模型/契约版本、execution
  identity/reservation 和唯一 request fingerprint；外部调用前持久化。
- immutable review record 保存 strict verdict、bounded issue snapshot、usage/latency、result fingerprint 和
  produced artifact/event binding。
- `calling` 后崩溃且没有 durable provider result 的请求进入 `result_unknown`/unavailable；不盲目重调。
- compatible replay 返回同一 request/record；同 identity 不同 fingerprint、scope、SHA 或版本 fail closed。

execution repository 只补充 exact artifact metadata lookup/compatible ensure 所需的窄接口。Artifact 正文
仍由 official-account repository/storage 拥有，Trace 仅保存 opaque ID/hash/计数/闭集状态。

## 4. 迁移与兼容

从实施时真实 Alembic head 创建 additive migration，并同步 ORM、head/compatibility/doctor tests。旧 Article
和 audit row 不回写虚假 Reviewer record。空特性数据时可 downgrade；存在 review request/record 或新
execution binding 时在 DDL 前拒绝。

## 5. 验证矩阵

- off：零新 provider call/row/allocation，现有 wire/status/bytes 不漂移；
- observe：四类 verdict 与 result_unknown 真实保存但无业务行为差异；
- authorization：Reviewer plan/write、跨 run/task、wrong SHA/version 在 handler 前拒绝；
- accounting：success/timeout/cancel/exception/oversize/unknown usage 只结算一次；
- restart/concurrency：intent 各边界、compatible replay、冲突 replay、lease lost、artifact registration；
- privacy：schema、trace、log、error/API 无正文、Prompt、provider body、凭据与私有路径。
