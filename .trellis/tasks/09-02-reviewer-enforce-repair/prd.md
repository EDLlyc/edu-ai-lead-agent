# Reviewer Enforce 单次返工

## Goal

在校准后的 enforce 模式中实现一次 Writer 定向返工、不可变 revision lineage、恢复与人工兜底。

## Requirements

- Dependency: `09-02-reviewer-contract-eval` 与 `09-02-reviewer-observe-governance` 必须完成并提交；
  enforce 默认仍关闭，不能由 fixture 或迁移自动开启。
- 现有 `official_account_article_versions.version` 是 schema family v1-v6，禁止复用为返工轮次；迁移应
  引入独立 revision identity（例如 `revision_no` 与 `repair_of_article_version_id`），旧 row 回填初稿。
- 初稿、修复稿和两次 review 均不可变并有独立 SHA/fingerprint/Artifact；active article 只指向当前
  合法 revision，下游查询必须按 active ID 而非任意 run 首行读取。
- Reviewer 不能修改文章；repair Writer 只接收闭集 issue/ref 和原有受控上下文，通过独立 worker
  allocation/Capability/预算生成 revision 2，随后重跑 deterministic validation 与 Reviewer。
- 第二次 rejection、non-repairable、manual_review、unavailable、provider failure、lease loss 或预算
  耗尽都不再派生，稳定进入人工复核/失败；重启和重放不能重复 provider 调用或覆盖成功 revision。

## Acceptance Criteria

- [x] 每个 run 最多两个 revision、一次 repair；并发和 retry 不能产生 revision 3 或新预算。
- [x] 旧 verdict/人工批准不能投影到新 SHA；render/media/draft/handoff 只消费 active revision。
- [x] Reviewer 无写权限、Writer 无 review/approve 权限，越权在 handler/provider 前失败。
- [x] 真实 PostgreSQL 测试覆盖 crash-after-review/repair/re-review、lease reclaim、stale fencing、replay、
      active revision、下游 lineage 和 downgrade refusal。
- [x] enforce 关闭时 observe/off 行为不漂移；人工审批和不自动发布边界保持不变。

## Out of Scope

- 不允许第二轮返工、动态多 Agent、自动换模型绕预算、自动发布或取消人工审批。
