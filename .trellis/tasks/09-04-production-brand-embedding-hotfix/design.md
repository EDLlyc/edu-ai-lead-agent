# 生产品牌 Embedding 热修复设计

## 1. Provider resolution

品牌文本 RAG 保持独立配置入口，但复用成熟 provider transport：

```text
BRAND_EMBEDDING_PROVIDER_MODE
  explicit disabled/fake/zhipu/alibaba -> exact mode, fail closed on invalid prerequisites
  auto:
    AI=fake                         -> fake
    visual provider=alibaba        -> alibaba
    AI=zhipu                       -> zhipu
    otherwise                      -> disabled
```

Alibaba 优先级保留当前 `auto` 语义，避免已迁移到共享图文向量空间的环境被热修复意外切回智谱；生产当前
视觉 provider 为 disabled，因此会落到 zhipu。本次保持受保护的生产 `.env` 不变并读回 resolved identity；
显式固定 `zhipu` 留给后续原子配置发布，避免在镜像回滚之外新增配置回滚边界。

## 2. Adapter and identity

`create_brand_embedding_model()` 的 zhipu 分支使用：

```text
ZhipuEmbeddingModel
  -> GovernanceEmbeddingBrandAdapter
  -> BrandEmbeddingResult(provider=zhipu, model=embedding-3, vector[2048])
```

不增加第二套智谱 HTTP 协议实现。已有 adapter 继续负责 HTTPS/base URL、凭据、输入上限、超时、并发、
重试、响应大小/结构和固定维度校验；brand adapter 只做 application port 映射。repository 继续用
provider + model + dimension + input-version 做严格检索过滤。

## 3. Owned-client wiring

- API：按 resolved brand provider 分别创建/关闭智谱 brand client 或 Alibaba visual client；不共享生命周期
  不清晰的临时 client。
- content worker：智谱 brand embedding 复用 worker 已拥有的智谱 client；Alibaba 使用 visual client。
- reindex、MCP、eval 已传入通用 owned client，只需 factory 支持 zhipu，并增加回归测试。
- fake/disabled 不创建网络 client。

## 4. Fail-fast contract

Provider-free selection 是合法模式，不能笼统要求所有 content worker 都配置 embedding。门禁只绑定明确的
自动投递意图：

```text
WECOM_AUTO_DELIVERY_ENABLED=true
  -> WECOM_ENABLED=true                  (existing)
  -> CONTENT_ENABLED=true
  -> CONTENT_WORKER_ENABLED=true
  -> AI_PROVIDER_MODE in {fake, zhipu}
  -> resolved brand provider in {fake, zhipu, alibaba}
  -> each selected provider's credentials/identity validation passes
```

这样本地默认和纯选题任务仍 provider-free；生产自动发送则无法以“copy 永远不可用”的配置启动。
Compose 只向 content worker 投影派生的 `CONTENT_COPY_PROVIDER_REQUIRED`，使 Settings 可以在不向该进程
扩散企业微信凭据的前提下执行相同门禁；doctor 要求这个投影与 API/dispatcher 的自动投递标志完全一致，
并对 Compose 展开后的共享 provider 配置做同一判定，防止单个 service env 漂移。

## 5. Production release and proof

生产当前的 `40e4dec0ae82569fc798355d4515ab0009697c6f` 来自
`feature/wechat-weekly-scheduler-production`，与当前 `main` 在 `4fbab01` 后分叉；它不是当前
`main` 的祖先。直接发布 `main` 会同时带入大量 Reviewer/IP/eval 运行时变化，并移除生产分支仍在使用的
weekly production 模块，因此不属于本次授权范围。

热修复在 `main` 保留可追溯提交，同时从生产分支最新只含文档加固的 `a4a3c00` 创建新的非强推
`release/brand-embedding-hotfix-20260904`，只移植本次运行时 hunks。发布前必须证明：

- 新 release commit 是 `40e4dec…` 的后代；
- `40e4dec…..release` 的应用运行时 diff 仅包含审核过的 embedding/config/wiring/doctor 变更；
- weekly scheduler/worker、12-service 拓扑、migration head 和现有 default-off flags 未被删除或改义；
- Codeup 与 GitHub 上的 hotfix ref 指向同一 commit，且无 force push。

本机和项目当前没有配置可用的 OCI registry repository；生产现有 weekly release 也使用已校验的离线
镜像归档。因此本次不伪造 registry gate，而是按 `quality-guidelines.md` 的 task-authorized offline
contract 新建本任务专属 builder、纯 validator、一次性 root operator 和 fake harness。它们绑定 fetched
Codeup release ref、完整镜像归档图、source manifest、生产 baseline、12 个应用服务、相同 Alembic head、
零发送计数以及回滚证据；不得复用旧任务 operator。

生产 `.env` 属于 release 事务之外的受保护 secret/config 状态。只读现场核验确认它是 physical regular file，
身份为 `0600 / uid=1000 / gid=1001`；capture 只接受并把这一已审核身份与 bytes checksum 一起写入 baseline，
不允许从任意现场 owner 动态放宽契约。capture 首尾以及 operator 每次复核均通过 `O_NOFOLLOW` 打开的单一
文件描述符生成稳定指纹，拒绝 symlink、读取期元数据变化和路径替换，避免把不同 inode 的 bytes/metadata
拼成一个 baseline。operator 在锁前、锁内、quiesce 后、迁移/服务启动前、回滚恢复后和最终验证阶段都必须
同时匹配 bytes/mode/uid/gid，备份和同文件系统原子恢复也必须保持该身份。当前 `auto` 在本修复后确定解析为
`zhipu/embedding-3/2048`，本次保留原始 `.env` 不变并验证 resolved identity，避免在镜像回滚之外制造第二个
配置回滚边界。显式 pin 改为后续 registry-backed 配置发布项。

```text
local tests + check
  -> hotfix-only commit
  -> main commit push + production-descendant hotfix ref
  -> task-local offline builder/validator/operator + fake harness
  -> immutable linux/amd64 image archive + source manifest
  -> production baseline/drift/zero-send preflight
  -> atomic activation of all 12 application services (raw .env unchanged)
  -> migrate/no-op schema check
  -> bounded embedding smoke (one request, no persistence)
  -> health + release identity + resolved-provider readback
```

不手动 enqueue 内容任务，不重放历史 terminal run，不调用企业微信 provider。下一条自然调度任务才是端到端
业务恢复证据；在其到来前，只声明 embedding/provider 与 worker readiness 已恢复，不虚构“新闻已送达”。

## 6. Dirty-worktree isolation

相关文件已有其他任务的未提交变更。实现时逐文件记录 pre-existing diff，补丁只追加本任务最小 hunk；验证后
生成/stage hotfix 专属 patch，不把 topic-rerank、Reviewer、报告等无关 WIP 带入提交。若某一必要 hunk 无法
安全拆分，则停止提交并报告冲突，而不是覆盖或回退他人工作。
