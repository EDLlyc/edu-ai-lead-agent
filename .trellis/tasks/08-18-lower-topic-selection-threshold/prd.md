# 降低新闻入选评分阈值至 0.59

## Goal

将新创建的新闻选题运行的入选评分阈值从 `0.6200` 调整为 `0.5900`，提高合格候选数量；保持现有治理、时效、重复、排序和推送安全规则不变，并以可回滚方式部署到生产。

## Requirements

1. 新增不可变评分版本 `scoring-v1-preview.8-threshold-059`，其默认阈值为 `0.59`。
2. `.8` 必须继承 `.7` 的全部行为，唯一业务差异是阈值：
   - 仍以“最终正式成功推送”作为 7 天重复窗口依据；
   - 仍使用 `topic-veto-v4-delivered-content`；
   - 权重、编辑规则、教育部科学教育优先、时效窗口、风险否决、主题重复惩罚、tie-break 和 `item_limit=3` 均不变。
3. 历史版本不可被重新解释：
   - `.7` replay 仍为阈值 `0.62` + delivered-history v4；
   - `.6` replay 仍为阈值 `0.62` + selection-history v3；
   - 已持久化 snapshot/fingerprint 必须继续可重放。
4. Settings、Compose 和 `.env.example` 的新安装默认值统一改为 `.8`。
5. 本次不更改数据库 schema、OpenAPI、依赖、新闻解析、评分权重、否决规则、选题数量或推送逻辑。
6. 本次不重跑、不补选、不重发今天早上的历史运行；新语义仅作用于部署后新创建的评分运行。
7. 部署前必须从干净的 Codeup `main` 精确构建候选，并证明生产当前 `.env` 是评分版本唯一 owner、值为 `.7`，`.release.env` 无同名键。
8. 部署必须先创建新鲜可验证回滚集，再原子切换 `.env` 到 `.8`；失败时恢复 `.7`、旧代码/镜像/标记和原有服务。
9. 发布过程不得主动调用模型供应商、创建业务运行、补发或重发企业微信消息。

## Acceptance Criteria

- [ ] `.8` 配置的阈值精确为 `0.59`；`0.5899` 不通过、`0.5900` 通过。
- [ ] `.8` 的 veto、权重、优先级、时效和排序元数据除 version/threshold/fingerprint 外与 `.7` 等价。
- [ ] `.8` 仍使用 delivered-history v4；近期已正式成功推送的同事件即使得分超过 `0.59` 仍被否决。
- [ ] literal `.7` snapshot/replay 仍为阈值 `0.62` 且使用 delivered-history v4。
- [ ] literal `.6` snapshot/replay 仍为阈值 `0.62` 且使用 selection-history v3。
- [ ] 配置默认值、Compose 默认值和示例环境统一为 `.8`。
- [ ] focused unit/integration tests、Ruff、mypy、完整 backend gate、Compose render 与 diff/secret checks 通过。
- [ ] Codeup `main` 包含精确候选提交，生产部署证据绑定该 full SHA 与候选 image ID。
- [ ] 生产 `.env` 恰好一处 `.8`，`.release.env` 零处；相关运行时容器读到 `.8`/`0.59`。
- [ ] 8 个应用服务使用候选镜像、运行正常、restart count 为 0，API/PG/MinIO 健康。
- [ ] 部署前后既有 durable/provider/WeCom 计数无发布引发的增量；没有历史重跑或重发。

## Out of Scope

- 调整评分权重、候选上限、栏目配额、重复窗口天数或 veto 语义。
- 修复新闻解析或 OCR；手工重跑、人工补选、人工补发。
- 让今天已经持久化的 `.7` 运行改用 `.8`。
- 数据库迁移、前端/API schema 或依赖变更。

## Verified Planning Evidence

- 2026-08-18 生产只读核验：`acquisition-api`、`content-scheduler`、`content-worker` 均读取 `.7`；`.env` 恰好一处 `.7`，`.release.env` 零处评分版本键。
- 今日早间阈值为 `0.6200`；降到 `0.5900` 后，`0.5997`、`0.5995`、`0.5978` 三条可越过数值门，但仍须经过全部既有 veto/栏目/排序规则。
- 当前生产代码/镜像版本为 `5d0a4caca97cc61edd201e26bf99f038500f107a`，8 个应用服务此前核验为 healthy/restart0。
