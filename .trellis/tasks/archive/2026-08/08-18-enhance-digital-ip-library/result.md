# 完善数字 IP 资产库：交付结果

## Outcome

已在现有品牌知识工作台内完成“赛先生与小赛”单 IP 的本地作品集闭环：active-ready 品牌版本与
已审核视觉 manifest 被聚合为只读人设投影，页面继续复用原有品牌混合召回，结果可解释到文档、
版本、类型、标签和三类分数，并显式保持 `evidence_eligible=false`。人工采纳/不采纳反馈仅进入
浏览器本地受限 ledger，不会写回服务端、激活知识、调用模型或触发发送。

## Delivered contracts

- 新增 `GET /api/v1/digital-ip/profile`，从既有 document projection 只选权威
  `active_version_id + active=true + ready` 版本；输出稳定 profile/character/document-binding
  类型和确定性 SHA-256 fingerprint。
- 视觉分支复用 `load_visual_catalog`，文件读取通过线程执行；只返回最多 12 条 approved
  赛先生/小赛元数据。响应没有 filename、path、object key、URL、完整 digest 或图片字节；
  legacy filename display fallback 会替换为中性标签，路径/URL/完整 digest 形态的元数据值会
  fail closed。
- manifest 缺失、损坏或校验失败返回 `visual_catalog_status=unavailable`；合法 catalog 无匹配
  approved asset 返回 `empty`；两种情况均保留文字人设。
- OpenAPI 和前端生成 schema 已更新。工作台顶部显示角色、人设规则来源、active 标签、受众、
  场景、fingerprint、active-ready 版本/有效期绑定与视觉审核元数据；视觉失败使用真实空态。
- 现有 `POST /brand-context/retrieve` 未被复制或改写。UI 补充来源版本、资料类型、语气/安全/
  视觉标签、full-text/vector/fused 分数和品牌不能证明外部事实的边界。
- 新增 `edu-ai-lead-agent.digital-ip-feedback.v1` browser-local ledger：运行时校验、最多 50 条、
  160 字备注，保存 query/profile fingerprint、chunk/version IDs、采纳结论和受控原因；损坏记录
  fail-safe，并通过字段 allowlist 重建记录，未知字段不会被再次保存；支持清除，不保存召回正文。
- 新增五类脱敏 provider-free eval 与 checked JSON/Markdown。当前 5/5 通过，预期类型覆盖
  100%，预期标签/角色覆盖 100%，禁用规则命中 100%，品牌误作事实证据 0 次。报告明确说明它
  只是 fixture contract conformance，不代表真实 embedding、召回或模型准确率。

## Focused validation

- Ruff format/check：12 个本任务 Python 文件通过。
- strict mypy：10 个修改/新增 backend app 与 eval source files 通过。
- backend focused pytest：`test_digital_ip.py` + `test_digital_ip_eval.py`，10 tests 通过。
- digital-IP canonical eval：`python -m evals.digital_ip.runner --check`，5/5 通过。
- production + Agent OpenAPI/generated clients：`api-contract-check` 与
  `agent-api-contract-check` 均通过，无 drift。
- frontend focused Vitest：brand API、profile/visual/retrieval/axe、feedback storage 共 15 tests
  通过。
- frontend Prettier、targeted ESLint、project strict TypeScript 和 production Vite build 通过。
- Digital-IP OpenAPI forbidden-field semantic scan、scoped secret scan 与 `git diff --check` 通过。
- 按任务约定未运行 full backend/frontend suite；定向门没有发现需要扩展到全仓测试的问题。

## Safety and limitations

- 未运行 SSH、部署、数据库 migration、provider、企业微信或任何发布/发送操作；未修改 Compose、
  调度、生产 flag 或业务数据。
- 反馈是单浏览器本地记录，不支持跨浏览器历史，也不冒充训练数据或生产审核流水。
- 页面只展示视觉元数据，不提供私有图片预览、上传、编辑或原图访问。
- Eval 是确定性 fixture 基线；真实语义召回质量仍需以后在受控真实 embedding 数据集上评估。
- 保留并未修改既有 `reports/**` 和 `.trellis/tasks/08-17-agent-workbench-public-portfolio/` 用户资产。
