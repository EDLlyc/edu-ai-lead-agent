# 六源图片 GLM-5V-Turbo 盲测：技术设计

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
source family 为 group，所有 derivatives 同 split。报告 `case_n=48`、`source_family_n=6` 和
`effective_source_cluster_n=6`。因为独立 cluster 只有 6 个，不输出伪精确的 family-cluster bootstrap CI；
仅报告点估计、覆盖率和这一不确定性限制，绝不声称 48 independent images。

## Case, blinding and judge output

`ImagePanelCase`：

- arm_0 / arm_1 各 1–2 `ArtifactReference`，可选 reference artifact；
- dimension、gold kind、objective arm decisions/critical flags、source family、split、recipe version/SHA；
- run-scoped HMAC blind map 和 A/B gold-position balance；图片 grouping/order 均进入 request fingerprint。

batch diversity 使用 A 两图 vs B 两图，没有 reference；IP identity 可使用 reference + A/B candidates，总数 3。
第一条正式 case 固定为四图 diversity，用作模型能力 gate，但计入 120-call plan，不增加额外 probe。

图片 judge 严格输出 pair choice，以及 `a_decision`、`b_decision`、`a_critical`、`b_critical`、A/B issue codes、
confidence。BA 输出解盲时必须同时交换 pair choice 与所有 arm-scoped fields。只有 AB/BA 完全等价才进入
objective score 或 subjective stability coverage。

## Execution and metrics

唯一的 `glm-5v-turbo` 执行 `48*2 + 12*2 = 120` calls，总上限 120。
只走智谱直连；不得构造 ToAPIs 或 `glm-4.6v` transport，也不得读取 `TOAPIS_API_KEY`。首个四图 request 发生 capability/identity/schema failure 时，
停止其余计划并标记 incomplete；不探测其他模型、不 fallback、不静默重试。

智谱视觉请求使用冻结的 `zhipu-vision-v1` 方言：保留 OpenAI-compatible 的 system/user
multi-image messages，但不发送仅文本模型支持的 `response_format`；固定发送
`thinking={"type":"disabled"}` 与 `do_sample=false`，且不接受任意 provider options。共享 transport 的
默认 `json-object-v1` 方言保持不变，Reviewer 等既有调用继续发送 `response_format=json_object`。
成功 HTTP 响应的 envelope/choices/usage 解析失败记录为 `provider_envelope_invalid`。只对冻结的
`zhipu-vision-v1` response boundary 去除外围空白，并允许一个独立、无 prose、无第二对象/围栏的 lowercase
`json` Markdown fence；随后仍走 duplicate-key rejecting exact-object parser、strict vote schema、arm
invariant 和 request-scoped issue-code allowlist。失败分别记录为
`judge_content_framing_invalid`、`judge_content_schema_invalid`、
`judge_content_policy_invalid`。Reviewer/default JSON profile 不做上述 normalization，继续要求 exact JSON。
旧证据中的 `judge_content_invalid` 与 `invalid_provider_output` 仍可回放；所有记录都只持久化闭集 code，不持久化
raw body、prompt 或解释。

图片 arm 输出的 exact keys 与不变量写入 v2 prompt：accept 必须 `critical=false` 且 issues 为空；reject 必须
给出 boolean critical 和至少一个 allowed issue；abstain 必须 `critical=null` 且 issues 为空；所有 issue
arrays 必须唯一、字典序排序且在 request allowlist 中。该 prompt/transport 变更分别提升 image prompt 与
adapter 版本，任何旧 manifest/authorization 不得复用。

应用层 live composition 只读取已有的 `AI_PLATFORM_API_KEY`。source、derived dataset、
manifest、authorization、requests、pricing 的 schema/hash/binding 以及 private run directory 必须全部通过后才
读取密钥；provider-free runner 的 `live` 永远 fail closed。定价只能来自 operator 提供并审核的 self-hashed
Zhipu-only snapshot，不内置或猜测任何费率。snapshot 的时区化有效期必须覆盖整个 frozen execution window。live output
directory 必须尚不存在，并由 safe store 原子创建为 owner-only、gitignored、untracked 的空目录；任何既有路径都
在读取密钥前拒绝，禁止把一次中断或已完成的计划静默重跑。

Objective metrics 直接对 recipe gold 计算 pair accuracy、arm decision macro-F1、critical FAR/FRR。Subjective
cases 不产生正确性或 proxy label，只测同一个 `glm-5v-turbo` 的 AB/BA position conflict、固定 repeat
consistency、coverage 和 abstention。报告必须显式写 `single_model_only=true`、`external_label_n=0`，不得
输出 consensus、target-to-proxy agreement 或 Fleiss κ；所有 failure 都保留分母。

逐维输出 metrics/confusion、P50/P95 latency、known/unknown usage/native cost 与 bad-case aliases，不汇总成会
抵消 critical failure 的总分。Calibration 可调 prompt/rubric；holdout 解盲后任何调整都要升版本并新 run。

## Production compatibility

`image_quality_audit_model` 默认 `glm-5v-turbo`，factory 明确传该字段而不是 `ai_chat_model`。测试把两字段设置为
不同值，确保视觉 identity 不再被文本默认值掩盖。生产单图 quality auditor 同样使用封闭的
`zhipu-vision-v1` 请求方言；OCR 的既有 JSON-object 方言不变。Mode off 时无调用/记录/fingerprint 变化；observe 仍非阻断，
历史 evidence 按其存储 identity/version 回放。实验结果只产生 non-activating candidate artifact。

## Rollback

移除新 live package和 additive setting/factory hunk即可；无数据库迁移、canonical rewrite、生产 gate、私有素材
提交或发布状态变更。
