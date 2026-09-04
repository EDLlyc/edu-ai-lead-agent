# 生产新闻未推送故障排查

## Goal

在不产生任何新业务副作用的前提下，只读检查生产服务器当前版本、进程、调度、持久化队列和安全日志，
区分“尚未到计划时间”“合法无候选/未生成”“上游失败”“发送被策略阻断”和“企业微信发送失败”，
定位 2026-09-04 未看到新闻的首个失败或未触发环节，并给出证据化处置建议。

## Confirmed Facts

- 本机已有受信任的 `edu-ai-production` SSH alias；生产运行目录按发布契约为
  `/opt/edu-ai-lead-agent`。
- 企业微信日常消息与微信公众号周草稿是两条独立链路。只有 `wecom-dispatcher` 能执行企业微信发送；
  微信公众号 worker 只创建未发布草稿，不能自动发布、群发或置顶。
- 2026-09-02 的周任务生产激活记录显示首次 eligible execution 是
  `2026-09-07 09:00 Asia/Shanghai`，当时 `due=false`，周任务和草稿计数均为 0；因此 9 月 4 日
  没有公众号周草稿可能是预期行为，不能直接认定为故障。
- 日常/三时段链路应按 acquisition → governance → selection → copy → image/package →
  delivery window/job/attempt 排查；`no_topic`、unfilled、尚未到 `not_before` 或过期均可能是合法状态。
- `delivery_unknown` 表示外部发送结果不确定，禁止自动重发；日志出现 provider 调用也不能替代数据库
  `delivered` 终态证据。
- 当前本地工作区有大量未提交 WIP，不能据此推断生产行为；服务器实际 release commit/image/migration
  才是本次诊断依据。

## Requirements

### R1 — 只读生产身份与健康检查

- 使用 BatchMode 和已配置 host alias 连接；记录服务器时间/时区、release commit/image、Alembic head、
  相关 Compose 服务状态、健康状态和 restart count。
- 不打印 `.env`、容器完整环境、凭据、用户 ID、正文、图片路径、对象 key、provider body 或认证 URL。

### R2 — 从持久化状态定位首个断点

- 以 `Asia/Shanghai` 的 2026-09-04 为主窗口，并观察前后至少一天的聚合趋势。
- 同时检查 legacy daily、morning/noon/evening slot、weekly draft 三条调度身份，不能假设服务器已经启用
  本地最新功能。
- 数据库只查询日期、状态、数量、安全 error code、attempt count、not-before/expiry 等非内容字段；
  不查询正文、prompt、来源 URL、收件人、provider response 或对象位置。

### R3 — 安全日志关联

- 只读取最近 48 小时相关 scheduler/worker/dispatcher 的有界日志，并仅保留时间、service、closed event/
  error code、状态和计数。
- 将日志与数据库终态交叉验证；单条日志不能独立证明发送成功或失败。

### R4 — 诊断结论与处置边界

- 结论必须指出首个未触发/失败 stage、直接证据、影响范围和置信度，并区分预期调度行为与真实事故。
- 本任务只诊断，不执行 restart、配置修改、数据库写入、队列 replay、人工 enqueue、provider smoke、
  WeCom retry/resend、部署或发布。
- 若修复需要任何生产 mutation，先给出最小、可回滚方案和重复发送风险，再等待新的明确授权。

## Acceptance Criteria

- [x] 已确认 SSH、服务器时间/时区、部署 commit/image、迁移版本和相关服务健康/restart 状态。
- [x] 已给出 2026-09-04 acquisition、governance、selection、copy、package、delivery 的安全聚合状态。
- [x] 已区分企业微信日常消息与微信公众号周草稿，并说明各自是否到期、是否产生 durable work。
- [x] 已检查最近 48 小时有界安全日志，且没有在本地结果中保存秘密或内容数据。
- [x] 已定位首个断点或证明当前行为符合调度设计；未知项明确写为未知，不从缺失日志臆断。
- [x] 未发生服务重启、配置/数据库写入、任务补跑、模型/provider 调用、消息重发、部署或推送。
- [x] 诊断结果写入本任务 `result.md`，包含时间、证据、根因、影响和后续建议。

## Out of Scope

- 直接恢复新闻推送、补发 9 月 4 日内容或手动触发任何调度任务。
- 修改代码、配置、部署镜像、Git 分支、服务器文件、数据库或外部平台状态。
- 检查或展示新闻正文、企业微信收件人、公众号内容、品牌私有资料和 provider 原始响应。

## Deliverable

- `result.md`：只读生产诊断结论与安全证据摘要。
