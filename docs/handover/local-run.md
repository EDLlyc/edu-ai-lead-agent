# 项目本地运行操作手册

在自己电脑上把项目跑起来，用来改代码和测试。本地的数据库、对象存储都是自己的，和线上无关。

## 先准备

- Conda
- Docker 29 以上，Docker Compose 2.40 以上
- Node.js 20.19 以上
- Make、Bash、curl

## 第一次：初始化

```bash
conda env create -f environment.yml
conda activate edu-ai
make env-init setup infra-up migrate seed-sources doctor
```

这一行依次做了：

| 命令                | 做什么                                                 |
| ------------------- | ------------------------------------------------------ |
| `make env-init`     | 把 `.env.example` 复制成 `.env`。`.env` 已经有就不动。 |
| `make setup`        | 装后端依赖和前端依赖。                                 |
| `make infra-up`     | 启动本地数据库（Postgres）和对象存储（MinIO）。        |
| `make migrate`      | 建数据库表。                                           |
| `make seed-sources` | 写入内置的新闻源。                                     |
| `make doctor`       | 检查环境是否齐全。                                     |

**不要把线上的 `.env` 拷到本地。** `.env.example` 里发消息和调模型的开关都是关的（`WECOM_ENABLED`、`WECHAT_MP_ENABLED`、`IMAGE_ENABLED` 为 `false`，`AI_PROVIDER_MODE` 为 `disabled`）。本地调试就用这份默认值。不要填线上的企业微信地址、公众号密钥和模型密钥，否则本地跑起来可能真的发出去、真的扣费。

> 当前开发机上的 `.env` 里已经填了真实密钥。交接时不要把它发给对方，让对方用 `.env.example` 自己生成。

## 启动

```bash
make stack-up
```

会构建并启动：数据库、对象存储、建表、后台接口、采集调度和采集进程。

| 服务     | 本地地址                    |
| -------- | --------------------------- |
| 后台接口 | http://127.0.0.1:8000       |
| Postgres | 127.0.0.1:5432              |
| MinIO    | 127.0.0.1:9000，控制台 9001 |

确认起来了：

```bash
curl http://127.0.0.1:8000/healthz
make infra-status
```

## 打开运营后台

另开一个终端：

```bash
cd frontend
npm run dev
```

浏览器打开 http://127.0.0.1:5173/admin/ 。后台页面会把 `/api/v1/admin` 转到本地的 8000 端口。

## 建一个本地后台账号

第一次进后台需要一个账号。激活环境后在 `backend` 目录执行，密码在提示里输入两遍，不会显示：

```bash
cd backend
python -m app.admin_users_main create admin --name 管理员 --role owner
```

- 角色有两种：`owner`（所有者，能管账号、密钥、操作记录）和 `editor`（编辑）。
- 不要用 `conda run` 跑这条命令，它不转发键盘输入。
- 密码要求：8 到 128 位，不能是最常见的弱密码，不能全是同一个字符，不能和用户名一样。
- 连续输错 5 次，账号锁 15 分钟。

## 改完怎么检查

| 命令                   | 检查什么                                                     |
| ---------------------- | ------------------------------------------------------------ |
| `make backend-check`   | 后端格式、静态检查、类型、测试                               |
| `make frontend-check`  | 前端格式、静态检查、类型、测试、打包，以及接口文件有没有对上 |
| `make check`           | 上面两个一起                                                 |
| `make predeploy-check` | 发布前总检查，约 5 分钟，不调模型                            |

改了后端接口之后，要重新生成接口文件，并让前端类型跟上：

```bash
make api-generate
make api-contract-check
```

集成测试要用本地数据库和对象存储，先确认 `make infra-up` 已经启动。

## 停止

```bash
make infra-down
```

会停掉本地容器，数据保留（不会删数据卷）。下次 `make stack-up` 接着用。

## 常见问题

| 现象                        | 做法                                                                                                                           |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| 端口被占用                  | 改 `.env` 里的 `POSTGRES_PORT`、`APP_PORT` 等。改了 `APP_PORT` 要同时改 `VITE_API_BASE_URL`。                                  |
| `make doctor` 说服务不健康  | `make infra-logs` 看数据库和对象存储的日志。                                                                                   |
| 登录后台提示被拒绝          | 用户名或密码不对、账号被停用、被锁 15 分钟，页面都是同一句提示。让所有者在「账号管理」里重置，或者用上面的命令重新设一个密码。 |
| 浏览器里登录不上，没有报错  | 确认 `.env` 里 `APP_ENV=development`。这样本地用 http 也能带上登录凭证。                                                       |
| 想试内容、企微、模型        | 这些默认关闭。需要时只开自己要试的那一项，并用测试用的地址和密钥。                                                             |
| `conda activate` 找不到环境 | 先 `conda env create -f environment.yml`。                                                                                     |
