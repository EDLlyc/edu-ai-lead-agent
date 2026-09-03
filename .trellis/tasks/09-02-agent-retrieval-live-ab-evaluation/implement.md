# Agent 检索增强真实 A/B 评测：实施计划

## Phase 1 — contracts and private dataset preparation

- [x] 新增 live A/B dataset/oracle/authorization/manifest/attempt/report 的严格 Pydantic schema 和安全 loader。
- [x] 实现只读 PostgreSQL dataset builder、12-case 类别平衡、qrel 存在性检查、snapshot commitment 与
      private-output 防误提交门禁。
- [x] 为 fixed-seed A/B 顺序、oracle isolation、registry equality、database drift 和隐私扫描补单元测试。

## Phase 2 — bounded paired runner

- [x] 复用现有 provider adapters，分别组合 plain/enhanced reader、相同 registry/model/limits，以及隔离的
      arm-local embedding cache。
- [x] 实现 capability budget、attempt journal、显式 live authorization、preflight-only 默认行为、无
      whole-suite retry 与安全失败账本。
- [x] 增加本地 Make/CLI 入口：preflight 不调用 provider，live 命令必须显式声明授权并绑定 manifest。

## Phase 3 — metrics and report

- [x] 实现 retrieval-sensitive 与 negative-control 分层评分、三次重复稳定性、端到端/分段延迟、usage、
      fallback/failure taxonomy 和逐 case bad-case 投影。
- [x] 实现固定 seed 的 10,000 次 case-level paired bootstrap，并在完整性不足、CI 跨零或未知 usage 时输出
      保守结论。
- [x] 生成 private 完整报告及可选 aggregate-safe 导出；所有 artifact 绑定 SHA，且不覆盖任何 canonical。

## Phase 4 — authorized execution and verification

- [x] 运行 provider-free focused tests、Ruff、strict mypy、相关既有 eval checks 与 `git diff --check`。
- [x] 执行一次不产生 provider 请求的 preflight，核对 12 cases、registry/model/provider、snapshot 和硬上限。
- [ ] 在已确认的 72-run 授权边界内执行一次真实 paired A/B；不因失败整套重跑，保留所有 attempts。
- [x] 复算报告、检查 artifact hashes/隐私/完整性，并明确 Seed、小样本、local-only 和 unknown cost 限制。
- [x] 最后检查 diff 只包含本任务文件；不触碰当前并行的 IP metadata/topic-selection 等未提交改动。

## Phase 5 — v2 canary-gated authorized revision

- [x] 将 Agent attempt 恢复为生产一致的四次模型决策/四次工具调用，并把全局 Agent decision 上限调整为
      288；Planner、Reranker、Alibaba Embedding 上限继续保持 108。
- [x] 新增 v2 schema/policy/authorization 身份、调度 ordinal 与 2-cell A/B 金丝雀；旧 v1 输出不可续跑
      或覆盖。
- [x] 只有两臂均通过终态、task、tool、argument、Top-3 target 全召回与引用完整性时才继续；否则写入
      `canary_failed` 和 incomplete/no-uplift 报告。
- [x] 增加连续四次系统性失败熔断、单次 executor fail-closed、报告/失败账本投影和 provider-free 回归。
- [x] 重新运行 focused tests、Ruff、targeted mypy 与 v2 provider-free preflight。
- [x] 仅在上述门禁通过后执行一次新授权 v2 live run；不得手工或静默重跑失败 cell。

## Phase 6 — Zhipu Agent compatibility repair

- [x] 为 OpenAI-compatible Agent 请求增加智谱官方 JSON mode；补全固定终答 JSON 契约，保持
      `AgentProposedAnswer`、tool arguments、unknown tool/call ID/citation 的严格校验不变。
- [x] 从既有 history 生成不含私有正文的确定性 next-action guidance：成功非空检索后优先终答，只有明确
      目标需要时才调用不同工具，禁止同类同义重搜和纯证据问题的无条件 `get_event`。
- [x] 使用 MockTransport/Recorded model 补齐 provider-free contract 与 runner regression，覆盖合法多工具、
      严格拒绝、token/trace 安全和既有精确调用 cache。
- [x] 运行 focused tests、Ruff、targeted strict mypy、Agent canonical、live-eval provider-free tests 与
      `git diff --check`，确认未触碰 Query Rewrite/RRF/Reranker/业务发布链路。
- [x] 新建 v3 compatibility authorization/output，最多执行一次 2-cell A/B canary；第二格后无条件停止，
      离线复算、隐私扫描并记录结果，绝不继续剩余 70 格。

## Validation commands

实际命令名在实现时按仓库现有 Make 命名规范确定，至少覆盖：

```bash
conda run --name edu-ai pytest backend/tests/unit/test_agent_retrieval_live_ab*.py -q --no-cov
conda run --name edu-ai pytest backend/tests/contract/test_agent_retrieval_live_ab*.py -q --no-cov
conda run --name edu-ai ruff check backend/evals/agent_retrieval_live_ab backend/tests
conda run --name edu-ai mypy backend/evals/agent_retrieval_live_ab
make agent-workbench-eval-check
make brand-retrieval-eval
git diff --check
```

## Rollback points

- 在 live flag 之前：只新增 provider-free harness，可直接删除新增 eval/test/Make 入口。
- dataset preflight 后：private dataset 只在 ignored output，不删除或修改数据库记录。
- live run 后：结果是不可变观察；失败不修改生产配置、不自动晋级 B、不自动写简历。
