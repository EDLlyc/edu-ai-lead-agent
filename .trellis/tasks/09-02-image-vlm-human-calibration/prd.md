# 六源图片 Model-Panel Proxy 与 VLM Judge 校准

## Goal

以 6 个独立公开 source families、48 个确定性派生 pair cases、objective anchors 和异构模型盲评团评估两个智谱 VLM Judge，量化六维质量、关键错误、偏置、稳定性、成本和失败案例，并明确结果不是 Human Gold。

## Dependencies

- 依赖父任务 provider-neutral contracts、one-shot transport、授权/预算/私有 I/O，并通过 version/SHA 显式绑定。
- 复用 `app.domain.image_quality_eval` 六维 taxonomy，但不覆盖 `backend/evals/image_quality/` canonical。
- 不依赖 Reviewer 子任务的实验结论；两条 track 使用不同 run ID、manifest、blind map、attempts 和 reports。

## Requirements

- `sources.v1.json` 只 allowlist 6 个独立 portfolio PNG families；记录 Git blob OID、SHA-256、MIME、dimensions、derivative relation 与用户明确的外部评测授权依据，不虚构许可证。
- 生成 48 个派生 pair cases（不是 48 个独立真实图片）：六维各 8，36 objective/12 subjective，24 calibration/24 untouched holdout；按 source family 分组切分，PNG/JPEG derivative 不得跨 split。
- Case 每臂支持 1–2 images 和 optional reference；batch diversity 使用四图分组，identity case 可使用 reference。HMAC 盲化并平衡 objective winner 在 A/B 的位置。
- Objective recipe 覆盖 semantic mismatch、IP identity corruption、exact visible-text mutation、blur/compression/artifact、crop/safe-area 和 duplicate-vs-diverse batch；hash-seeded Pillow recipe 可复现。
- Panel 为 `gpt-5.6-terra`、`gemini-3.7-flash`、`claude-sonnet-5`；候选为直连智谱 `glm-4.6v`、`glm-5v-turbo`，exact returned identity 不匹配即失败，无 fallback。
- 五模型均做 48 case AB/BA + 固定 12-case AB/BA repeat，即每模型 120、最多 600 calls。每模型首个正式 call 是四图 diversity capability case；失败就停止该模型计划并标记 incomplete，不另行 probe。
- Vote 必须同时输出 pair preference、A/B 各自 accept/reject/abstain、arm critical flags 和 arm issue codes；否则不得计算 FAR/FRR。
- Panel consensus 排除两个 target candidates；至少两个 order-consistent panel 才 resolve。Fleiss κ 只在三 panel 完整且 order-consistent 的交集计算，并报告 κ coverage。
- 分别报告逐维 objective accuracy/macro-F1、critical FAR/FRR、panel agreement/κ、target-to-panel agreement、position conflict、repeat consistency、coverage/abstention、latency、usage/cost 与 bad cases；禁止单一总分。
- 新增 `IMAGE_QUALITY_AUDIT_MODEL=glm-4.6v` 并修正 factory；`IMAGE_QUALITY_EVAL_MODE` 默认仍 off，observe-only、ready/handoff 与历史回放不变。实验不复用生产单图 adapter，也不自动晋级候选。
- 私有 evidence 写入 `0700`/`0600` gitignored run dir；safe report 只含 aliases/hashes/closed labels/aggregates。

## Acceptance Criteria

- [ ] Source preflight 证明 family n=6、授权依据、tracked/clean blob/content SHA 和 zero private paths。
- [ ] Dataset 验证 48 derived cases、six dimensions、36/12、24/24、family-disjoint split、gold-position balance 与 recipe hashes。
- [ ] Multi-image grouping、reference、AB/BA inverse、arm verdict、repeat identity、target exclusion/quorum 有确定性测试。
- [ ] Preflight 显示 5*120<=600、first-case four-image capability gate、模型/pricing/auth identities。
- [ ] Holdout 能复算 arm-level FAR/FRR；κ 同时报告 eligible n/coverage，case n 与 effective source cluster n 分开。
- [ ] `IMAGE_QUALITY_AUDIT_MODEL` 测试使用不同 chat/audit model 验证正确 wiring；default-off/canonical 无回归。
- [ ] 最终只称 automated/model-panel calibration，不写人工指标，不泄露素材，不自动生产晋级。

## Out of Scope

- 人工标注、人类一致率、把 48 cases 当 48 个独立样本、虚构图片许可证、私有 IP 原图跨网关分发、训练/微调、自动发布 gate、自动重生成或模型 fallback。
