# Design: 评测 P0 可靠性门禁

## 1. Architecture and boundaries

本任务不增加新的评测框架。它把现有 runner 组合成一个显式 CI gate，并修复两个确定性数据契约：选题 priority fixture 和 IP 演示查询。

```text
versioned eval datasets
        ↓
seven existing provider-free runners --check
        ↓
Makefile eval-check
        ↓
Yunxiao quality stage
        ↓
non-zero drift blocks candidate
```

生产 API、数据库、Worker、模型适配器和业务排序不在此链路中。

## 2. Topic priority fixture repair

`topic_rerank.runner.CONFIG` 应绑定当前 `QUALIFIED_AUTHORITATIVE_PRIORITY_RULE_VERSION`。这与生产内容选择的当前默认值一致，并让 priority case 的显式政策候选进入 group 0，普通候选进入 group 1。

评测在已有 `priority_barrier` check 中增加 fixture 有效性条件：

- 非 priority 场景维持现有行为；
- priority 场景必须观察到至少两个不同 group；
- final groups 必须单调不降；
- 预期最终 suffix 仍为 `[1, 2]`。

这样规则身份再次漂移时，评测会以 fixture-invalid/priority check 失败，而不是因为两个相同 group 恰好排序正确而假通过。

Canonical 报告通过现有显式 `--write-canonical` 流程更新，随后 `--check` 字节级校验。

## 3. Unified Make gate

保留 `agent-workbench-eval` 的现有非 checked/诊断用途，新增 checked 入口，并补齐数字 IP：

```make
agent-workbench-eval-check
digital-ip-eval
eval-check
```

`eval-check` 以 Make prerequisites 或逐行 recipe 组合七个 checked 目标。普通 `make` 在首个非零目标处失败；不使用一个无 `set -e` 的 shell loop，避免最后一个成功命令覆盖前序失败。

所有目标继续通过可覆盖的 `PY_RUN` 执行，以兼容本地 Conda 与 CI 的固定容器 wrapper。

Grounded retrieval 作为同一统一门禁中的 provider-free 数据契约目标，按顺序检查 Seed V1
与 Seed V2。Seed V1 的首项使用专门的 frozen-artifact CLI 模式，只验证 Git 跟踪的资产
快照 hash 以及可重建的查询/判断字节，不读取私有视觉清单；原有 `authoring --check` 保留给
具备私有清单的显式本地完整重建。Seed V2 在现有子目标内追加三条独立 recipe：`authoring --check-v2`、
`runner validate-seed-v2`、`runner check-v2-canonical`。Make 会在任一命令失败时停止；live
preflight、真实 provider run 和运行产物报告不进入 CI。

## 4. IP demo query fixture

在 `ip_asset_retrieval/cases.v1.jsonl` 增加一个脱敏 case：

- query：`小赛和赛先生在空间站`
- category：组合过滤/场景类现有枚举之一，以当前 schema 为准；
- candidates：使用安全 synthetic keys，至少包含双角色空间站相关项、单角色或错误场景近邻以及无关项；
- observations：冻结 metadata rank、vector rank 和 evaluator-only relevance grade；
- V3 预期维持 exact metadata evidence 优先，同时让语义 lane 改善组合意图排序。

数据加载测试新增精确 query 存在断言。评分仍调用生产 domain selector，relevance grade 只进入 evaluator。

## 5. CI wiring and contract

在云效 `quality_checks` 中，`backend-check` 后增加：

```bash
make PY_RUN="$PWD/scripts/ci-python.sh" eval-check
```

`deploy/release/tests/test_pipeline_contract.py` 对该精确命令做字符串契约断言。CI 已经使用 `set -Eeuo pipefail`，因此 gate 非零会立即终止质量阶段。

## 6. Compatibility and rollback

- 无数据库迁移、API schema 或生产配置变化。
- 单项 Make 目标继续存在；回滚统一 gate 只涉及 Makefile/pipeline，但不应回滚新增的真实性断言，除非同时恢复旧生产优先级策略。
- IP canonical hash 的变化是有意的数据集版本结果；Git 回滚相关 case 和 canonical 文件即可恢复。
- 不触碰用户正在开发的 topic-rerank V5 生产模块。

## 7. Validation strategy

- 直接运行全部七套 `--check`。
- 运行 topic-rerank 和 IP retrieval evaluator unit tests。
- 运行 pipeline contract test。
- 对任务涉及 Python 文件运行 Ruff/Mypy；对 Make/YAML/JSONL/Markdown 运行格式或解析检查。
- 最后运行 `git diff --check` 并审查 canonical metric/hash 差异。
