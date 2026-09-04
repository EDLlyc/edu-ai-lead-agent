# 生产新闻未推送只读诊断设计

## 1. Boundary

诊断只允许本机读取和经 `edu-ai-production` 进行 SSH 只读查询。所有远端命令必须是状态读取、
有界日志读取或 SQL `SELECT`；不得运行会刷新证据文件的脚本，也不得执行 Compose `up/restart/stop`、
HTTP POST、数据库 DML、provider preflight/smoke 或队列 retry。

## 2. Causal chain

```text
server clock + deployed identity
  -> scheduler/container liveness
  -> scheduled acquisition
  -> governance terminal state
  -> daily/slot/weekly selection identity
  -> copy terminal state
  -> image + material package readiness
  -> delivery window eligibility
  -> durable WeCom job + child attempts
  -> delivered | failed | partial | delivery_unknown
```

微信公众号周草稿单独检查：

```text
weekly scheduler due state -> weekly run/nodes -> prepared artifacts
  -> draft job/items/attempts -> unpublished drafts only
```

诊断以“最早缺失或失败的持久化节点”为根因边界，避免把下游零计数误判为下游服务故障。

## 3. Safe evidence

- 服务器：UTC/Asia-Shanghai 时间、release SHA/digest 摘要、migration、service/state/health/restart count。
- 配置：仅 allowlisted 非秘密 gate 与 schedule 字段；不读取/输出完整环境文件。
- 数据库：business date、slot、status、safe error code、count、attempt count、not-before/expiry。
- 日志：最近 48 小时，限定服务和匹配 closed event/error code；输出上限固定。
- 本地结果：只写聚合结论，不保存 IP、用户 ID、正文、URL、prompt、provider body、token 或对象路径。

## 4. Decision matrix

| Earliest evidence | Classification | Safe conclusion |
|---|---|---|
| Scheduler not running/restarting | Infrastructure | 调度器不可用，尚未产生计划任务 |
| Gate false or schedule not due | Expected/configured | 当前无任务符合设计，不是 provider 故障 |
| Acquisition missing/failed | Acquisition | 后续零计数是上游结果 |
| Governance incomplete/failed | Governance | 选题尚无合格输入 |
| `no_topic` / slot unfilled | Valid business outcome | 没有满足阈值的新闻，不应强行推送 |
| Copy/image/package failed | Generation | 发送器没有 eligible package |
| Package ready but no job | Delivery policy | 检查 review/direct gate、auto-delivery、日期和窗口 |
| Job queued before `not_before` | Expected timing | 尚未到发送时间 |
| `delivery_window_expired` | Delivery scheduling | 窗口已过且未发送，不自动补发 |
| `failed` / `partial` | Provider/delivery | 按 safe error code给出人工处置建议 |
| `delivery_unknown` | Ambiguous side effect | 禁止自动重发，需人工核对外部平台 |
| Weekly due=false before 2026-09-07 | Expected timing | 公众号草稿尚未到首次计划时间 |

## 5. Failure handling

- SSH/权限失败：报告无法验证生产，不尝试密码或替代主机。
- 表/字段与本地代码不一致：以部署 migration/表结构为准，先读取 catalog，再构造兼容 SELECT。
- 日志或 SQL 输出包含意外内容字段：立即停止该输出，不写入结果。
- 一旦发现需要 mutation，结束诊断并请求新的操作授权。
