# 评测 P0 可靠性门禁

## Goal

把现有七套 provider-free 评测收敛成一个明确、可复现、失败即阻断的 P0 质量门禁；修复当前选题重排评测中失真的优先级屏障案例，并把演示查询“小赛和赛先生在空间站”固化为 IP 检索回归样本。

用户价值是：任何排序策略、评测数据或 CI 配置变更都不能在评测漂移时被误判为通过，同时演示所依赖的关键检索意图具有版本化回归证据。

## Background and confirmed facts

- 仓库当前有七套独立评测：Agent Workbench、品牌文本检索、数字 IP 投影、图片质量、IP 资产检索、选题重排、品牌视觉检索。本任务提交后的 V4 基线共 186 个 provider-free case；并行 V5 工作树增加两个选题 case 后为 188 个。
- 2026-09-02 实际重跑结果为六套通过、`topic_rerank` 的 `priority-barrier` 失败；预期顺序 `[1, 2]`，当前顺序 `[2, 1]`。
- `backend/evals/topic_rerank/runner.py:55-57` 仍绑定 `MINISTRY_EDUCATION_PRIORITY_V4_RULE_VERSION`，而当前内容选择默认使用 `qualified-authoritative-priority-v1`。旧规则使 `priority-barrier` 的两个候选都成为 `priority_group=1`，因此案例名称与实际构造不一致。
- 使用当前 `QUALIFIED_AUTHORITATIVE_PRIORITY_RULE_VERSION` 运行同一 fixture，会得到候选组 `0` 和 `1`，可以真实验证模型分数不能跨越优先级屏障。
- `Makefile:175-191` 暴露了多数单项评测，但缺少统一 `eval-check`，也缺少独立的 checked Agent 与数字 IP Make 入口；`.PHONY` 还遗漏了 IP 资产检索评测。
- 云效质量阶段在 `deploy/yunxiao/pipeline.yaml:115-126` 运行 backend/release/frontend 等门禁，但没有显式运行全部七套评测。
- IP 检索评测是脱敏、provider-free 的冻结排名策略评测；新增演示查询只能证明数据契约与 V2/V3 排序回归，不能声称真实 Embedding 或线上检索效果。
- 工作区存在用户正在进行的 `topic-rerank-v5-multidimensional-scorecard` 改动。本任务必须在该现状上修复评测，不回退、覆盖或重新设计 V5 生产排序逻辑。

## Requirements

### R1. 修复并强化优先级屏障评测

- 选题评测必须使用当前内容选择的权威优先级规则，与 Compose/Settings 当前默认身份一致。
- `priority-barrier` 必须实际产生至少两个不同的 `priority_group`，并证明高分普通候选不能越过优先候选。
- 评测需要显式检查 priority fixture 的组分离，避免未来规则变化后出现“案例仍绿但屏障没有被测试”的假阳性。
- 修复后更新 topic-rerank canonical 报告只能反映真实策略输出；禁止仅修改预期顺序掩盖失败。
- 不改变生产评分权重、候选准入、V5 提示词、供应商适配器或最终排序实现。

### R2. 建立统一离线评测门禁

- 增加一个顶层 `make eval-check`，以 checked 模式运行全部七套评测：
  - `evals.agent_workbench.runner --check`
  - `evals.brand_retrieval.runner --check`
  - `evals.digital_ip.runner --check`
  - `evals.image_quality.runner --check`
  - `evals.ip_asset_retrieval.runner --check`
  - `evals.topic_rerank.runner --check`
  - `evals.visual_retrieval.runner --check`
- 任一子评测非零退出时，`eval-check` 必须非零退出；不能因后续命令成功而覆盖前序失败。
- 保留现有单项命令兼容性，补齐 checked Agent、数字 IP 和 `.PHONY` 声明。
- 统一门禁必须无网络、无 API key、无业务写入，不启动 live provider 或生产服务。
- 统一门禁必须能在只有 Git 跟踪文件的干净检出中运行，不得要求被忽略的
  `private/brand-materials/visual-assets.manifest.json` 或原始图片。

### R3. 固化演示检索意图

- 在 IP 资产检索 V3 脱敏数据集中增加精确查询“小赛和赛先生在空间站”。
- 样本必须表达双角色与空间站场景组合，并提供与现有 schema 一致的冻结 metadata/vector 排名和 evaluator-only relevance grade。
- 数据不得包含真实 asset/profile/user 身份、文件名、对象路径、图片字节或向量。
- 数据集加载/单元测试必须断言该精确查询存在，防止后续整理数据时无意删除演示回归。
- 有意增加数据集后，使用 runner 正常重建并审查 IP 检索 canonical JSON/Markdown。

### R4. 接入云效 CI

- 云效质量阶段在现有 backend gate 之后显式运行 `make PY_RUN="$PWD/scripts/ci-python.sh" eval-check`。
- release pipeline contract test 必须断言该命令存在，避免 CI 配置漂移后静默移除评测门禁。
- CI 继续使用固定 Python 容器、无 live AI 凭据和现有安全环境遮罩。

### R5. 文档与真实性边界

- README 的质量/评测入口列出统一 `make eval-check`，并说明它是 provider-free 回归门禁。
- 任何新增报告继续保留免责声明，不把 fixture 通过率描述为模型准确率或线上业务提升。

### R6. 将 Grounded Seed V2 纳入统一门禁

- 现有 `ip-asset-grounded-eval-check` 必须在 Seed V1 三项检查之后继续执行 Seed V2 的
  `authoring --check-v2`、`validate-seed-v2` 与 `check-v2-canonical`。
- 顶层 `make eval-check` 继续通过该子目标覆盖 Grounded Seed V1/V2；任意 V2 数据、schema、
  V1 继承身份或 canonical 漂移都必须使统一门禁非零退出。
- V2 接线保持 provider-free，不运行 live preflight、真实检索或模型调用。
- Grounded V1 在统一门禁中使用明确的 frozen-artifact 检查；依赖私有视觉清单的完整
  authoring 重建仍是显式本地检查，不能伪装成 CI 可复现检查。

## Acceptance Criteria

- [x] `topic_rerank` 当前已提交策略基线的全部 case 通过（本任务 V4 为 8/8；并行 V5 落地后由其任务提升到 10/10），`priority-barrier` 的候选组确实同时包含 `0` 和 `1`，最终顺序保持 `[1, 2]`。
- [x] 单元测试能在 priority fixture 再次退化为同一组时失败，而不是仅检查最终顺序。
- [x] IP 检索数据集包含精确查询“小赛和赛先生在空间站”，总 case 数不少于 41，canonical check 通过。
- [x] `make eval-check` checked 运行七套评测并全部通过；人为让任一子命令失败时，Make 目标的失败传播由结构或测试证明。
- [x] 云效 pipeline 显式调用 `eval-check`，release pipeline contract test 覆盖该命令。
- [x] `make ip-asset-grounded-eval-check` 与 `make eval-check` 均执行三项 Seed V2 检查，且
      124 条查询、30 条无答案、5,084 个判断的冻结契约通过。
- [x] 从 Git index/干净检出导出的、不含私有视觉清单的快照可以运行完整 `make eval-check`。
- [x] 任务相关 Ruff、Mypy、focused Pytest、canonical drift 和 `git diff --check` 全部通过。
- [x] 没有 live provider 调用、数据库迁移、生产数据写入或生产部署。

## Key Decisions

- P0 只强化确定性回归和 CI 门禁；真实模型、人类 Gold Set 和线上统计属于后续阶段。
- 修复 priority fixture 的策略身份与断言，不改写 V5 生产排序逻辑，也不把错误输出提升为新基线。
- 演示查询进入现有脱敏 IP 检索数据集，作为排序策略回归；不伪装成端到端多模态模型评测。
- 所有 CI 评测保持 provider-free，以保证 PR 可复现、无成本且不依赖第三方可用性。

## Out of Scope

- 建立 100--200 张图片或 50--100 条真实搜索的人工 Gold Set。
- 启用 `IMAGE_QUALITY_EVAL_MODE=observe|gate`，执行付费 VLM/OCR/Embedding 调用。
- 新增公众号文章事实性、品牌语气或移动端截图质量评测。
- 建立线上 A/B、统计显著性、成本看板或匿名搜索指标仪表盘。
- 修改生产选题算法、RRF 权重、Embedding 模型或业务数据库 schema。
- 提交、推送或部署现有工作区中的其他用户改动。

## Risks and deferred items

- 当前 topic-rerank V5 仍属于另一个进行中的任务；实施必须只做评测规则身份和 fixture 真实性修复，避免混入该任务的生产代码。
- IP 检索新增 case 会有意改变 dataset hash 和聚合指标，canonical 更新必须通过差异审查而不是机械覆盖。
- 将七套评测显式加入 CI 会增加少量耗时，但它们均为 provider-free，当前本地合计运行约数秒，收益高于成本。
- 人工标定、live model paired eval、置信区间和业务指标仍是形成真实效果证据所必需的 P1/P2 工作。
