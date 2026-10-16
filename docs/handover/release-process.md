# 项目发版操作流程

这份写的是我们实际在用的做法：给线上正在跑的镜像打补丁，只重建受影响的容器。镜像是服务器上的一份固定模板，容器是按它跑起来的程序。补丁打在镜像上，不是进容器里改文件。

示例用的是 2026-10-16 的“采集：读不出的页面跳过”。脚本都在 `.trellis/tasks/10-15-public-hosting/overlay-acquisition-skip/`，发新版时复制最近一个目录来改。

## 0. 开始之前

1. 代码在本地 `mainline` 上改完、测完（见 [本地运行手册](./local-run.md) 的“改完怎么检查”）。
2. 跑发布前检查，把最后一行 `predeploy gate PASS @ <提交号> …` 记进发布记录。没通过不发：

   ```bash
   make predeploy-check
   ```

3. 看清线上现在是什么。镜像是一层层叠出来的，不能凭提交记录猜：

   ```bash
   ssh edu-ai-production
   sudo docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
   ```

   登不上去先看 [交接文档](../operations/handover.md) 第 2 节和 [账号与密码](./accounts-and-passwords.md)。

4. 选时间。内容相关服务（写稿、选题、长图）在北京时间 05:55–06:40、10:55–11:40、16:55–17:40 不要重启。只改采集的话，脚本会等正在跑的采集任务结束再动。

## 1. 本地：准备改动

- 后端：确认改过哪些文件，记下它们。
- 后台页面有改动的话，在 `frontend/` 里打包：

  ```bash
  VITE_ADMIN_DATA_MODE=production \
  VITE_API_BASE_URL=https://ops.xiaosaiai.com \
  VITE_EXHIBIT_ENTRY_URL=https://pgc.xiaosaiai.com/ \
  npm run build:admin
  ```

  产物在 `frontend/dist-admin/`，里面是 `admin/index.html` 和 `assets/`。记下新 JS 的文件名，比如 `index-AdbYLP1T.js`。

## 2. 补丁目录里放什么

复制最近的 `overlay-*` 目录，改成这几样：

| 文件                    | 作用                                                                      |
| ----------------------- | ------------------------------------------------------------------------- |
| `Dockerfile`            | `FROM` 线上现在的镜像摘要，再 `COPY` 改过的文件。                         |
| `base-hashes.txt`       | 改之前线上那几个文件的指纹（前 8 位）。构建前会核对，防止盖掉别人的改动。 |
| `smoke.py`              | 断网试跑用的小检查，确认新代码能被导入、入口还在。                        |
| `remote-build-smoke.sh` | 在服务器上构建并试跑。                                                    |
| `activate.sh`           | 真正替换容器。里面写死了“预期的旧镜像”和“要重建的服务”。                  |
| `tree/…`                | 要覆盖进去的文件，路径和镜像里一致。                                      |

取线上文件指纹：

```bash
sudo docker exec <容器名> sha256sum /app/<文件路径> | cut -c1-8
```

## 3. 上传、构建、试跑（不影响线上）

```bash
rsync -az <补丁目录>/ edu-ai-production:/tmp/<名字>/
rsync -az frontend/dist-admin/ edu-ai-production:/tmp/<名字>-dist/
ssh edu-ai-production 'sudo FIX_COMMIT=<提交号或标签> bash /tmp/<名字>/remote-build-smoke.sh /tmp/<名字>'
```

脚本做的事：确认容器现在用的正是预期的旧镜像；核对文件指纹；断网构建新镜像；再用“断网、只读、去掉所有权限”的临时容器跑 `smoke.py`。最后一行是 `build_smoke_ok … image_id=sha256:…`，记下这个镜像编号。没看到这一行就不要往下。

## 4. 激活

```bash
ssh edu-ai-production 'sudo bash <暂存目录>/activate.sh <备份目录> <镜像编号> /tmp/<名字>-dist <新JS文件名>'
```

脚本按顺序做：

1. 确认线上镜像是预期的旧版本，不是就中止。
2. 等待：没有正在跑的采集任务；内容服务另外避开上面三个时段。
3. 备份编排文件、`.env`、`.release.env` 和后台静态文件。
4. 记下这个服务的环境变量哈希。
5. 只重建要换的那个服务。
6. 检查：在运行、镜像是新的、环境哈希前后一致、重启 0 次、日志没有 `Traceback` 或 `CRITICAL`。
7. 整体替换后台静态文件。
8. 用 `curl` 检查：`/admin/` 返回 200，新 JS 返回 200，没登录访问管理接口返回 401。
9. 任何一步失败，自动退回旧镜像并恢复后台文件。

成功时最后一行是 `…_activated image=… backup=…`。

## 5. 发完确认

```bash
sudo docker inspect <容器名> --format '{{.Image}} {{.State.Status}} restarts={{.RestartCount}}'
sudo docker ps --format '{{.Names}}' | wc -l       # 应为 17
sudo docker logs --since 5m <容器名> 2>&1 | grep -ciE 'Traceback|CRITICAL'   # 应为 0
curl -s https://ops.xiaosaiai.com/admin/ | grep -o 'index-[A-Za-z0-9_-]*\.js'  # 应是新文件名
```

## 6. 回滚

脚本失败会自动回滚。事后要手动退回时，换回旧镜像再重建那一个服务：

```bash
cd /opt/edu-ai-lead-agent
export CONTENT_SCORING_VERSION=<这个服务当初创建时的值>
APP_IMAGE="offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:<旧镜像>" \
  docker compose -p edu-ai-lead-agent --env-file .env --env-file .release.env \
  up -d --no-deps --no-build --pull never --force-recreate <服务名>
```

后台页面：把当次备份目录里的 `www.before` 拷回 `/var/www/edu-ai-admin`。

有数据库迁移的发布（例如系统内置词）要多做一步：先在新镜像的接口容器里把迁移退回上一版（`alembic -c alembic.ini downgrade <上一版本号>`），再换镜像。启动前用 `pg_dump` 备份过，参考 `overlay-builtin-phrases/activate.sh`。不要拿一份旧备份去回滚后来的发布。

旧镜像不会自动删，所以回滚很快。每次发布的备份目录和回滚命令记在 [公网托管记录](../../.trellis/tasks/10-15-public-hosting/runbook.md)。

## 7. 事后

1. 把镜像编号、备份目录、回滚方法写进公网托管记录和 [生产主线说明](../../.trellis/spec/guides/production-mainline.md)。
2. 代码提交并推到 Codeup 的 `mainline`。

## 容易踩的坑

| 现象                               | 原因和做法                                                                                                                                  |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| 环境哈希对不上，脚本回滚           | 重建会重读当前 `.env`，各服务创建时间不同，`CONTENT_SCORING_VERSION` 不一样。重建前先记下这个服务现在的值，用 `export` 钉住，重建后再对比。 |
| 脚本回滚了，但后面的步骤还在继续   | 在 `$(…)` 里写 `grep -c` 时，零匹配返回 1，会在子进程里误触发回滚。写成 `grep -c … \|\| true`。                                             |
| 命令前的 `APP_IMAGE=…` 好像没生效  | 它会盖过 `--env-file`，这是故意的。只想换一两个服务就这么用。`.release.env` 不要改，它跟着后台接口的镜像。                                  |
| 只想换内容服务，却被拉到了接口镜像 | `content-worker`、`content-scheduler`、`wecom-infographic-producer` 不能直接 `docker compose up`，会跳到接口镜像。一定带 `APP_IMAGE`。      |
| 等待超时（`job_wait_timeout`）     | 采集任务跑得久。过一会儿再发，不要强行重启。                                                                                                |
| 提示有孤儿容器                     | 是 `visitor-display`，故意留着。**不要加 `--remove-orphans`。**                                                                             |

## 发版时的底线

- 部署不调用大模型，也不发企微。发到正式群只有后台的「推送到正式群」。
- 每次只动改到的服务。
- 先试跑，再激活，激活有备份。
