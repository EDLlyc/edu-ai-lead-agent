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

审核构建机的 Docker client/server 为 29.1.3，本地 daemon 使用
`io.containerd.snapshotter.v1`，`ctr 2.2.1` 可读同一 `moby` namespace，但没有 buildx CLI plugin。builder
因此在构建前选择且锁定一条路径：`docker buildx version` 成功时执行原 buildx OCI output；只有输出明确为
命令不存在时才进入 legacy 预检。其他 buildx probe 错误或选定路径后的任何构建错误直接终止，不做运行期
fallback。

legacy 预检固定本地 Unix Docker socket、`/run/containerd/containerd.sock` server、linux/amd64 daemon、
containerd snapshotter、moby namespace、
`docker build --pull/--platform/--tag` 与 `ctr images export --skip-manifest-json/--platform` 能力。构建使用
`DOCKER_BUILDKIT=0 docker build --pull --platform linux/amd64` 和 buildx 相同的 commit/source/created args 与
唯一 transport tag，再从 moby 精确导出 Docker-normalized reference。纯 Python canonicalizer 对原始 tar 做
两遍有界校验与复制，只接受 root-owned regular members、单 OCI manifest、完整 config/layer graph、匹配
blob digest、标准化 name annotation 和短 ref annotation；它把 Docker gzip/uncompressed layer media type
映射为 OCI 等价类型，保持 config/layer bytes，重算 canonical manifest/index 并原子生成确定性安全 tar。
旧 manifest 不进入新 graph；nested index、dangling blob、链接、重复项、digest/diff-ID/platform/user 漂移
全部拒绝。其输出继续走原有 derive、严格 validator、`docker load`/RepoDigest、network-none probes；临时归档
和本次新建的 candidate tag/reference 在成功与失败路径都清理；构建前记录已有 RepoDigest，清理不得移除
先存引用。

真实 release 镜像复现证明失配不是 Docker 把 OCI layer media type 改回 Docker media type：旧 canonical index
错误地把未规范化 full tag 同时写入 name/ref-name，`docker image load` 返回成功却没有创建 transport tag；此时
后续 inspect 读到的是 legacy build 留下的 raw tag。修复后 index 固定为 containerd-normalized full name 与
short ref-name，严格 validator 从 metadata 独立推导并逐项匹配。legacy 路径还会在严格图验证后、load 前只
删除本次预检后创建的 raw tag，并确认 tag 已消失；fresh load 必须重新创建 tag、精确 RepoDigest 与已验证
manifest/config ID，不能借用 stale local identity。真实 11-layer release 归档 fresh-load 后 `.Id` 与 canonical
manifest digest 完全相同，重新 export 的 layer media types 也保持 OCI。

`docker image inspect .Id` 不是跨 image store 固定为 config digest：classic store 返回 config digest，而审核构建
机的 Docker 29.1.3/containerd image store 对单 manifest OCI 返回 manifest digest。builder 与 operator 因此只
接受严格 validator 已绑定 graph 中的 manifest/config digest 二选一，再要求 transport tag 的 RepoDigests 包含
精确 manifest reference、该 reference inspect 返回相同运行时 ID。operator 保存这次实际加载 ID，并用它核验
12 个应用容器的 `.Image`；不把任意第三个 digest 当作兼容值，也不放宽 OCI validator。

candidate 首次真实 source probe 的失败来自命令参数转义，而不是镜像内容：builder 传入容器内 Python 的
`-c` 参数使用了双重转义换行，导致每条正确摘要之间写出字面量 `\n`，严格字节比较因此安全终止。probe 现改为
先生成完整、排序后的逐文件行，再用 `chr(10)` 分隔并由 `print` 写入终止换行，避开 shell/Python 双层转义；
回归测试捕获真实 `-c` argv 并执行，要求输出行数、顺序、path 与 SHA-256 全部精确相等。完整 app/alembic
`.py/.html`、`alembic.ini` 与 `pyproject.toml` 范围不变；worktree 与 image probe 均在生成记录前拒绝
非 canonical ASCII safe path，阻止换行或制表符文件名注入记录，validator 和 `cmp` 均不放宽。

第四次真实 authority build 已通过 OCI graph、fresh load、双 image identity 和 298-file source manifest，最终
stage 校验仍安全终止。聚合复现确认 builder 早期通过 `importlib` 从 stage 导入 validator 时，CPython 自动新增
了 `__pycache__/validate-brand-embedding-hotfix-offline-artifacts.cpython-311.pyc`；额外目录正是精确 member-set
失败原因，不是归档或权限漂移。早期 baseline helper 现用 Python `-B` 执行同一真实 validator，禁止在 stage
写 bytecode；回归测试实际复制并导入 validator，比较调用前后的顶层成员集合并要求 `__pycache__` 不存在。
最终 validator 继续拒绝任何额外成员、非 regular file、非 root owner、非 `0600` 或超限文件，不增加清理未知
成员的逻辑。

第五次真实 authority build 证明 baseline import 修复后仍有第二个同类写入边界：OCI archive 生成后，
`validate_candidate_image_graph` 在 load 前通过另一段 `importlib` 再次导入 staged validator，外部只读观察捕获
到该调用新增 mode-`0700` 的 `__pycache__` 目录及 mode-`0600` 的 validator pyc，均为 `root:root`；其余固定成员
类型、mode 与 owner 未漂移。该 helper 同样固定使用 Python `-B`，不删除或忽略生成物；真实完整 stage 回归在
有效和 dangling OCI graph 两条路径上比较递归成员集合，证明成功与 fail-closed 校验都不再改变 stage。所有
staged validator 的直接执行也统一固定 `-B`，并由回归测试枚举 invocation，避免后续新增第三个 bytecode 写入边界。

生产 `.env` 属于 release 事务之外的受保护 secret/config 状态。只读现场核验确认它是 physical regular file，
身份为 `0600 / uid=1000 / gid=1001`；capture 只接受并把这一已审核身份与 bytes checksum 一起写入 baseline，
不允许从任意现场 owner 动态放宽契约。capture 首尾以及 operator 每次复核均通过 `O_NOFOLLOW` 打开的单一
文件描述符生成稳定指纹，拒绝 symlink、读取期元数据变化和路径替换，避免把不同 inode 的 bytes/metadata
拼成一个 baseline。operator 在锁前、锁内、quiesce 后、迁移/服务启动前、回滚恢复后和最终验证阶段都必须
同时匹配 bytes/mode/uid/gid，备份和同文件系统原子恢复也必须保持该身份。当前 `auto` 在本修复后确定解析为
`zhipu/embedding-3/2048`，本次保留原始 `.env` 不变并验证 resolved identity，避免在镜像回滚之外制造第二个
配置回滚边界。显式 pin 改为后续 registry-backed 配置发布项。

生产只读 capture 还确认 7 条旧 `queued/attempt_count=0` copy job 的业务日期均早于当前日期。真实 `_claim`
只查询 `run.business_date == Asia/Shanghai 当天`、`queued/retry_scheduled`、已到 `available_at` 且 attempt
小于 3 的任务，因此不能把这 7 条冻结记录误算成发布必须清零的实时 pending。baseline 固定时区、业务日期、
max-attempts，并要求 exact-claimable、全局 running、当天 queued/running/retry 和未来 queued/retry 全为 0。
冻结 cohort 以严格排序的 `job id/run id/status/business_date/attempt_count/available_at` canonical rows 计算
`count=7 + sha256`；首次 capture 还逐项匹配已审核的七个业务日期、`queued` 与 `attempt_count=0`，不能将
capture 前的同数量状态漂移重新确认为 baseline。输出与日志只出现聚合和摘要。operator 在锁前、锁内、
quiesce 后、迁移前、启动前、最终及回滚服务重启前后重新计算；日期跨界、cohort 增删改或任何实时可执行
copy 状态均 fail closed，绝不通过 DML “修正”现场数据。

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
