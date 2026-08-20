# 本地重新抓取新闻一次

## Goal

在本地只执行一次受控新闻采集，禁止自动进入治理、选题、文案、图片或推送，并记录来源与结果统计。

## Requirements

- 仅操作本地开发环境，不连接生产服务器，不执行 SSH、部署或消息发送。
- 使用一个新的 `Idempotency-Key` 通过正式采集 API 创建一次 manual acquisition run；不删除、覆盖或重放已有 run。
- 只启动 API 和 acquisition worker。不得启动 acquisition scheduler、governance、content scheduler/worker 或 WeCom dispatcher。
- 使用当前已登记且启用的全部来源；不添加临时来源，不进行开放式网页搜索。
- 等待本次 run 进入自然终态，记录 run ID、来源数、各 job 终态、new/unchanged/duplicate/filtered/failed 统计。
- 完成或失败后停止本次启动的所有临时进程，并确认没有由本次操作创建 governance、topic-selection、copy、image 或 delivery 工作。
- 不修改代码、配置、数据库历史数据或用户未提交文件。

## Acceptance Criteria

- [x] 创建或取得的 run 可明确绑定本次唯一 idempotency key，且只提交一次 POST。
- [x] acquisition jobs 全部进入终态，或明确报告未终态/失败原因，不做整轮自动重试。
- [x] 输出每个来源的成功/失败摘要以及总 new/unchanged/duplicate/filtered 数量。
- [x] governance、topic selection、copy、image 和 delivery 的本次增量均为零。
- [x] 临时 API/worker 进程全部停止；没有推送或部署。

## Notes

- 这是一次本地业务操作，不是代码变更。若 API 因配置/迁移/基础设施状态拒绝创建 run，先只读诊断并报告，不自动修改数据库或配置。
