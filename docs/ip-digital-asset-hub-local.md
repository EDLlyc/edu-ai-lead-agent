# IP 数字资产中心 MVP：本地与内网运行手册

这个 MVP 提供一个共享图库和独立 AI 视觉创作室：所有使用者都可以上传、分类、检索、预览、收藏、下载赛先生与小赛图片；可选 worker 为图片建立多模态向量。生图结果先进入当前浏览器的个人素材架，只有用户明确点击“加入共享图库”才会进入共享图库。它不会修改现有的静态品牌视觉目录。

## 安全边界

当前版本**没有鉴权、可信账号、部门隔离或删除接口**。浏览器会为收藏和个人素材生成一个随机本地名片，但它没有密码、不能证明员工身份、不能跨设备同步；清除浏览器数据后也无法恢复对应的私有生成素材。只能绑定到 `127.0.0.1`，或放在有网络访问控制的可信公司内网。不得把 API、Vite 开发服务、MinIO API/Console 或 PostgreSQL 暴露到公网。页面中的“部门”和“上传人”是自填描述，不是可信身份信息。

所有开关默认关闭。原件进入私有 MinIO bucket，浏览器只能通过受校验的同源 API 预览和下载；API 不返回对象键或存储凭据。

## 首次启动

安装依赖并创建本地配置：

```bash
make env-init
make setup
make infra-up
make migrate
```

在本地 `.env` 中只打开基础图库：

```dotenv
IP_ASSET_HUB_ENABLED=true
IP_ASSET_WORKER_ENABLED=true
IP_ASSET_GENERATION_ENABLED=false
APP_BROWSER_ORIGINS=http://127.0.0.1:5173
VITE_IP_ASSET_HUB_ENABLED=true
```

启动 API、worker 和前端（分别占用一个终端）：

```bash
make acquisition-api
make ip-asset-worker
make ip-asset-ui
```

也可以让 Compose 启动 API 与 worker：

```bash
make ip-asset-stack-up
make ip-asset-ui
```

打开共享图库 `http://127.0.0.1:5173/ip-assets`，或打开独立创作室 `http://127.0.0.1:5173/ip-assets/create`。两者都不会挂载到根路径的共享开发控制台。能力探针位于 `GET /api/v1/ip-assets/capabilities`；即使 provider 关闭，上传、分类浏览、元数据检索、收藏、个人素材架、预览、单图下载和 ZIP 下载也应可用。

Vite 本地服务会把 `/ip-assets` 深链交给 SPA。正式内网部署时，静态服务器或反向代理也必须把 `/ip-assets`、`/ip-assets/create`（及其尾斜杠形式）回退到前端 `index.html`，同时保留 `/api/` 路径转发给后端；否则直接刷新独立页面会得到服务器 404。

本地 Vite 与 API 使用不同端口，因此 API 只为 `APP_BROWSER_ORIGINS` 中逐个列出的精确来源返回 CORS 响应；禁止配置 `*`。内网部署若不使用同源反向代理，必须把实际 HTTPS/HTTP 前端来源加入这个逗号分隔白名单，并同步设置浏览器可访问的 `VITE_API_BASE_URL`。

## 分类和命名

- 角色：赛先生、小赛、双角色、其他 IP。
- 类型：形象设定、头像、全身动作、表情、表情包、透明底素材、场景插画、海报元素、其他。
- 描述字段：情绪、动作、场景、用途、风格、标签、部门和上传人。
- 系统按元数据分配稳定规范名与版本号；下载文件名使用安全 ASCII 名称。相同 SHA-256 原件重复上传时返回已有资产，不会复制对象。

上传只接受完整解码通过的 PNG、JPEG 或 WebP，单文件最大 25 MiB、最长边最大 8192 像素、总像素最大 3200 万。ZIP 下载最多 50 张、总原件最多 250 MiB，并附带包含校验摘要的 JSON 清单。

## 可选 AI 辅助识别

识别默认关闭，而且只有用户在上传面板选择图片后主动点击“AI 辅助识别”才会调用视觉模型；选择文件和本地预览不会发送图片。模型建议只回填角色、类型、情绪、动作、场景、用途、风格和标签，用户仍需检查或修改后再走原有上传流程。识别不会填写部门或上传人，不会自动上传，也不会创建数据库记录、MinIO 对象或后台任务。

在本地 secret 配置已经提供智谱 HTTPS endpoint 和 API key 后，可显式打开：

```dotenv
IP_ASSET_HUB_ENABLED=true
IP_ASSET_RECOGNITION_ENABLED=true
IP_ASSET_RECOGNITION_MODEL=glm-4.1v-thinking-flash
AI_PROVIDER_MODE=zhipu
AI_PLATFORM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
AI_PLATFORM_API_KEY=<仅保存在本地或部署 secret store>
```

服务端会先校验图片，再将像素重新编码为去元数据、有尺寸和字节上限的瞬态输入。超时、供应商拒绝或无效输出只显示安全错误，当前图片和手动表单仍可继续上传。自动化测试不调用真实供应商；真实验收必须单独授权，并且一次只检查一张非敏感测试图。

## 导入现有已审核图库

先运行 provider-free dry-run；输出只有聚合计数，不打印私有路径或对象键：

```bash
make ip-asset-import-dry-run MAX_ASSETS=500
```

确认清单和备份后再实际导入：

```bash
IP_ASSET_HUB_ENABLED=true \
  conda run --name edu-ai python -m app.ip_asset_import_main --max-assets 500
```

导入通过现有安全清单读取器复制已审核图片，源目录只读且不被改名或修改。重复执行按内容校验和幂等。

## 可选多模态检索

没有向量 provider 时，文本检索会明确降级为分类/关键词结果，以图搜图会返回可读的不可用状态；图库本身继续工作。离线验收可使用 fake adapter：

```dotenv
VISUAL_SEMANTIC_ENABLED=true
VISUAL_EMBEDDING_PROVIDER_MODE=fake
```

真实 embedding 需要显式选择受支持的 adapter，并只在本地 secret store 或权限为 `0600` 的部署 `.env` 中提供 endpoint/key。不要提交密钥。更换 model、dimensions、input policy 后，新旧向量严格隔离；需让 worker 为当前身份补齐索引。

## 可选 1:1 生图

MVP 只支持 provider-neutral 现有请求的 `1:1`、1024×1024 合同。不得在 UI 或 API 中宣称支持 4:3、3:4 等比例，除非先扩展并验证所有生成 adapter。

打开生图必须同时满足：

```dotenv
IP_ASSET_HUB_ENABLED=true
IP_ASSET_WORKER_ENABLED=true
IP_ASSET_GENERATION_ENABLED=true
IP_ASSET_HEARTBEAT_SECONDS=60
IMAGE_ENABLED=true
IMAGE_PROVIDER_MODE=toapis  # 或仓库当前支持的另一个真实 adapter
```

真实 provider 凭据仍只能来自 secret store/部署 `.env`。API 只创建幂等任务；独立 worker 按页面 `01–03` 的顺序读取一至三张已校验共享参考图，校验返回图片后通过与上传相同的不可变路径入库。结果默认只属于当前浏览器本地名片，可在“我的素材架”下载、收藏或明确加入共享图库。默认测试和本地验收不调用真实 provider。

## 本地名片、收藏与下载排行

第一次收藏、查看个人素材或发起创作时，页面要求填写显示名称和部门，并在浏览器生成 32 字节随机 token。后端只保存 token 摘要，浏览器只通过 `X-IP-Profile-Token` 请求头发送 token。不要把 token 复制到 URL、日志或工单；它不是登录凭据，但持有它即可访问该名片的私有生成素材。

普通上传仍会立即进入共享图库；存在本地名片时，它也会出现在“我的上传”。收藏可以随时取消，并不赋予他人私有素材访问权。下载排行只有 30 天和全部两个聚合视图，只保存每个共享资产、业务日期和次数，不保存下载者、IP、User-Agent 或逐次事件。单图/ZIP 原件全部准备成功后才计数，一次请求中的重复资产只计一次。

## 备份、升级与回滚

启用前同时备份 PostgreSQL 数据库和 MinIO bucket。两者必须作为一组恢复：数据库保存资产元数据和任务状态，MinIO 保存不可变原件。

```bash
pg_dump --format=custom --file=edu-ai-before-ip-assets.dump "$POSTGRES_BACKUP_URL"
mc mirror --overwrite local/edu-ai-materials ./backup/edu-ai-materials
```

`POSTGRES_BACKUP_URL` 和 `mc` alias 应由操作者在本机明确配置；不要把凭据写入命令历史或仓库。迁移为 additive，执行 `make migrate` 后用 `alembic -c backend/alembic.ini heads` 获取仓库当前 head，并确认数据库升级到同一版本；本次复核时仓库 head 为 `20260824_0035`，其中 IP 资产基础迁移是 `20260824_0031`，本地名片、个人素材、收藏、有序参考和下载聚合是 `20260824_0035`。

紧急回滚优先关闭访问和 worker，不删除数据：

```dotenv
VITE_IP_ASSET_HUB_ENABLED=false
IP_ASSET_WORKER_ENABLED=false
IP_ASSET_GENERATION_ENABLED=false
IP_ASSET_RECOGNITION_ENABLED=false
IP_ASSET_HUB_ENABLED=false
```

重启前端、API 和 worker 后确认能力探针为 disabled。只在已经验证数据库与 bucket 备份，并确认不存在本地名片、私有资产、名片生成任务、多参考生成记录或下载聚合时，才考虑从 `0035` 降级；迁移检测到这些个人素材功能数据时会拒绝破坏性降级。`0035` 之前已经存在的共享资产不需要为了降级而删除。不要手工删除内容寻址对象。

## 日常检查

```bash
make api-contract-check
conda run --name edu-ai pytest backend/tests/unit/test_ip_assets.py \
  backend/tests/unit/test_ip_asset_recognition.py \
  backend/tests/integration/test_ip_assets.py \
  backend/tests/integration/test_migrations.py --no-cov -q
npm run test --prefix frontend -- --run src/features/ip-assets
make doctor
```

故障排查优先查看结构化错误代码和任务状态。不要记录上传原件、provider 正文、完整提示词、密钥、私有路径或 MinIO 对象键。
