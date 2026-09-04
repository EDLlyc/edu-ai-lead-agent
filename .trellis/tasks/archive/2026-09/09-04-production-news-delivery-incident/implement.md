# 实施计划

1. 以 `BatchMode=yes` 验证 SSH；读取服务器时间、时区、release marker、migration 和磁盘/容器健康摘要。
2. 读取 allowlisted gate/schedule 配置值，确认 legacy daily、三时段和 weekly draft 的实际启用状态。
3. 查询 2026-09-03 至 2026-09-05 的 acquisition/governance 聚合状态，确定是否形成当天可选输入。
4. 查询 daily selection、slot run/job/selection 与 weekly run/node 的日期/状态/计数，确定实际调度路径。
5. 查询 copy run/job、image artifact、material package 的状态计数和 safe error code，定位生成断点。
6. 查询 delivery window/job/attempt 的状态、时间边界、attempt count 与 safe error code，禁止读取收件人或正文。
7. 读取最近 48 小时相关服务的有界安全日志，和数据库状态交叉验证。
8. 将首个断点、影响、置信度、预期/事故判断及最小处置建议写入 `result.md`；不执行修复。
9. 复核本地任务 diff、秘密/私有内容缺失、所有远端命令无 mutation，并由独立 checker 审阅结论。

## Verification

- 所有 SQL 都是 `SELECT` 或 catalog introspection；无 HTTP 非 GET 请求。
- `git diff --check -- .trellis/tasks/09-04-production-news-delivery-incident`。
- 结果中不包含 secret-shaped value、完整 URL、用户 ID、正文、prompt、provider body 或对象路径。
- 远端服务 restart count、数据库业务计数和 provider attempt count 不因诊断增加。
