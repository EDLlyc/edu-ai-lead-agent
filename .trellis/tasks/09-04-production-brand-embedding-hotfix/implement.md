# 实施计划

1. 记录必要文件的 pre-existing diff，读取 backend/provider/release 规范，冻结本任务增量边界。
2. 扩展 `Settings` 的 brand provider 类型、`auto` resolver、provider identity 和非法组合校验；增加自动投递
   fail-fast 配置契约。
3. 在 brand embedding factory 增加 zhipu 分支，复用 `ZhipuEmbeddingModel` 与
   `GovernanceEmbeddingBrandAdapter`，不新增 provider 协议实现。
4. 修正 API/content worker owned-client 装配与关闭路径；启动日志增加安全的 resolved provider identity。
5. 更新 `.env.example`、Compose 共享环境和 `scripts/doctor.sh`，保证 brand provider 跨服务一致且自动投递
   配置可生成 copy。
6. 增加 resolver/validator/factory/client-wiring/Compose/release tests，覆盖 zhipu、Alibaba、fake、disabled、
   provider-free 与自动投递 fail-fast。
7. 运行定向测试、backend lint/type-check、Compose render、doctor 静态检查和 release contract tests；检查
   没有秘密、正文、向量或 provider body 进入日志/产物。
8. 独立质量复核本任务 diff；只 stage 热修复 hunks，在 `main` 提交并推送 Codeup/GitHub。
9. 从生产分支 `a4a3c00` 创建非强推 `release/brand-embedding-hotfix-20260904`，只移植热修复；验证其为
   `40e4dec…` 后代且运行时 diff 命中白名单，不发布当前分叉的完整 `main`。
10. 因当前没有可用 registry，新增并回归本任务专属离线 builder、纯 validator、mode-0600 一次性 operator
   和 fake harness；绑定 fetched release ref、生产 baseline、完整 source/image 归档、12 服务、零发送状态和回滚。
11. 从该 release ref 构建 linux/amd64 不可变镜像并通过离线 operator 部署；保持受保护 `.env` 原始值不变，
   核对 resolved provider、release marker、OCI revision、迁移版本、12 服务 health/image/restart count。
12. 在生产执行一次无持久化写入的有界 `embedding-3` smoke，只保留 provider/model/dimension/状态；随后
    只读确认 worker readiness，不 enqueue、不 replay、不发送。
13. 将生产验证、未恢复的历史任务边界和下一次自然调度观察项写入任务结果。

## Verification

- `pytest`：Settings/resolver、brand factory、API/content worker wiring、release contract 的定向用例。
- backend：项目约定的 lint、format-check、type-check 与相关 integration/contract suite。
- deploy：`docker compose ... config`、`bash -n scripts/doctor.sh`、doctor 的 provider gate。
- Git：`git diff --check`；staged patch 不含任务开始前的无关 hunk；提交不包含 secret/private content。
- Release ref：`git merge-base --is-ancestor 40e4dec… <release>` 成功；生产基线到 release 的 runtime diff
  只含审核白名单，Codeup/GitHub ref 一致。
- Offline release：builder/validator/operator/fake harness 的 task-local tests 通过；归档绑定 fetched ref、
  linux/amd64 image graph、source manifest、生产 baseline、相同 migration head 和全部 12 个应用服务。
- production：一次 embedding 请求；数据库业务计数、18 个历史 copy run 和企业微信 attempt 数不因 smoke 增加。

## Stop Conditions

- 智谱 smoke 返回身份/维度不匹配，或 provider 错误无法安全分类。
- 发布会夹带无法拆分的无关 WIP。
- release marker 与 OCI revision 不一致，或新容器 restart/health 异常。
- 任何步骤需要重放历史任务、写业务数据库或触发消息发送；这些必须另行授权。
