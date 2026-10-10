# Journal - LiYuchen (Part 2)

> Continuation from `journal-1.md` (archived at ~2000 lines)
> Started: 2026-09-17

---



## Session 88: Deploy WeChat marketing-header spacing

**Date**: 2026-09-17
**Task**: Deploy WeChat marketing-header spacing
**Branch**: `release/wechat-two-banner-framing-20260914`

### Summary

Released the versioned Cheng Yue marketing-header body spacer without a schema migration; corrected Compose variable loading during restart and verified the production runtime.

### Main Changes

- Added one WeChat-safe visible line between the V5 marketing header and article cover for newly prepared drafts, with immutable manifest/fingerprint versioning and legacy-byte compatibility.
- Loaded the immutable overlay image on production and restored standard .env-based Compose interpolation while passing the candidate APP_IMAGE explicitly.

### Git Commits

| Hash | Message |
|------|---------|
| `abfb89d` | (see git log) |

### Testing

- [OK] Scoped pytest, Ruff, mypy, HTML validator, isolated image smoke test, production /healthz, 12-container revision checks, schema check, and aggregate draft/article preservation checks passed.

### Status

[OK] **Completed**

### Next Steps

- Existing prepared drafts retain their frozen HTML; newly prepared V5 drafts receive the spacing automatically.


## Session 89: Repair agent, read-only ops tools, auditor v22 and two releases

**Date**: 2026-10-01
**Task**: Repair agent, read-only ops tools, auditor v22 and two releases
**Branch**: `feat/repair-agent-20260930`

### Summary

Built the tool-using copy repair agent on one typed tool registry shared by function calling, MCP and evals; gave tools a SELECT-only production role; ran the agent in nightly shadow; shipped auditor v22 with a brand-repeat check, a delivery watchdog and eval regression; deployed the a8 session's fresh candidate pool and held human picks. Work spans 09-30 evening to 10-01.

### Main Changes

- Repair agent (check_draft, find_evidence, replace_claim, drop_claim, rewrite_hook): eval v3 repairs 25/28 blocked seeded drafts, the same as full regeneration, 28/28 combined, with fewer input tokens per repair.
- Read-only role edu_ai_ops_ro (column grants, TEMP revoked, fail-closed verify), ops MCP servers, day trace dashboard, repair shadow job at 21:10; live 10-01 11:32-11:43 with seven write/privacy probes refused.
- Prompt-injection eval: the generator followed 0 of 30 instructions hidden in evidence. Ops assistant: reads run at once, draft edits wait for operator approval (sandbox only).
- Auditor v22 (closed error codes, system-decided severity): 26/26 vs v21 18/26 on seeded drafts, 0/5 clean blocked; brand-repeat check; delivery watchdog (alerts only to a separate ops webhook); eval repeats and regression; known-failure baseline 28 -> 0. Live 22:30 (image 7bffe4ed).
- Fresh candidate pool + held human picks (release 765fe1e, a8 session) deployed 23:12 (image 5887bce7).

### Git Commits

| Hash | Message |
|------|---------|
| `d15cf11` | (see git log) |
| `42e636e` | (see git log) |
| `4c330d8` | (see git log) |
| `ff70cb8` | (see git log) |
| `c9d12f9` | (see git log) |
| `2236e58` | (see git log) |
| `ae0825a` | (see git log) |
| `a6d5115` | (see git log) |
| `13cf91d` | (see git log) |
| `d9b534b` | (see git log) |
| `fc3e732` | (see git log) |
| `9644d63` | (see git log) |
| `72a4930` | (see git log) |
| `cc958d8` | (see git log) |
| `1d4d8b2` | (see git log) |
| `60bc652` | (see git log) |

### Testing

- [OK] Deploy gate PASS at c9d12f9, 72a4930 and 765fe1e; offline smoke in the overlay image; base file hashes matched the running image each time; six services healthy, 0 restarts, 0 errors after each release.

### Status

[OK] **Completed**

### Next Steps

- Owner: internal ops group webhook key for watchdog alerts.
- Decide a gradual repair-agent rollout once shadow data has enough valid cases (10-01-repair-shadow-ops).


## Session 90: Pool-aware visual planning live; Trellis records backfilled

**Date**: 2026-10-02
**Task**: Pool-aware visual planning live; Trellis records backfilled
**Branch**: `feat/repair-agent-20260930`

### Summary

Found why selector v3 reused cooled images (two-person pool had 2 prop-free images; PNGs over the 6 MiB budget were never selectable), made the planner aware of the fresh action pool, resized 12 oversized action images, replayed 186 production briefs and deployed. Backfilled Trellis task records for 09-30..10-02.

### Main Changes

- action_pool_capacity + planner penalty (1,500 empty / 300 one left), only with selector v3 and prop labels; evals/visual_replay/plan_sim.py.
- Replay: cooled reuse 56% -> 2%, distinct action images 15 -> 21, top image share 16% -> 8%.
- Live 13:31 (image b8fa7ada): 12 PNGs resized to 1536 px, host manifest rebuilt, backups under /var/backups/edu-ai/brand-materials/before-visual-pool-20261002T133009/.
- Trellis: task.json/PRD for four tasks; three delivered tasks archived; 10-01-repair-shadow-ops stays in progress.
- Resume v3 draft prepared locally (tmp/resume-draft), awaiting the owner; the official resume file was not changed.

### Git Commits

| Hash | Message |
|------|---------|
| `11ad19c` | (see git log) |
| `ff398b2` | (see git log) |
| `0cb0eca` | (see git log) |

### Testing

- [OK] Deploy gate PASS at 11ad19c; smoke on staged and live materials: 41 assets verified, 26 action images within budget; no job running; six services healthy, 0 restarts, 0 errors.

### Status

[OK] **Completed**

### Next Steps

- After the evening slot, compare live cooldown-exhausted picks with the replay.
- Owner review of resume v3.


## Session 91: 运营后台计划与第 0 项（登录 + 设置页框架）

**Date**: 2026-10-08
**Task**: 运营后台计划与第 0 项（登录 + 设置页框架）
**Branch**: `feat/admin-console-20261008`

### Summary

Owner's 8 admin features planned as nine Trellis tasks (10/8-11/17); item 0 built: operator login, roles, audit log, /admin shell

### Main Changes

- Tasks 10-08-admin-console + admin-0..8 with PRDs from a code survey (sources are code seeds, keywords hard-coded, WeChat draft-only, no datacube, single env account, style constants, env-only model keys)
- Backend: migration 0052 admin_users/sessions/audit, /api/v1/admin auth + audit-events, write guard header, CLI admin_users_main
- Frontend: /admin login + grouped menu by role + placeholders + 操作记录; same-origin via Vite proxy (no credentialed CORS)
- Spec .trellis/spec/backend/admin-console.md: rules items 1-8 must follow (audit, fallback, versioning, encrypted write-only secrets)

### Git Commits

| Hash | Message |
|------|---------|
| `95059dd` | (see git log) |
| `90c5cdd` | (see git log) |

### Testing

- [OK] 12 unit + 6 integration (PostgreSQL), 34 frontend, browser smoke on a throwaway DB, predeploy gate PASS

### Status

[OK] **Completed**

### Next Steps

- Item 1 新闻源 from 10/9; owner questions: WeChat 认证/发布/数据统计 permissions, meaning of 文字数据统计, item 5 before 3, poster samples, how operators reach the console (tunnel vs HTTPS)


## Session 92: 运营后台第 1 项：新闻源后台增删改

**Date**: 2026-10-08
**Task**: 运营后台第 1 项：新闻源后台增删改
**Branch**: `feat/admin-console-20261008`

### Summary

Started item 1 on the owner's word (10/8 instead of 10/9) and finished it: generic HTML/RSS connectors configured in the database, sticky on/off for code sources, preview before save, audit

### Main Changes

- Generic connectors generic_html_v1 / generic_rss_v1 with settings in source_versions.connector_config (migration 0053)
- seed_sources keeps an operator's on/off (enabled_set_by); operator sources can be edited (new version) and archived
- Preview route: robots.txt, list, 3 sample articles with freshness/relevance verdicts; create re-checks robots; sources start disabled
- 新闻源 page in /admin; audit labels for source actions

### Git Commits

| Hash | Message |
|------|---------|
| `0b1c33c` | (see git log) |

### Testing

- [OK] 15 unit + 10 integration + 12 frontend; browser smoke + one real acquisition job on kepu.gmw.cn kept 2 articles; predeploy gate PASS

### Status

[OK] **Completed**

### Next Steps

- Item 2 关键词 next; deploy items 0+1 together only on the owner's word (migrations 0052+0053, API + acquisition worker image)
- Local dev DNS uses a fake-IP proxy (198.18.x): some hosts are refused locally by the public-DNS check; production is fine


## Session 93: 运营后台第 2 项：关键词后台增删改

**Date**: 2026-10-08
**Task**: 运营后台第 2 项：关键词后台增删改
**Branch**: `feat/admin-console-20261008`

### Summary

Operator 关注词/屏蔽词/文案禁用词 as immutable versions; slot runs snapshot the version; block = veto, focus = ordering bonus, banned = copy gate error

### Main Changes

- Migration 0054 operator_keyword_versions + content_slot_runs.operator_keyword_version_id; human picks inherit
- Selection: operator_blocked_term veto, +0.08 ordering bonus for focus hits, explanation keys only when present (replay-safe)
- Copy: LockedTopicContext.operator_banned_terms -> validate_material_draft error operator_banned_term
- Admin API + 关键词 page with try box, 7-day impact, wide-block confirmation, history

### Git Commits

| Hash | Message |
|------|---------|
| `ac5f076` | (see git log) |

### Testing

- [OK] unit + 3 integration + 7 frontend; browser smoke; predeploy gate PASS

### Status

[OK] **Completed**

### Next Steps

- Item 3 公众号发布 needs owner answers first (WeChat 认证 + freepublish permission; item 5 before 3?)
- Deploy items 0-2 together on the owner's word: migrations 0052-0054; API, acquisition worker, content scheduler/worker images


## Session 94: 运营后台第 0-2 项上线

**Date**: 2026-10-08
**Task**: 运营后台第 0-2 项上线
**Branch**: `feat/admin-console-20261008`

### Summary

Deployed login/audit, 新闻源, 关键词 to production at 17:28 CST on the owner's word (evening slot waived): image 5a5fb24c, migrations 0052-0054, mainline e6b3a5b

### Main Changes

- Base hashes 0 mismatches, offline smoke ok, DB dump 95 MB verified, migrate 0051->0054, six services recreated, admin routes 401/403, no log errors; 18:30 deliveries stayed queued
- Admin-only build (npm run build:admin) and nginx template tested locally (only console + /api/v1/admin exposed, CSP clean, login rate limit)
- mainline fast-forwarded to e6b3a5b (merged peer's docs-only e4534ac); exhibit connector pins 5a5fb24c; peer notified

### Git Commits

| Hash | Message |
|------|---------|
| `e6b3a5b` | (see git log) |

### Testing

- [OK] predeploy gate PASS; production checks listed above

### Status

[OK] **Completed**

### Next Steps

- Create the first owner account on production (owner picks the username)
- Domain: company domain is ICP-filed; need the name, DNS access, Tencent access filing check, office IP; install nginx + cert


## Session 95: 运营后台 items 6 (排版模板) and 8 (模型配置)

**Date**: 2026-10-09
**Task**: 运营后台 items 6 (排版模板) and 8 (模型配置)
**Branch**: `feat/admin-console-20261008`

### Summary

Per-account colour schemes for pipeline drafts; model key rotation with probe-first and self-restart. Both on the branch, not deployed.

### Main Changes

- Item 6: 4 colour templates over V2 (default identity), migration 0057, pinned per edition in the draft journal, editor page with sandboxed preview
- Item 8: model_api_keys (0058) + MODEL_SECRET_KEY, get_settings overlay (fail-open), SIGTERM watch in API + 5 workers, owner page with test/save/history/restore

### Git Commits

| Hash | Message |
|------|---------|
| `c364814` | (see git log) |
| `a6d6c5d` | (see git log) |

### Testing

- [OK] Unit + integration + frontend green; browser smokes (CSP, 390px, worker self-stop and reload); predeploy gate PASS

### Status

[OK] **Completed**

### Next Steps

- Combined deploy of polish + items 3/4/5/6/8: ADMIN_SECRET_KEY + MODEL_SECRET_KEY in server .env and compose, migrations 0055-0058, regenerate the rollout bundle; owner go-ahead, outside slot hours
- Item 7 海报风格 waits for the teacher's samples


## Session 96: 运营后台第二批上线与生产验收

**Date**: 2026-10-10
**Task**: 运营后台第二批上线与生产验收
**Branch**: `feat/admin-console-20261008`

### Summary

用户同意上线后，10:03 CST 切换六个服务到 24e96708，数据库升至 0059；绑定赛先生并完成首次统计同步，无文章发布。主线已合并并推送 origin。

### Main Changes

- 后台账号完善、公众号绑定/发布/数据、排版模板和模型配置按 9eaaaf3 清单上线；七个旧服务和数据库/MinIO 容器保持原样。
- 前端安装 /var/www/edu-ai-admin，本地入口 http://127.0.0.1:5180/admin/；公网 HTTPS 仍待域名和证书。
- 备份 /var/backups/edu-ai/admin-release-2-20261010T015738Z；生产版本、回滚步骤与审查问题已记录在规范和归档任务。

### Git Commits

| Hash | Message |
|------|---------|
| `f59ed89` | (see git log) |
| `a136a6d` | (see git log) |

### Testing

- [OK] predeploy gate PASS：10 passed / 0 failed / 1 skipped（缺少本地私有图片清单）；45 个后台前端测试、类型/静态检查、构建和 schema 检查通过。
- [OK] 六服务 0 重启/0 traceback；3 个模型消费者心跳新鲜；401 登录保护正常；浏览器登录页 200 且无 JS 错误。
- [OK] 公众号凭证通过；只读查询草稿 6 条、已发布记录 14 条；统计同步成功（21 条文章数据、30 条日数据），发布任务为 0。

### Status

[OK] **Completed**

### Next Steps

- 另行升级旧公众号草稿 worker 后排版模板才生效；模型轮换当前仅覆盖三个消费者。
- 模型密钥解密失败仍可能报告已加载版本，已记入后台规范，需独立修复后再依赖异常情况下的生效状态。
- 主目录展厅连接器仅追加新镜像白名单，20 测试通过；保留原有未提交改动，未重启展厅。


## Session 97: 运营后台首批可靠性修复与隔离预览

**Date**: 2026-10-10
**Task**: 运营后台首批可靠性修复与隔离预览
**Branch**: `fix/admin-reliability-20261010`

### Summary

完成R1–R5：发布确认与不确定状态防重/核对、独立统计补同步与日期缺口、模型真实加载状态及深链接修复。新只读模拟预览5181；生产未更新。

### Main Changes

- 新增0060/0061迁移、生成API契约与发布清单；独立复核修复畸形微信回执；保留根工作区及node_modules链接。

### Git Commits

| Hash | Message |
|------|---------|
| `d555011` | (see git log) |

### Testing

- [OK] 全量predeploy PASS：10通过0失败1私有素材缺失跳过；308前端测试；49个独立后台集成用例；Ruff/mypy/TypeScript/构建及Chromium验收通过。

### Status

[OK] **Completed**

### Next Steps

- 用户审核 http://127.0.0.1:5181/admin/ 只读模拟预览；单独批准生产切换后，按归档任务rollout执行实际镜像构建、迁移、后端先行部署与前端替换。


## Session 98: Admin usability: mobile layout, unsaved guards and pagination

**Date**: 2026-10-10
**Task**: Admin usability: mobile layout, unsaved guards and pagination
**Branch**: `feat/admin-usability-20261010`

### Summary

Completed U1-U6 frontend usability improvements in isolated admin worktree. Full frontend 50 files/345 tests, lint/types/changed formatting, generated API parity, OpenAPI check, admin demo+production and main builds passed. Independent review fixed stale actionable drafts on account/tab round trips and input edits during pending save. Final built browser 30 responsive checks and 9 grouped interaction flows passed; refreshed read-only mock preview5181 with API18102, no password. Production5180/services unchanged. Candidate hashes and backend0061 prerequisite documented in archived task. Preserve existing frontend/node_modules symlink; overview and production rollout remain outside this batch.

### Git Commits

| Hash | Message |
|------|---------|
| `3eeedc6` | (see git log) |

### Status

[OK] **Completed**
