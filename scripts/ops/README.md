# 本机 MCP 工具（运维只读 + 文案修复）

三个 MCP 服务都在本机运行，默认通过标准输入输出和 Claude Code 通信，服务器上不开任何端口。
`ops` 也可以走 Streamable HTTP（只听 127.0.0.1，要带令牌），见下文“HTTP 方式”。

| 服务 | 工具 | 数据 |
|---|---|---|
| `ops` | list_slot_runs、list_copy_runs、get_copy_run、list_deliveries、get_day_trace | 生产库，只读账号 + SSH 通道 |
| `repair` | check_draft、find_evidence、replace_claim、drop_claim、rewrite_hook | 内置样例稿，或 `--copy-run-id` 指定的真实草稿；改动只在内存里 |
| `workbench` | get_event、search_evidence、retrieve_brand_context、validate_copy | 内置样例数据 |

## 安全设计

- **专用只读账号 `edu_ai_ops_ro`。** 只对需要的表有 SELECT 权限，发送表按列授权，不含接收人；
  素材包只开放文案快照（含运营修改记录），不开放品牌快照。
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

### 资源和提示词（ops）

- 资源：`ops://trace/{日期}` 是某天的全链路追踪（和 get_day_trace 相同，也计入调用上限）；
  `ops://server/info` 列出工具、调用上限和版本。
- 提示词：`diagnose_slot(business_date, slot)` 按 选题 → 文案 → 发送 排查某个时段，
  `explain_blocked_copy(run_id)` 解释一条文案为什么被拦，`daily_usage(business_date)` 汇总当天用量。
  在 Claude Code 里输入 `/` 可以看到这些提示词。

### 改稿前确认（repair）

`repair` 的三个改稿工具（replace_claim、drop_claim、rewrite_hook）执行前，会先在一份副本上试改，
再通过 MCP 表单确认（elicitation）把“改前/改后”发给客户端，由你确认：

- 确认：照常修改，结果的 `_meta["edu-ai/confirmation"]` 记为 `accepted`。
- 拒绝或关闭：返回 `operator_declined`（不可重试），草稿不变。
- 工具本来就会拒绝的修改（编号不存在、不是证据原文等）不弹确认，直接返回原来的拒绝原因。
- 客户端不支持表单确认时，按原来的方式直接修改，并记为 `not_supported`；
  想在这种情况下拒绝修改，启动时加 `--require-confirmation`。
- 新协议（2026-07-28）用 `InputRequiredResult` 一问一答，旧协议在调用中途发 `elicitation/create`，
  两种都由 SDK 自动选择，确认的问答不算一次工具调用。

### HTTP 方式（ops）

```bash
# 1. 生成令牌（只做一次，至少 32 个字符）
umask 077; python -c "import secrets; print(secrets.token_urlsafe(32))" > ~/.config/edu-ai/ops-mcp.token

# 2. 启动（需要 SSH 通道开着），默认 http://127.0.0.1:8765/mcp
scripts/ops/run_mcp.sh ops --transport http

# 3. 在 Claude Code 里注册
claude mcp add --transport http edu-ops-http http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer $(cat ~/.config/edu-ai/ops-mcp.token)"
```

- 没有令牌或令牌不对返回 401；令牌只在本机比较，不出现在日志和响应里。不提供 OAuth 发现。
- 只允许监听回环地址（127.0.0.1、localhost、::1），其他地址要显式加 `--allow-remote`，不建议用。
  从别的机器用，保持只听 127.0.0.1，再用 `ssh -L 8765:127.0.0.1:8765 <这台机器>` 转发。
- 启动时检查一次只读账号，不合格就不启动。
- Claude Desktop 用 stdio 方式最简单（配置里写 `run_mcp.sh ops`）；要走 HTTP，需要客户端能带
  `Authorization` 请求头。

## 对话式运维助手

用自然语言问“今天中午的推送发了没”“昨天哪条文案被拦了、为什么”“打开这条帮我改引导语”。
助手自己选工具查询：查询类工具直接执行；改稿先把草稿复制到沙盒；每次修改都先给出改动前后，
等你点“确认执行”或“拒绝”。修改只在沙盒里，线上不会被改，改好的文案复制后到审核页提交。

```bash
scripts/ops/ops_db_tunnel.sh            # 另开一个终端
scripts/ops/run_ops_assistant.sh        # 打开 http://127.0.0.1:4190
```

模型密钥放在 `~/.config/edu-ai/model.env`（0600），建议在智谱后台单独建一个本机工具专用的密钥。
不想在本机放密钥时，可以在服务器一次性容器里用 `python -m app.ops_assistant_main --ask "…"` 跑。

助手是一张 LangGraph 状态图：改稿走到 approval 节点时用 `interrupt()` 暂停，你的确认/拒绝用
`Command(resume=…)` 继续。每段对话是一个 thread（页面顶部显示编号）：

- 想让“等你确认”的修改在重启后还在：设 `OPS_ASSISTANT_CHECKPOINT_URL` 为本机开发库的
  `postgresql://…`（可写；指向只读运维库会被拒绝），重启时加 `--thread <编号>`，页面会恢复待确认卡片。
  不设时检查点只在内存里。草稿正文不进检查点，重启后按“打开的任务 + 已确认的修改”重放出来。
- `OPS_ASSISTANT_TRACE_FILE=/tmp/ops-assistant-trace.jsonl`：每一步记一行（invoke_agent / chat /
  execute_tool，OpenTelemetry GenAI 命名，只有名称、编号、token 和耗时，没有消息内容）；
  装了 opentelemetry 时走它的 tracer。
- 轨迹评测（合成数据，不连线上）：`cd backend && python -m evals.ops_assistant.runner --help`。

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

## Approved actions (diagnosis → approval → execution)

When the watchdog's diagnosis agent suggests a resend, the watchdog writes one proposal per failed
delivery of that slot to `reports/delivery-watchdog/action-proposals.jsonl` and lists them in the
alert. The agent never executes anything. An operator decides on the server:

```
ssh edu-ai-production
sudo edu-ai-ops-action list
sudo edu-ai-ops-action approve <id> --by <name>     # or: reject <id> --by <name>
sudo edu-ai-ops-action verify                       # 10+ minutes after an execution
```

- Only `retry_delivery` exists; the app's own retry re-checks the job's state and window.
- One proposal per target; it expires with the slot's delivery window (target + 60 minutes);
  at most 3 executions per day.
- Propose-only by default: nothing executes until `scripts/ops-actions.env` contains
  `OPS_ACTIONS_ENABLED=true`. Every event (proposed, approved, rejected, executed, failed,
  expired, verified) is appended to the log with who and when.
- Approval is on the server command line on purpose: the local ops assistant only has the
  read-only role, and a web approval would need a new authenticated write endpoint.

