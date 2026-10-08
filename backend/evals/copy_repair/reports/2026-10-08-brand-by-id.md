# 修复 Agent 生产回放（copy-repair-agent-v5-brand-by-id）

- 生产上交给修复 Agent 的被拦稿，用线上同一份初稿、拦截问题和品牌资料，在本地重跑当前 Agent，再过同样的规则和该任务当时的审查版本。审查是模型判断，不是人工标注。
- 10 份被拦稿 × 每份 2 次。

| | 结果 |
|---|---|
| 线上旧版 Agent 修好 | 7/10 |
| 当前版本修好（按次） | 17/20（85%） |
| 品牌句保留 | 20/20 |
| 停止原因 | checked 20 |
| 平均输入 token | 9,617 |

| 任务 | 拦截原因 | 线上旧版 | 当前版本 | 停止 / 工具错误 |
|---|---|---|---|---|
| 28536008 | brand_claim_repeated | 修好 | 2/2 | checked；checked |
| 2fe9732e | brand_claim_repeated | 退回重写 | 0/2 | checked；checked |
| 35a5038a | unsupported_brand_claim | 修好 | 2/2 | checked；checked |
| 87e3b912 | brand_claim_repeated | 修好 | 2/2 | checked；checked |
| 969ed987 | unsupported_brand_claim | 修好 | 2/2 | checked；checked |
| 98deca6a | unsupported_brand_claim | 修好 | 2/2 | checked；checked |
| 9ee26638 | unsupported_brand_claim | 修好 | 2/2 | checked；checked（same_sentence） |
| b4a33e77 | unsupported_brand_claim | 修好 | 2/2 | checked；checked |
| c9f6b4bb | unsupported_brand_claim | 退回重写 | 2/2 | checked；checked |
| e5a59f70 | brand_claim_repeated | 退回重写 | 1/2 | checked；checked |

## 结论

- 线上 v3/v4 在这 10 份上修好 7 份；剩下 3 份都是同一个失败方式：6 次 replace_claim 都因“品牌句不是资料原句”
  （claim_not_in_brand）被拒，耗满 6 轮后退回重写。
- v5 改为 list_brand_sentences + use_brand_sentence 按编号选句：20 次运行里“抄不准原句”的错误为 0，没有一次
  耗满轮数（20 次都在规则通过后停下），每次平均输入 token 9.6k（线上 v4 约 12k）。
- 线上修好的 7 份，v5 两次都修好（14/14）；线上失败的 3 份，v5 修好 3/6 次。剩下 3 次失败都是同一种：
  换上的品牌句通过了规则，但审查认为它和这条新闻不相干（unsupported_brand_claim）。这已经是“选哪句”的判断
  问题，不再是工具使用问题；失败时照旧退回整篇重写。
- 87e3b912 是 10-03 线上删掉品牌句导致长图缺失的那份；v5 两次都换句修好、保留了品牌句。
- 样本小（10 份 × 2 次），审查是模型判断。
