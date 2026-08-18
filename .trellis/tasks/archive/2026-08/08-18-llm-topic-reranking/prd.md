# LLM 选题重排

## Goal

在现有可信证据、硬否决、0.59 阈值和确定性排序之后，增加一层可审计的 LLM 候选重排，让系统能综合判断传播价值、信息增量、时效性、栏目适配度和洞察空间，再决定每日 Top 1 或时段内 1--3 条内容的优先顺序。

该能力必须是“规则守门、LLM 排序”，不能让模型改变事实资格、抬高低分新闻、绕过近期重复或其他安全规则；模型不可用时，业务自动回退到当前确定性顺序。

## Background and Confirmed Facts

- 当前默认选题配置为 `scoring-v1-preview.8-threshold-059`，普通候选阈值为 0.59；历史 `.4`--`.7` 配置必须继续按原快照回放，见 `backend/app/domain/topic_selection.py` 与 `.trellis/spec/backend/topic-selection.md`。
- `select_daily_topic()` 当前对最多 500 个治理事件计算规则分数，按部委优先、资格、总分、来源可信度、时间和 UUID 稳定排序，并选择第一个合格项。
- 硬否决包括治理未解决、证据不合格、Tier C only、未验证、安全/隐私/营销风险、十天外陈旧事件以及七天内已正式成功推送的同一事件。模型不能覆盖这些结果。
- 当前七天重复窗口读取正式 `WeComDeliveryJob(mode=formal,status=delivered)` 的类型化谱系；“仅入选但未成功推送”不会触发 `.8` 硬重复否决。
- 内容时段模式在当前配置中默认关闭，但代码支持早/中/晚并行路径；它在相同基础资格之上增加时段 affinity、同日排除和 1--3 条上限。共享能力必须避免每日路径和时段路径产生相反语义。
- 现有 Zhipu OpenAI-compatible adapter 已具备 HTTPS 边界、超时、并发、有限重试、JSON object、Pydantic 校验、usage 和安全 request fingerprint 模式，可复用传输规范但不能复用事实分析的业务 schema。
- 当前 topic run 在入队时锁定评分配置和 cutoff；新增重排配置也必须在入队时锁定，不能让排队中的任务读取后来变更的进程设置。
- 当前 `topic_scores` / `content_slot_scores` 持久化最终 rank 与 explanation，但没有独立的重排配置、请求候选、模型结果、失败降级和 token/latency 审计记录。
- 工作区存在本任务之外的报告和另一个未跟踪任务目录；实现必须保留且不得纳入本任务提交。

## Requirements

### R1. 两阶段资格与排序

- 第一阶段继续使用现有 `.8` 确定性评分、0.59 阈值、部委优先认证、同日排除和全部硬否决。
- LLM 只接收已经合格、且在时段路径中未被同日排除的候选；低于阈值但不具备受控部委 bypass 的候选、被 veto 的候选和时段同日重复候选不得进入模型排序池。
- 部委优先组与普通合格组之间的顺序是硬边界。LLM 可以在同一组内调整顺序，不能把普通候选排到受控优先候选之前。
- 每日路径最终选择 Top 1；时段路径继续遵守原有 `max_items` 1--3 和 slot affinity，只改变同一合格组内的优先顺序。
- LLM 不具有 `no_topic` 或救回候选的权限。没有合格候选时沿用现有 `no_topic`；只有一个可排序候选时直接选择并跳过 provider。

### R2. 有界、结构化的 LLM 重排

- 每次最多向模型提供确定性顺序最靠前的 8 个合格候选，其余合格候选继续按确定性顺序接在重排池之后。
- 输入只使用固定 cutoff 下治理后的候选 ID、版本 ID、有界标题/摘要、事件时间、规则总分、来源/编辑/产品方向/风险投影，以及可选时段 affinity；不发送整篇原文、私有路径、密钥或品牌内容作为事实。
- 排序维度固定为传播价值、信息增量、时效性、AI/教育受众相关性、“小赛洞察”栏目适配度、洞察空间和主题多样性。
- 模型必须返回输入候选的完整排列、每项 1--3 个受控 reason code 和一段有界简短理由。缺失、重复、未知 ID、跨越优先组、额外字段或超长内容均视为无效输出。
- 模型不得生成新事实、改写规则分数或输出一个不可解释的替代总分。

### R3. 确定性降级与开关

- 新能力通过独立设置显式开启，默认关闭；关闭时每日与时段选择必须与现有行为完全一致。
- provider disabled、超时、HTTP/解析错误、无效排列、输入超限或模型异常时，任务仍按原确定性排序成功完成，并持久化安全、稳定的 fallback code。
- 传输层可以使用现有有限重试策略，但一次业务执行只发起一个逻辑重排请求；不增加无界重试或第二个“评委模型”。
- fake 模式必须 provider-free 且确定性，用于测试和本地演示；本任务不调用真实模型。

### R4. 不可变配置与审计

- 每日 run 和时段 run 在入队时锁定 versioned rerank config snapshot/fingerprint，至少包含 enabled、policy version、候选上限、provider、model、temperature、输出上限和 fallback 策略。
- 持久化一次类型化重排记录，绑定每日 run 或时段 run，记录输入候选顺序、最终顺序、理由、outcome、failure code、prompt/request fingerprint、provider/model、token usage 和 latency。
- 最终 score 保留确定性基础 rank 与 LLM 最终 rank；规则 total、threshold、eligibility、veto、priority、slot affinity 和 same-day exclusion 保持原值。
- API 返回安全的重排摘要与每个候选的基础/最终顺序和理由；不得暴露 provider 原始响应、Authorization、私有 prompt 或内部路径。
- 历史没有重排数据的 run 仍能读取；字面 `.4`--`.8` 评分快照继续可反序列化，不因新增设置被重新解释。

### R5. 一致的数据流

- 每日 TopicSelectionExecutor 和 ContentSlotExecutor 复用同一个 reranker port、请求/结果 schema、输出 validator 和 fallback service，不复制两套模型协议。
- 数据库会话不得跨 provider 网络调用保持打开；先读取不可变候选投影，关闭读取会话，再调用模型，最后在原有 lease/事务边界内原子持久化决策与重排记录。
- lease 丢失时不得覆盖已有决策。崩溃发生在 provider 返回但持久化之前时，允许后续 bounded job retry 产生同 fingerprint 的再次调用，但系统不得声称 provider exactly-once。

### R6. 测试与评测

- 纯 domain/unit 测试覆盖硬否决、0.59 阈值、部委优先组、候选上限、0/1 候选跳过、合法重排、非法排列和确定性 fallback。
- fake/model adapter 测试覆盖严格 JSON、未知/重复/缺失 ID、超长理由、输入 prompt injection 文本隔离、usage/latency 和 provider 错误映射。
- PostgreSQL 集成测试覆盖入队时配置快照、每日/时段结果原子持久化、历史无重排兼容、lease loss 和 fallback 记录。
- provider-free fixture eval 至少覆盖每日与早/中/晚、优先组、硬否决、同日排除和 fallback；报告只声明 contract conformance，不宣传真实模型排序准确率。
- OpenAPI、生成前端类型、Compose 渲染、Ruff、mypy、相关 pytest 和 diff/secret 检查通过。

### R7. 实施边界

- 本任务只实现本地代码、迁移、测试、规范和离线 eval，不 SSH、不部署、不触发调度、不调用 provider、不发送企业微信。
- 不改新闻评分权重、0.59 阈值、七天正式推送重复语义、事实治理、数字 IP 内容、文案生成、图片流程和发送规则。
- 不覆盖或提交本任务之外的现有工作区修改。

## Acceptance Criteria

- [ ] 开关关闭时，当前每日与时段选择的输出及历史 `.4`--`.8` 回放保持不变。
- [ ] 开关开启且同一优先组存在至少两个合格候选时，fake reranker 能改变最终优先顺序，并且每日 Top 1 / 时段 Top N 使用该顺序。
- [ ] LLM 无法选择低于阈值、硬否决、同日排除、输入池外或低优先组越级的候选。
- [ ] provider 或输出失败时，无需人工介入即可使用现有确定性顺序完成任务，并持久化 typed fallback 原因。
- [ ] 每次 run 能查看锁定的 rerank config、基础/最终排序、理由、模型身份、fingerprint、usage、latency 和 outcome，且没有原始 provider body 或敏感字段。
- [ ] 每日和时段路径共享同一重排服务与校验器；provider 调用期间没有数据库 session 长事务。
- [ ] 相关 unit、adapter、PostgreSQL integration、API contract 和 provider-free eval 全部通过。
- [ ] 实施过程没有生产连接、真实模型调用、业务推送或本任务外文件覆盖。

## Out of Scope

- 让 LLM 修改规则分数、阈值、资格、硬否决、部委优先或七天重复判定。
- 使用联网搜索、全文网页、任意 URL、数字 IP 私有正文或用户私有资料扩展模型输入。
- 多模型投票、在线学习、自动根据点击率改 prompt、强化学习或模型微调。
- 真实线上排序质量结论；本轮 eval 只证明安全边界、结构契约和确定性降级。
- 生产启用、服务器部署、补发、公众号发布或企业微信发送。
