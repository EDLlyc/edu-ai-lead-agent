# 受治理的 Worker–Reviewer：实施计划

## Phase 0 — 规划与基线

- [x] 检查现有 Article generator/auditor、copy 单次修复、execution governance、weekly DAG、handoff 与
      eval 能力，确认可复用边界。
- [x] 冻结 `off|observe|enforce`、最多一次返工、Reviewer 编辑职责和 live 证据约束。
- [x] 拆成四个串行、可独立验收的子任务，记录迁移与高冲突文件风险。
- [ ] 用户审核并明确批准最终 PRD/design/implement 后，才启动第一个子任务。

## Phase 1 — Reviewer 契约与 provider-free eval

- [ ] 启动并完成 `09-02-reviewer-contract-eval`，提交闭集 verdict/rubric/repair policy。
- [ ] 建立至少 48 条脱敏 fixture、canonical drift 与安全/质量指标，明确不代表 live 模型表现。
- [ ] 通过 task-scoped review/check，提交并归档；后续子任务只消费该已提交契约。

## Phase 2 — off/observe 治理接入

- [ ] 从实施时真实 migration head 开始，完成 durable review intent/result 与 exact artifact binding。
- [ ] 将非 off 的 initial Writer/Reviewer 接入既有 allocation、Capability Gateway、预算与安全 Trace。
- [ ] 证明 off 零漂移、observe 不改变 gate/release、ambiguous outcome 不盲目重调。
- [ ] 完成 `09-02-reviewer-observe-governance` 的真实 PostgreSQL、并发、隐私和回归检查后独立提交。

## Phase 3 — enforce 与单次返工

- [ ] 新增 Article `revision_no`/`repair_of`，迁移旧 row 为 revision 1，并改为 active-ID 精确读取。
- [ ] 实现代码拥有的 RepairDirective、独立 repair Writer、全量重验与第二次 Reviewer 终态。
- [ ] 将 exact active revision/review 绑定 render、draft 与 editor handoff fingerprint。
- [ ] 验证 crash/restart/replay/lease/fencing/预算失败不会重复调用或产生 revision 3，独立提交子任务。

## Phase 4 — opt-in live A/B 与晋级证据

- [ ] 先实现 dry-run/preflight、费用与样本上限、paired manifest、人工 gold worksheet 和报告生成器。
- [ ] 只有获得用户对 provider、样本数和费用的单独明确授权后才调用 live 模型。
- [ ] 报告质量/成本/延迟/bad cases；有效人工校准报告 SHA 是 enforce 晋级的必要条件。
- [ ] 无有效 live 数据时保持“框架已实现、线上收益未测”的真实表述。

## Phase 5 — 父任务集成与交付

- [ ] 串行验证四个子任务 commit、单一 Alembic head、off/observe/enforce 矩阵和 handoff/Workbench 回归。
- [ ] 运行 Ruff、format、mypy、unit/contract/real PostgreSQL integration、migration、privacy、eval、
      `git diff --check`，并由 Trellis check 修复真实问题。
- [ ] 把经验证的执行契约更新到 `.trellis/spec/`；仅用可追溯报告数字整理简历/作品集表述。
- [ ] 用户确认 scoped commits 后归档父任务并记录 session。

## 风险与回滚点

- 当前 worktree 有大量用户/其他任务改动；只编辑当前 Reviewer 任务拥有的文件，遇到 config、schema、
  migration head、handoff 或生成契约重叠时先重读最新版本，不回退他人修改。
- 每阶段用独立 feature/version boundary 回滚；`off` 是运行时回滚开关，已有 review/revision rows 保留
  可读，不通过破坏性 downgrade 清除。
- Reviewer provider、repair provider 与 live A/B 都是额外成本边界；未配置/未授权不能隐式 fallback
  到另一模型或重复尝试。

## Pre-start gate

- [x] 父/子 PRD 已明确范围、依赖、真实指标与禁止项。
- [x] 父 design/implement 已定义权限、数据、恢复、rollout 与评测架构。
- [x] 父/子 context manifests 均为真实 spec/research 条目且 `task.py validate` 通过。
- [ ] 用户批准本次最终规划摘要。
