# 本机 MCP 工具（运维只读 + 文案修复）

三个 MCP 服务都在本机运行，通过标准输入输出和 Claude Code 通信，服务器上不开任何端口。

| 服务 | 工具 | 数据 |
|---|---|---|
| `ops` | list_slot_runs、list_copy_runs、get_copy_run、list_deliveries、get_day_trace | 生产库，只读账号 + SSH 通道 |
| `repair` | check_draft、find_evidence、replace_claim、drop_claim、rewrite_hook | 内置样例稿，或 `--copy-run-id` 指定的真实草稿；改动只在内存里 |
| `workbench` | get_event、search_evidence、retrieve_brand_context、validate_copy | 内置样例数据 |

## 安全设计

- **专用只读账号 `edu_ai_ops_ro`。** 只对需要的表有 SELECT 权限，发送表按列授权，不含接收人。
  账号不能建表、不能建临时表、不能继承其他角色。默认只读事务，语句超时 5 秒，最多 4 个连接。
- **两道保险。** 即使在会话里关掉"默认只读"，没有写权限照样写不进去，这一点已实测。
- **密码只在本机生成。** 发给数据库的是 SCRAM 校验值，明文密码不经过服务器。
  连接串存在 `~/.config/edu-ai/ops-db.<target>.env`，权限 0600，不进仓库。
- **启动前自检。** 服务先检查账号：是超级用户，或者能写、能建表时，拒绝启动。
- **数据库端口不对外。** 生产库只在服务器的 127.0.0.1:5432 上监听，本机通过 SSH 通道转发到 127.0.0.1:15432。
- **调用有记录。** 每次调用在 stderr 记一行 JSON，不含原始参数。每个进程有调用次数上限，用 `AGENT_MCP_MAX_CALLS` 设置，默认 200。

## 第一次使用

```bash
# 1. 建只读账号（可重复执行；--rotate 换新密码）
python scripts/ops/ops_readonly_role.py --target production

# 2. 开 SSH 通道（保持这个终端开着）
scripts/ops/ops_db_tunnel.sh

# 3. 在 Claude Code 里注册
claude mcp add edu-ops -- /root/projects/edu-ai-lead-agent/scripts/ops/run_mcp.sh ops
claude mcp add edu-repair -- /root/projects/edu-ai-lead-agent/scripts/ops/run_mcp.sh repair
```

修真实草稿：先用 `ops` 的 list_copy_runs 找到 run_id，再这样启动：
`scripts/ops/run_mcp.sh repair --copy-run-id <run_id>`（一次只处理一份草稿）。

本机开发库可以用 `--target local` 和 `OPS_TARGET=local`，但本机数据停在 8 月，只适合测试。

## 全链路追踪看板

和 `ops` 的 get_day_trace 用同一个读取器，生成一个独立的 HTML 文件：

```bash
set -a; . ~/.config/edu-ai/ops-db.production.env; set +a   # 需要 SSH 通道开着
cd backend && python -m app.ops_trace_report_main --days 3 --output /tmp/trace.html
```

- 每条推送从选题重排到发送的时间线，以及每个环节的模型、调用、token、耗时和状态。
- 当天按环节和模型汇总，给出 p50/p95 耗时。
- 成本只在给了 `--prices`（JSON：`{"模型": {"input": 元每百万, "output": 元每百万}}`）时才算，不估价。

## 修复 Agent 影子模式（服务器定时任务）

- 每天 21:10 由 `/etc/cron.d/edu-ai-copy-repair-shadow` 运行 `/usr/local/sbin/edu-ai-copy-repair-shadow`。
  脚本源文件在 `scripts/ops/server/`。
- 它取昨天和今天生产上被拦下、做过整篇重写的草稿，让修复 Agent 在后台修同一份被拦稿，
  再过同样的规则和该任务当时的审查版本，每份写一行 JSON，和生产结果并排。
- 线上发出去的内容不受影响：不改任何数据，不重启任何服务，用固定镜像跑一次性容器。
  数据库只经只读账号读取，每次最多 120 次模型调用。
- 结果在服务器 `/opt/edu-ai-lead-agent/reports/copy-repair-shadow/`，`summary.md` 是累计汇总。

## 撤销

```sql
REASSIGN OWNED BY edu_ai_ops_ro TO edu_ai;
DROP OWNED BY edu_ai_ops_ro;
DROP ROLE edu_ai_ops_ro;
```
