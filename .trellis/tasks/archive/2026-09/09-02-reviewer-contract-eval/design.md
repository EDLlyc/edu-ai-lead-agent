# Reviewer 契约与离线评测：技术设计

## 1. 边界

本子任务只新增纯 domain contract 和 `backend/evals/official_account_reviewer` provider-free evaluator。
不接数据库、官方账号 executor 或外部模型；因此后续生产接入只能消费该版本化契约，不能复制一份
更宽松的 parser/taxonomy。

## 2. 严格 verdict

- `ReviewDecision`: `accepted|manual_review|rejected|unavailable`。
- `ReviewIssue`: 闭集 editorial issue code、`critical|warning`、有界 section/block/claim/evidence reference。
- `ReviewVerdict`: decision、排序且去重的 issues、reviewer/prompt/schema/rubric/policy identity 和输入绑定。
- 未知字段、自由文本指令、重复 issue、越界引用、accepted + blocking issue、unavailable + model issues 等
  非法组合拒绝构造。
- repairability 不是模型字段；版本化 `RepairPolicy` 将闭集 issue/location 纯函数映射到有界
  `RepairDirective`，不包含模型生成的命令文本。

硬门禁输入单独建模。其失败优先级高于所有 Reviewer 分数/verdict，用于证明事实、隐私、安全、注入
与发布限制不能被平均分、审美信号或 Reviewer accepted 覆盖。

## 3. Dataset 与 oracle 隔离

至少 48 个脱敏、稳定 ID 的 JSONL case：正确文章、品牌语气、结构/层级、营销夸大、边界/人工复核、
hard-gate precedence、provider unavailable/非法 schema。case 输入不携带期望 verdict；oracle 存在独立
文件并由 loader 以 ID 严格一对一绑定，防止 evaluator 把答案泄漏给被测策略。

dataset、oracle、rubric、policy 和 runner 均有 SHA/version。重复 ID、未知键、断裂 reference、未覆盖
维度或 case 数不足立即失败。

## 4. 指标与 canonical

报告区分 Reviewer 编辑维度与端到端 hard-gate 安全维度：

- editorial critical precision/recall/F1、false accept、false reject、manual-review rate；
- issue/location 与 repairability accuracy；
- hard-gate override violations 必须为 0；
- schema/permission/provider-unavailable 分支覆盖和 failure taxonomy。

canonical JSON/Markdown 由 runner 生成并用 drift test 固定。报告标题、metadata 和 README 明示
`provider_free=true`、`live_model_calls=0`，不得称为线上 accuracy 或模型提升。

## 5. 测试重点

纯 domain 构造/序列化、闭集与边界值、fingerprint determinism、oracle 隔离、数据损坏、hard-gate
precedence、repair policy、canonical 重算与隐私扫描。CI 不需要 key 或网络。
