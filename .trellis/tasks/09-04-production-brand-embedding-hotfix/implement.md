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
    builder 在 build 前基于能力选择 buildx 或严格 legacy/containerd 路径；后者固定本地 Docker socket 与
    `/run/containerd/containerd.sock`、linux/amd64、
    containerd snapshotter/moby namespace 和 legacy argv/env，导出后由纯 Python 重建严格单-manifest OCI graph，
    不因 buildx 或构建运行失败静默 fallback，也不放宽最终 validator。
11. 从该 release ref 构建 linux/amd64 不可变镜像并通过离线 operator 部署；保持受保护 `.env` 的 bytes 及
   已审核 `0600 / 1000:1001` 身份不变；用拒绝 symlink/路径替换/读取期漂移的单 fd 稳定指纹，在锁前、锁内、
   quiesce 后、迁移与服务启动前、回滚服务重启前后和最终阶段重复核对，并验证 resolved provider、release
   marker、OCI revision、迁移版本、12 服务 health/image/restart count。
   同时按真实 `_claim` 日期语义要求当天 claimable/running/current-day/future copy 门禁为 0，以精确 count=7
   与 canonical SHA-256 全程绑定历史冻结 cohort；capture 同时固定已审核日期集合、`queued/attempt_count=0`，
   日期跨界或 cohort 漂移立即失败，不对这 7 条记录执行 DML。
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
- Builder fallback：harness 覆盖 buildx/明确缺失/异常失败路由、legacy 能力及 argv/env、Docker normalized ref、
  Docker→OCI layer media canonicalization、manifest digest 更新、nested/dangling/symlink/malformed 拒绝及 cleanup；
  canonical graph 必须由未放宽的真实 stage validator 接受；index 的 normalized full name/short ref name
  必须能在 fresh load 后重建 tag，legacy raw tag 仅在证明为本次所有时于 load 前移除；加载身份覆盖 classic
  store 的 config digest 与 containerd image store 的 manifest digest 两种精确语义，拒绝 tag 缺失、stale tag
  和 graph 外 ID，并以实际加载 ID 验证服务收敛；source probe 测试捕获并执行真实容器 Python argv，证明每个
  完整范围文件恰好生成一条 canonical newline 分隔摘要，而非字面量 `\n` 拼接行，并在 host/image 两侧
  拒绝可通过换行或制表符注入摘要记录的非 canonical path；真实 298-file release manifest 必须按序列化后的
  relative POSIX path string 排序并与完整 source archive 投影逐 path/hash 相等，Alembic head 由完整 migration
  源码中的唯一、未重绑定静态 revision 声明与 candidate `alembic heads` reported identity 共同证明，不绑定
  手写文件名；解析前后固定迁移数、单文件 bytes 与 AST 节点上限，拒绝动态声明和解析资源耗尽；
  staged baseline 与 pre-load OCI graph 的两次真实
  validator import 以及其余 staged validator 执行都必须以 no-bytecode 模式运行，测试证明有效和拒绝路径的
  递归 stage member set 均不变且不会产生 `__pycache__`，并静态约束所有 invocation 防止新增第三个写入边界；
  builder/operator source probe 的真实 `python -c` argv 必须完全相等，并在 298-file release 投影上产生与
  stage 逐字节相同的 LF-delimited manifest；operator preflight 失败清理还需覆盖 owned inactive、preloaded、
  tag drift、Docker inventory error 与 container-in-use 路径，任何不确定状态均保留镜像；Compose topology
  对 12 个服务精确绑定继承的 backend build metadata、拒绝显式 pull policy，而不是拒绝共享开发字段，同时运行时强制且静态枚举
  candidate activation 与 rollback/recovery 的全部 create/up 路径均带 `--no-build`，并禁止 migration run 显式
  请求 `--build` 及赋值形式（该子命令不支持 `--no-build`）。
- production：一次 embedding 请求；数据库业务计数、18 个历史 copy run 和企业微信 attempt 数不因 smoke 增加。
- copy-state：`Asia/Shanghai` 业务日期在发布窗口内不跨界，7 条历史冻结 job 的 count/digest 不变，且当天
  claimable/running/current-day/future copy gate 始终为 0。

## Stop Conditions

- 智谱 smoke 返回身份/维度不匹配，或 provider 错误无法安全分类。
- 发布会夹带无法拆分的无关 WIP。
- release marker 与 OCI revision 不一致，或新容器 restart/health 异常。
- 任何步骤需要重放历史任务、写业务数据库或触发消息发送；这些必须另行授权。
