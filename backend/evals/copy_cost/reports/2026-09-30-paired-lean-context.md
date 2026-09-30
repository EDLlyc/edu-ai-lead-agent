# 配对对比：同一批选题、初稿和埋雷，两套提示词版本

- 选题 10 条（生产上真实通过的）；基线 `moments-generator-v26-headline-hook + moments-auditor-v20-headline-hook`，候选 `moments-generator-v27-lean-context + moments-auditor-v21-lean-context`。
- 生成：每条选题两个生成版本各生成一次，只比 token 与初稿是否过规则。
- 审查：原稿和埋雷稿都用候选生成的初稿，两个审查版本审同一批文案。
- 拦截理由按错误码关键词归类（启发式，见脚本 FAMILIES）；单次运行，没有重复试验。

## 每次调用平均 token（输入 / 输出）

| 环节 | 基线 | 候选 | 输入变化 |
|---|---|---|---|
| 生成 | 8,230 / 418 | 7,964 / 424 | -3% |
| 审查 | 7,935 / 142 | 2,651 / 130 | -67% |

- 模型服务拒绝的审查调用：基线 0 次，候选 1 次（计为无结果，不算拦截）。

## 原稿（对照组）

| 审查版本 | 通过 | 只提醒 | 被拦 | 被拦原因 |
|---|---|---|---|---|
| baseline | 9 | 0 | 0 | – |
| candidate | 8 | 0 | 0 | – |

## 埋雷（同一批埋雷稿）

| 缺陷 | 适用 | 基线：理由对 / 碰巧拦 / 只提醒 / 漏过 | 候选：理由对 / 碰巧拦 / 只提醒 / 漏过 |
|---|---|---|---|
| hook_anxiety_listed | 8 | 8 / 0 / 0 / 0 | 8 / 0 / 0 / 0 |
| hook_anxiety_paraphrase | 8 | 6 / 2 / 0 / 0 | 8 / 0 / 0 / 0 |
| hook_marketing_listed | 8 | 8 / 0 / 0 / 0 | 8 / 0 / 0 / 0 |
| hook_marketing_paraphrase | 8 | 4 / 0 / 4 / 0 | 7 / 0 / 1 / 0 |
| hook_off_topic | 8 | 0 / 4 / 4 / 0 | 0 / 3 / 5 / 0 |
| hook_fabricated_number | 8 | 8 / 0 / 0 / 0 | 8 / 0 / 0 / 0 |
| hook_fabricated_policy | 8 | 4 / 4 / 0 / 0 | 5 / 3 / 0 / 0 |
| brand_effect_fabricated | 8 | 8 / 0 / 0 / 0 | 8 / 0 / 0 / 0 |
| brand_as_fact_binding | 8 | 8 / 0 / 0 / 0 | 8 / 0 / 0 / 0 |
| claim_number_outside_evidence | 2 | 2 / 0 / 0 / 0 | 2 / 0 / 0 / 0 |
| claim_number_swapped | 1 | 1 / 0 / 0 / 0 | 1 / 0 / 0 / 0 |
| claim_meaning_reversed | 2 | 2 / 0 / 0 / 0 | 2 / 0 / 0 / 0 |

- baseline：77 个埋雷，理由对 59（77%），碰巧拦 10，只提醒 8，漏过 0。

- candidate：77 个埋雷，理由对 65（84%），碰巧拦 6，只提醒 6，漏过 0。
