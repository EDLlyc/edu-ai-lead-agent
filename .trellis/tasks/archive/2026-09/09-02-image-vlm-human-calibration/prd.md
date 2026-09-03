# 六源图片 GLM-5V-Turbo Judge 校准

## Goal

以 6 个独立公开 source families、48 个确定性派生 pair cases 和 objective anchors 盲测 `glm-5v-turbo`，量化六维质量、关键错误、偏置、稳定性、成本和失败案例，并明确结果不是 Human Gold。

## Dependencies

- 依赖父任务 provider-neutral contracts、one-shot transport、授权/预算/私有 I/O，并通过 version/SHA 显式绑定。
- 复用 `app.domain.image_quality_eval` 六维 taxonomy，但不覆盖 `backend/evals/image_quality/` canonical。
- 不依赖 Reviewer 子任务的实验结论；两条 track 使用不同 run ID、manifest、blind map、attempts 和 reports。

## Requirements

- `sources.v1.json` 只 allowlist 6 个独立 portfolio PNG families；记录 Git blob OID、SHA-256、MIME、dimensions、derivative relation 与用户明确的外部评测授权依据，不虚构许可证。
- 生成 48 个派生 pair cases（不是 48 个独立真实图片）：六维各 8，36 objective/12 subjective，24 calibration/24 untouched holdout；按 source family 分组切分，PNG/JPEG derivative 不得跨 split。
- Case 每臂支持 1–2 images 和 optional reference；batch diversity 使用四图分组，identity case 可使用 reference。HMAC 盲化并平衡 objective winner 在 A/B 的位置。
- Objective recipe 覆盖 semantic mismatch、IP identity corruption、exact visible-text mutation、blur/compression/artifact、crop/safe-area 和 duplicate-vs-diverse batch；hash-seeded Pillow recipe 可复现。
- 唯一识图模型是直连智谱 `glm-5v-turbo`；不调用 `glm-4.6v`、ToAPIs、Claude、Gemini、GPT 或其他视觉模型。Exact returned identity 不匹配即失败，无 fallback。
- 单模型执行 48 case AB/BA + 固定 12-case AB/BA repeat，即最多 120 calls。首个正式 call 是四图 diversity capability case；失败就停止其余计划并标记 incomplete，不另行 probe。
- Vote 必须同时输出 pair preference、A/B 各自 accept/reject/abstain、arm critical flags 和 arm issue codes；否则不得计算 FAR/FRR。
- Objective recipe gold 是唯一正确性依据。Subjective cases 没有外部标签，只报告 `glm-5v-turbo` 自身的 AB/BA position conflict、repeat consistency、coverage 和 abstention，不生成 proxy gold，不得称 consensus、agreement 或 Fleiss κ。
- 分别报告逐维 objective accuracy/macro-F1、critical FAR/FRR、position conflict、repeat consistency、coverage/abstention、latency、usage/cost 与 bad cases；禁止单一总分。
- 将 `IMAGE_QUALITY_AUDIT_MODEL` 默认值设为 `glm-5v-turbo` 并保持 factory 使用该独立字段；`IMAGE_QUALITY_EVAL_MODE` 默认仍 off，observe-only、ready/handoff 与历史回放不变。实验不复用生产单图 adapter，也不自动晋级候选。
- 私有 evidence 写入 `0700`/`0600` gitignored run dir；safe report 只含 aliases/hashes/closed labels/aggregates。

## Acceptance Criteria

- [x] Source preflight 证明 family n=6、授权依据、tracked/clean blob/content SHA 和 zero private paths。
- [x] Dataset 验证 48 derived cases、six dimensions、36/12、24/24、family-disjoint split、gold-position balance 与 recipe hashes。
- [x] Multi-image grouping、reference、AB/BA inverse、arm verdict、repeat identity 与单模型稳定性有确定性测试。
- [x] Preflight 显示 1*120<=120、first-case four-image capability gate、唯一 `glm-5v-turbo` pricing/auth identity，且不读取 `TOAPIS_API_KEY`。
- [x] Frozen pricing 的时区化有效期覆盖 execution window；live output 在读取密钥前由 safe store 新建并证明
      owner-only、gitignored、untracked 且为空，任何既有路径都拒绝复用。
- [x] Holdout 能复算 arm-level FAR/FRR；单模型 position/repeat 指标报告 eligible n/coverage，case n 与 effective source cluster n 分开。
- [x] `IMAGE_QUALITY_AUDIT_MODEL` 测试使用不同 chat/audit model 验证正确 wiring；default-off/canonical 无回归。
- [x] 最终只称 automated single-model calibration，不写人工/共识指标，不泄露素材，不自动生产晋级。

## Out of Scope

- 人工标注、人类一致率、多模型或单模型 proxy consensus/κ、把 48 cases 当 48 个独立样本、虚构图片许可证、向 ToAPIs 或其他模型发送图片、训练/微调、自动发布 gate、自动重生成或模型 fallback。
