# 本地新闻采集重跑结果

## 结论

- 本地 manual acquisition run `3cd3f220-ef30-43e6-aaae-afa7cc261242` 已自然进入 `succeeded`。
- 唯一幂等键为 `local-rerun-20260820-78e41ac9`；数据库只读核对显示该键与 run 的匹配记录为 1。
- 正式 API 仅收到一次创建请求；未执行整轮重试、重放或 requeue。
- 10 个启用来源全部成功，每个 job 的 `attempt_count` 均为 1，失败数为 0。
- 总计：`new=3`、`unchanged=30`、`duplicate=0`、`filtered=42`。

## 来源结果

| 来源 | 状态 | 尝试 | 新增 | 未变化 | 重复 | 过滤 | 错误 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `bnu-news` | succeeded | 1 | 0 | 1 | 0 | 0 | — |
| `cas-research` | succeeded | 1 | 0 | 9 | 0 | 1 | — |
| `china-government-policy` | succeeded | 1 | 0 | 1 | 0 | 0 | — |
| `chinanews-education` | succeeded | 1 | 0 | 3 | 0 | 7 | — |
| `gmw-education` | succeeded | 1 | 1 | 4 | 0 | 5 | — |
| `moe-science-news` | succeeded | 1 | 0 | 2 | 0 | 8 | — |
| `sensetime-news` | succeeded | 1 | 0 | 1 | 0 | 3 | — |
| `stdaily-tech` | succeeded | 1 | 2 | 2 | 0 | 5 | — |
| `xinhua-education` | succeeded | 1 | 0 | 2 | 0 | 8 | — |
| `xinhua-tech` | succeeded | 1 | 0 | 5 | 0 | 5 | — |

## 时间与版本

- 采集版本：`acquisition-v6-broad-hard-tech`
- 创建：`2026-08-20T07:05:37.227474Z`
- 开始：`2026-08-20T07:05:38.402107Z`
- 完成：`2026-08-20T07:06:59.936412Z`
- 数据库迁移前置检查：`20260818_0022 (head)`
- PostgreSQL 与 MinIO 前置健康检查均通过。

## 下游零增量证据

| 对象 | 执行前 | 执行后 | 增量 |
| --- | ---: | ---: | ---: |
| governance runs | 28 | 28 | 0 |
| topic-selection runs | 11 | 11 | 0 |
| content-slot runs | 0 | 0 | 0 |
| copy-generation runs | 33 | 33 | 0 |
| image artifacts | 26 | 26 | 0 |
| material packages | 26 | 26 | 0 |
| WeCom delivery jobs | 8 | 8 | 0 |
| model invocations | 352 | 352 | 0 |

因此本次没有治理、选题、智谱排序、文案、图片/OCR、物料包或推送活动。

## 清理

- 仅启动了 loopback API（服务 PID `55615`）与 acquisition worker（服务 PID `55941`），完成后通过各自受控会话发送中断并正常关闭。
- 清理后 `127.0.0.1:8000` 无监听进程，API、acquisition worker、governance worker、content worker 均无残留。
- 全局 non-terminal acquisition job 数为 0。
- 未连接生产服务器，未执行 SSH、部署、提交或推送；未修改产品代码、配置或用户报告文件。
