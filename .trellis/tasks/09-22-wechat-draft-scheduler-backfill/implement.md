# 9 月 21 日单篇草稿补建与自动化修复实施计划

当前执行边界：Phase 1–3 的真实未发布草稿已完成回查与幂等证明；用户已确认推进 Phase 4–5 的永久修复和服务器部署。使用隔离 worktree 构建不可变候选，完成检查后部署并验收下一计划窗口。

## Phase 1 — 锁定证据与隔离实现基线

- [x] 从 release-hardening `720305b...` 创建隔离实现 worktree，不触碰根目录和现有未跟踪文件。
- [x] 采集两次稳定只读生产基线，确认 9 月 21 日唯一目标、第 0 slot 三次 unknown（503/timeout/timeout）、Article/render/owner/journal/草稿无冲突。
- [x] 将 release marker、镜像、schema 0048、运行开关和下一个计划日写入隐私安全 evidence。
- [x] 冻结三次 unknown 证据、五个新 recovery visual identity 与五张 Article 已选品牌素材；确认补建最多新增五次图片调用且旧请求绝不重放。

## Phase 2 — Exact-target backfill 与幂等对账

- [x] 通过现有 private journal/checkpoint 新增 operator-owned backfill 持久化状态，不为一次性补建新增 schema；保持普通 single-edition no-backfill 语义。
- [x] 实现默认只读 plan、显式 `--apply`、稳定目标/授权 fingerprint、短时截止、lease/fencing 和重复执行复用。
- [x] 复用目标 Article/render；在 exact-target 跨日授权下，为五个 slot 建立新的 stable request identity、intent-before-call 与每 slot 一次/整篇五次上限；旧 V3 unknown 尝试保持不可变。
- [x] 实现 all-or-nothing 视觉选择：五张新图全部通过才进入 generated prepared contract；任一失败/unknown 立即停止后续调用，并用五张 checksum-bound 品牌素材构建 versioned approved-catalog-fallback contract，明确记录非模型生成来源。
- [x] 复用 persistent manual journal 和 draft-only client，实现媒体与 `draft/add` intent/ACK、unknown no-replay。
- [x] ACK 后实现官方只读回查与数据库/owner 对账；从 journal ACK 恢复对账时不得再次调用微信。
- [ ] 覆盖错误目标、状态漂移、并发 apply、过期、五图全成功、任一 provider failure/unknown 后停止并整套兜底、微信 failure/unknown、ACK 后 DB crash 和二次执行。

## Phase 3 — 先补建 9 月 21 日真实草稿

- [x] 将 exact-target operator 打成独立、哈希固定、默认 plan 的 transient 包；不得修改生产运行镜像或常驻配置。
- [x] 在生产 deployment lock 下复核 protected config、journal、队列、lease、目标和素材不变性。
- [x] 运行 plan 并独立复核；全门禁通过后仅执行一次生图 apply 与一次产生微信副作用的 delivery apply；回读对账恢复只复用既有 ACK。
- [x] 通过 journal ACK、官方只读回查、数据库 receipt/owner 和无发布状态证明草稿创建。
- [x] 重复运行 operator，证明已消费的新生图 intent 不会重放、无第二次媒体上传或 `draft/add`，且总图片 provider 调用不超过五次。
- [x] 为胸牌修正建立独立的 generation-only operator：冻结原五个视觉位置与 `720305b...` 胸牌提示词，使用新 namespace/identity，每位置一次、总计最多五次，并从依赖边界排除微信 client 与数据库写入。
- [x] 使用 fake provider 覆盖五个新 intent、重复执行不重放、调用上限、结果内容寻址、提示词胸牌硬约束和零微信/零数据库副作用；完成 lint、type-check 和禁网导入检查。
- [x] 在生产 deployment lock 下用当前图片运行时执行一次 generation-only apply；导出五张结果逐张检查蓝底白字 `AI`，本轮不更新公众号草稿。任一张未通过时停止并等待用户决定。
- [x] 实现 exact-target 同草稿 replacement operator：从补建 journal 绑定原草稿，读取胸牌 selection/MinIO 五图，默认只读 plan；apply 仅允许五次 journaled inline upload 与一次 journaled `draft/update`，排除 `draft/add`、发布、删除和数据库写入。
- [x] 覆盖草稿/账号/原正文/图片哈希漂移、五图顺序替换、upload/update unknown no-replay、官方回查、重复 apply 零新增写入；完成 lint、type-check、禁网生产兼容和独立检查。
- [x] 同草稿 replacement 在只读预检确认原稿已发布后安全停止；该 apply 按 D9 取消，改由以下独立 redraft 流程完成用户目标，没有发起 `draft/update`。
- [x] 实现 exact-target published-to-redraft operator：只读定位唯一发布记录并冻结文章，读取五张已验收胸牌图；默认 plan，apply 仅允许五次 journaled inline upload 和一次 journaled `draft/add`，排除 update/publish/delete/数据库写入。
- [x] 覆盖发布记录歧义/漂移、候选哈希漂移、七图与非图片字段保持、upload/add unknown no-replay、batchget 唯一对账、官方 draft/get、重复 apply 零写入；完成 lint、type-check、禁网生产兼容和独立检查。
- [x] 在 deployment lock 和 draft-only runtime 中运行 plan 后一次 apply；官方回查新草稿未发布且唯一，原发布记录不变，再次执行证明无第二篇草稿。

## Phase 4 — 前向候选与发布门禁

- [x] 实现 V4 tolerant geometry 的新运行支持，保留三次有界物理尝试和全部非几何硬门禁；实际启用由部署修改唯一策略配置，显式 V3 仍受尊重。
- [x] 为三次耗尽/unknown 增加自动 approved-catalog fallback；不得发第四个图片请求，且不得把 fallback 记录成模型生成成功。
- [x] 将 migration compatibility/health 声明与实际 schema `20260916_0048` 对齐。
- [x] 为单篇 scheduler/producer/consumer、legacy 互斥、next-due 和 target backfill 增加安全只读状态命令。
- [x] 运行 focused unit/integration/operator/release tests、strict mypy、Ruff、Compose config、diff 和 Trellis validation；完整 suite 的 27 项历史失败及基线同矩阵对照见 forward-validation，不宣称全量通过。
- [ ] 独立检查通过后构建不可变镜像/manifest/operator，并记录哈希与前向恢复步骤。

## Phase 5 — 生产部署和前向自动化验收

- [ ] 在 deployment lock 下复核 protected config、备份、数据库/对象存储/journal、队列和 lease。
- [ ] 部署候选并验证 release/image/schema、12+2 服务、API、模式开关、重启计数和日志安全。
- [ ] 验证下一个 M/W/F 计划窗口、普通 scheduler 不回放历史日期、fallback 路径可观测，并保存隐私安全 activation receipt。

## Focused validation

```bash
PYTHONPATH=backend pytest -q --no-cov \
  backend/tests/unit/test_official_account_single_backfill.py \
  backend/tests/integration/test_official_account_single_backfill.py \
  backend/tests/unit/test_official_account_strict_visual_policy.py \
  backend/tests/integration/test_official_account_strict_visual.py

PYTHONPATH=backend mypy --config-file backend/pyproject.toml \
  backend/app/application \
  backend/app/infrastructure/db/official_account_single_backfill.py

ruff check backend/app backend/tests
docker compose --profile official-account-weekly-dag \
  --profile wechat-official-account-draft config --quiet
git diff --check
python3 ./.trellis/scripts/task.py validate \
  .trellis/tasks/09-22-wechat-draft-scheduler-backfill
```

## Review gates

- 本次补建最多调用图片模型五次；任何模型或微信调用之前，exact target、旧失败 ledger、新 request identity、五张 fallback 素材、内容指纹、owner、journal、账号和 deadline 全部冻结并复核。
- 只有 `draft/add`，没有 publish/mass-send/delete/update；人工审核保持可选后置步骤。
- 历史普通 scheduler 仍然 no-backfill；补建权限不能泛化为日期范围或任意 run 参数。
- 生产健康检查必须按 0048 通过，不能靠忽略 schema mismatch 验收。
- 成功标准是官方回查到一个未发布草稿，不是容器健康、图片生成完成或网页显示“草稿已创建”。
