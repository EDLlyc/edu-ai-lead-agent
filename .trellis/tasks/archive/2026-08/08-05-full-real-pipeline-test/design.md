# 技术设计

## 边界

本任务增加一个本地测试编排入口和一个前端展示面板，不改变正式生产 API 的语义。测试
直接复用现有 API、scheduler、worker、领域选择器和模型适配器；结果写入当前本地开发
数据库/MinIO，并导出脱敏预览 manifest。若验证发现代码缺陷，修复范围限于阻塞本次验收
的最小变更。

## 数据流

```text
预览入口
  -> 当前本地 PostgreSQL/MinIO
  -> 正式采集入口
  -> acquisition-worker
  -> 终态 acquisition run / candidates / snapshots
  -> governance run
  -> governance-worker
  -> topic-selection run
  -> content-worker: Top 1 + brand retrieval + Zhipu copy/validation/audit
  -> accepted copy-generation run
  -> material-package reservation
  -> content-worker: visual selector + Comfly 1024x1024
  -> image validation + MinIO private object
  -> material package awaiting_manual_use
  -> 预览 manifest + image -> output/preview/<run-id>/
  -> frontend preview page
```

正式产品链路在素材包审核/通过后再接入独立的 `wechat-delivery` durable stage：读取企业微信
自建应用 secret store 中的凭据，向一个配置好的销售 `userid` 发送文案和图片，并以
`package_version + recipient_userid` 做幂等键，持久化发送状态、重试次数和回执。该阶段不
使用前端按钮触发，也不扩展为群发或朋友圈发布；本次预览 runner 明确停在素材包，不发送
真实消息。

每个阶段通过 API 返回的 UUID 连接，轮询只接受明确终态；不会用日志猜测状态，也不会
在阶段未准备好时直接修改下游表。脱敏 manifest 不包含凭据、临时 URL 或 MinIO 内部对象
路径。

## 前端预览

预览 runner 生成不含凭据和内部对象路径的 `manifest.json` 以及 PNG；前端通过 Vite 的
本地 preview 资源读取它们。页面复用现有深色控制台的 token 和组件语言，但单独呈现一次
预览的阶段时间线、文案、标签、图片、来源和审计结果。页面只负责查看，不承载正式发送。

## 隔离策略

- 使用唯一的手动幂等键和唯一输出目录；重跑不覆盖任何已有预览。
- 同一 fingerprint 的重放复用现有 reservation；不得为了展示结果重复扣费生图。
- 输出文件名包含运行 ID 和阶段含义，且使用独占创建，避免覆盖之前样本。
- 教育部优先使用独立、版本化的“科学政策”判定：来源必须为教育部科学来源，标题/摘要必须
  同时命中科学教育主题与政策/行动语义。规则版本升级创建新的 scoring 配置，历史日锁保持不变。

## 安全与失败处理

- 保留图片输出 `1024x1024`、HTTPS、重定向、主机、媒体类型、字节数和 MinIO 私有存储
  校验；不因本次验收取消 SSRF/Fake-IP 拒绝规则。
- 供应商临时 URL 只在内存中下载，数据库只留安全元数据。
- 文案失败只允许现有配置的有限重试/一次修复；终态错误要在报告中展示。
- 任意阶段 `review_required` 或 `failed` 都停止后续依赖阶段，并保留可审计状态。

## 兼容性与回滚

- 不执行 `docker compose down -v`、Alembic downgrade 或直接 SQL 修改。
- 只对本次测试创建的业务记录进行正式 API 查询和复用，不删除已有本地数据。
- 只重建受改动影响的 worker；若代码修复未通过质量检查，保留原失败结果并停止真实调用。
- 真实生成的 `output/preview` 是本地验收产物，不进入 Git。
