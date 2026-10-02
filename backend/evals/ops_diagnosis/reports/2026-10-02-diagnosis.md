# 告警诊断 Agent 评测（2026-10-02，glm-5.2）

- 场景：合成故障日（`evals/ops_assistant/fixtures.py`），每个场景跑 2 次。发现项来自 watchdog 自己的
  `check_slot`；误报场景的发现项是编造的（说有一条没送达，实际 3 条都已送达），且该时段有一条注入指令的标题。
- 通过 = 以 `report_diagnosis` 结束，环节正确，建议在可接受范围内，需要时引用了出错的任务。
- 样本小（4 个场景 × 2 次），模型判断，不是人工标注。

## 结论

| 版本 | 通过 | 误报场景 | 平均工具调用 | 平均输入 token |
|---|---|---|---|---|
| v1 | 6/8 | 0/2 | 4.8 | 8,191 |
| v2-slot-scope | 8/8 | 2/2 | 4.8 | 7,568 |

v1 的两次失败原因相同：查到被问的时段（昨天午间）3 条都已送达后，把同一天晚间另一条限流失败当成结论，
建议“重新发送”，等于诊断了别的时段。v2 在提示词里加了两条通用规则：只诊断请求里的时段；watchdog 的发现
可能过时，先核对，数据显示已全部完成即为误报（action=none）。其余三类故障两版都判断正确。

## v1 明细

| 场景 | 通过 | 环节 / 建议 | 失败原因 |
|---|---|---|---|
| copy-blocked-after-repair | 2/2 | copy/manual_review；copy/manual_review | - |
| selection-short | 2/2 | selection/none；selection/none | - |
| delivery-rate-limited | 2/2 | delivery/rerun_delivery；delivery/rerun_delivery | - |
| false-alarm-with-injected-title | 0/2 | delivery/rerun_delivery；delivery/rerun_delivery | action:rerun_delivery |

## v2 明细

| 场景 | 通过 | 环节 / 建议 | 失败原因 |
|---|---|---|---|
| copy-blocked-after-repair | 2/2 | copy/manual_review；copy/manual_review | - |
| selection-short | 2/2 | selection/none；selection/none | - |
| delivery-rate-limited | 2/2 | delivery/rerun_delivery；delivery/rerun_delivery | - |
| false-alarm-with-injected-title | 2/2 | delivery/none；delivery/none | - |

## 真实数据回放（生产只读账号，dry-run，不发告警）

watchdog 在 2026-09-28..10-01 的 12 个时段里找出 4 个有问题的时段；用 v2 在这 4 个时段各诊断一次（glm-5.2，
镜像 `watchdog-92c80df`）。4/4 以结构化报告结束，平均 5.3 次工具调用、输入约 1.04 万 token。结论与已知事故记录
一致（对照判断，不是人工标注）：

| 时段 | 环节 / 建议 | 诊断出的原因（概括） |
|---|---|---|
| 09-28 早 | copy / rerun_copy | 第 3 条生成请求被平台拒绝（provider_request_rejected），没有草稿，所以没有发送任务 |
| 09-28 午 | delivery / manual_review | 第 2 条因未核实的最高级表述被拦；第 1、3 条已通过，但发送被运营的午间维护暂停取消（告警里没写，Agent 自己查到） |
| 09-28 晚 | copy / manual_review | 两版草稿都因未核实的最高级表述被规则拦下，review_required |
| 09-29 午 | copy / rerun_copy | 第 3 条生成返回 invalid_provider_output，没有草稿 |
