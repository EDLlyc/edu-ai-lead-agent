# 云效 Codeup / Flow / ACR 预检（2026-08-14）

## CLI 实证

- 官方 Alibaba Cloud CLI `3.4.11` 与 `aliyun-cli-devops 0.7.2` 已安装在当前开发环境。
- 用户 PAT 可访问单一组织“赛先生科学”。
- Codeup 私有代码组 `marketingUseOnly` 存在，ID 为 `2071662`，当前仓库数为 0。
- Flow 可列出 23 条组织流水线，但读取任一现有流水线详情均返回 `403 InvalidPipeline.NotHavePipelinePermission`，证明目录可见不等于资源操作权限。
- Flow 可列出 1 个 ACR 服务连接：`sxsstem的容器镜像服务(ACR)服务连接`，ID 为 `79934`。
- Flow 当前没有 GitHub 服务连接；GitHub 单向备份需要新增仅覆盖目标仓库的最小权限身份。
- Flow 当前主机组数量为 0。
- 生产服务器公网 IP 位于腾讯 AS45090 宣告的网段，可确认是腾讯云网络而非阿里云 ECS；公网注册信息不能进一步区分 CVM 与轻量应用服务器。
- PAT 仅通过进程环境临时使用，未写入阿里云 CLI 配置、仓库或日志文件。

## 官方能力边界

- 云效 Flow 服务连接支持 ACR、Codeup、ECS 等资源，并可限定成员可见范围：<https://help.aliyun.com/zh/yunxiao/user-guide/service-connection/>
- Flow 支持托管构建集群和接入自有服务器的私有构建集群；自有主机 Runner 是常驻进程：<https://help.aliyun.com/zh/yunxiao/user-guide/build-a-cluster>
- 非阿里云 ECS 可通过手动安装 Runner 接入私网/自有环境：<https://help.aliyun.com/zh/yunxiao/user-guide/how-to-use-cloud-efficiency-pipeline-for-ci-cd-in-private-network-environment>
- Flow 官方支持从代码仓库构建 Docker 镜像并推送 ACR；托管构建集群经公网推送时需要 ACR 白名单，私有/VPC 构建可走内网：<https://help.aliyun.com/zh/yunxiao/user-guide/build-image-and-push-to-acr>
- Codeup 内建“仓库同步”是从外部代码库强制覆盖同步到 Codeup，不能用于本任务要求的
  Codeup→GitHub 单向备份：<https://help.aliyun.com/zh/yunxiao/user-guide/warehouse-synchronization/>
- 官方建议迁移已有 Git 仓库时使用 bare clone / mirror push 保留全部分支与标签：
  <https://help.aliyun.com/zh/yunxiao/user-guide/code-base-usage-issues/>

## 规划结论

- Codeup 作为权威主仓库，GitHub 只做单向备份。
- CI/镜像构建不在生产服务器执行；生产服务器只承担按 digest 拉取、备份、迁移、重建和验收。
- 优先复用 ACR 服务连接 `79934`，前提是管理员确认使用范围并提供目标 ACR 实例/地域/命名空间。
- 生产接入不得复用聊天中出现的服务器口令；应使用云效 Runner 或独立最小权限部署身份，并保留移除/回滚步骤。
