# 六源图片 Model-Panel Proxy：技术设计

## Boundary

新建 `backend/evals/image_quality_panel/`，只复用现有六维 taxonomy，不覆盖 provider-free canonical。
实验 multi-image transport 与生产 single-image auditor 分离：前者要求严格 one-shot、usage/cost 和最多四图；
后者保持现有 observe-only 语义。生产只新增独立视觉模型配置，mode 默认仍 off。

## Sources, rights and deterministic dataset

`sources.v1.json` 记录 6 个独立 portfolio PNG source families。四个 JPEG publication derivatives 必须用
`derivative_of` 归回对应 family，不能增加有效样本数。每项包括 repository path、Git blob OID、content SHA、
MIME/dimensions、family 和
`external_model_use_basis=project_owner_authorized_external_evaluation_2026-09-02`；不添加未经证明的 SPDX。

Preflight 必须验证 source 已 tracked、working tree bytes 与 blob/content SHA 一致、授权字段存在、路径不在
`private/`，否则 fail closed。只使用 hash-seeded stdlib 与 pinned Pillow 生成 recipes，避免无 seed noise 和
依赖系统 CJK font。可见文字 case 通过已有图片的确定性区域 mutation/crop 创建。

48 pair cases 按六维各 8，36 objective + 12 subjective；24 calibration + 24 untouched holdout。Split 以
source family 为 group，所有 derivatives 同 split。报告 `case_n=48`、`source_family_n=6` 和每项 family-cluster
bootstrap/限制，绝不声称 48 independent images。

## Case, blinding and judge output

`ImagePanelCase`：

- arm_0 / arm_1 各 1–2 `ArtifactReference`，可选 reference artifact；
- dimension、gold kind、objective arm decisions/critical flags、source family、split、recipe version/SHA；
- run-scoped HMAC blind map 和 A/B gold-position balance；图片 grouping/order 均进入 request fingerprint。

batch diversity 使用 A 两图 vs B 两图，没有 reference；IP identity 可使用 reference + A/B candidates，总数 3。
第一条正式 case 固定为四图 diversity，用作模型能力 gate，但计入 120-call plan，不增加额外 probe。

图片 judge 严格输出 pair choice，以及 `a_decision`、`b_decision`、`a_critical`、`b_critical`、A/B issue codes、
confidence。BA 输出解盲时必须同时交换 pair choice 与所有 arm-scoped fields。只有 AB/BA 完全等价才进入 panel
consensus或 candidate score。

## Execution and metrics

五个模型各执行 `48*2 + 12*2 = 120` calls。首个四图 request 发生 capability/identity/schema failure 时，
停止该模型其余计划并标记 incomplete；不探测第二模型、不 fallback、不静默重试。

Objective metrics 直接对 recipe gold 计算 pair accuracy、arm decision macro-F1、critical FAR/FRR；subjective
metrics 只对至少两个 order-consistent panel 的共识计算 candidate agreement。Fleiss κ 只在三 panel 完整一致
子集计算，报告 eligible case count/total/coverage；position/repeat conflict、abstention 和 failure 都保留分母。

逐维输出 metrics/confusion、P50/P95 latency、known/unknown usage/native cost 与 bad-case aliases，不汇总成会
抵消 critical failure 的总分。Calibration 可调 prompt/rubric；holdout 解盲后任何调整都要升版本并新 run。

## Production compatibility

`image_quality_audit_model` 默认 `glm-4.6v`，factory 明确传该字段而不是 `ai_chat_model`。测试把两字段设置为
不同值，确保视觉 identity 不再被文本默认值掩盖。Mode off 时无调用/记录/fingerprint 变化；observe 仍非阻断，
历史 evidence 按其存储 identity/version 回放。实验结果只产生 non-activating candidate artifact。

## Rollback

移除新 live package和 additive setting/factory hunk即可；无数据库迁移、canonical rewrite、生产 gate、私有素材
提交或发布状态变更。
