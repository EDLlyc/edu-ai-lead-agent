# 微信公众号编辑器本地适配：实施计划

## Phase 0 — 开始前保护与基线

- [ ] 在 `task.py start` 后先加载 backend/frontend/Trellis 指南；重新检查 `git status` 和下列高碰撞
      文件的局部 diff：config、route/schema、OpenAPI/generated schema、Panel/CSS、`.env.example`、
      `compose.yaml`、README、Trellis specs。
- [ ] 冻结现有 official-account export/API/frontend focused tests；记录当前 migration head，但本任务不
      新增 migration。
- [ ] 把当前已通过校验的小赛 V4 主题/正文作为研究基线，计算主题文件/产物 SHA-256；确认运行时不读取
      `/root/.codex/skills`。
- [ ] 明确实施期间外部调用计数：微信、企微、模型、Embedding、生图、新闻抓取均为 0。

## Phase 1 — 纯 domain renderer 与 preflight

- [ ] 新增 `domain/official_account_editor_handoff.py`，冻结 renderer/style/template/bundle/preflight/
      rights-policy identities 和 typed immutable models。
- [ ] 把小赛主题所需 token、组件骨架、组件映射收为项目静态定义并绑定 SHA-256；保持 gzh 原版结构，
      只使用已批准的小赛色板。
- [ ] 实现 Article Package -> 单一纯 `<section>` 正文：标题/引言/精选目录/章节编号/段落关键词下划线/
      引用/列表/正文图片/上下文图/来源/结语/唯一签名区；只标记已有文本，不改写事实或文案。
- [ ] 实现标签、属性、inline CSS、`span leaf`、URL、相对 asset、占位符、重复媒体、封面比例、哈希与
      preview/body 一致性 preflight。
- [ ] 把 `publish_permission_unverified` 作为
      `context_image_rights_unverified_direct_use` 非阻断 warning，保留原状态/来源/署名；不修改历史
      copy-ready 检查。
- [ ] 添加纯单元测试：中文/危险文本转义、source allowlist、1--5 图、section/block placement、context
      anchor、关键词标记、禁止标签/属性/style、稳定 fingerprint、历史常量不变。

## Phase 2 — application bundle use case

- [ ] 新增 application service，复用现有 repository、persisted snapshots 和
      `OfficialAccountLocalMediaResolver`；数据库读取与对象字节读取分界保持现有模式。
- [ ] 实现 development/flag、ready simulated draft、validation/audit、immutable approved review 与 review/
      request fingerprint gate；所有失败返回稳定 blocking code。
- [ ] 重新读取并校验 body/context/cover 字节、MIME、尺寸、hash、role、ordinal、section anchor；禁止私有
      路径和 API/remote image URL 进入正文或 bundle。
- [ ] 生成 article-body/preview/Markdown/JSON/sources/rights/review/preflight/mobile/theme/README/
      manifest/assets，并构建排序、时间戳、权限固定的确定性 ZIP；写后复核 ZIP entry/hash/bytes/path。
- [ ] 用临时目录或内存构建并清理中间物；不得修改任何 durable row、对象或 approved article。
- [ ] 添加 offline tests：两次构建字节相同、ZIP 安全、媒体篡改 fail closed、approval/state matrix、
      unverified rights 只警告、0 socket/provider/client construction。

## Phase 3 — development-only HTTP/OpenAPI contract

- [ ] 在 setting 中增加默认关闭的 editor-handoff opt-in，并要求 `APP_ENV=development`；谨慎合并
      `.env.example`/Compose 当前改动。
- [ ] 扩展 capabilities 和 typed schemas：handoff state、stable checks/warnings、identities/fingerprints、
      media downloads、mobile status 与 artifact URLs。
- [ ] 扩展现有 route，增加 metadata/body/preview/assets/bundle 五个 GET resource；route 只组合 use case、
      响应与安全 headers，不承载 render/preflight 规则。
- [ ] blocked metadata 返回可展示的 200 projection；artifact routes 返回稳定 AppError code，不能解析
      中文 message；preview 使用严格 CSP，asset/bundle 使用安全 Content-Disposition。
- [ ] 更新 API unit tests 和 OpenAPI prohibition tests：新路径存在但没有 publish/send/AppID/AppSecret/
      token/account fields；flag/production fail closed；路径 traversal、未知 asset、篡改 bytes 被拒绝。
- [ ] 运行 `make api-generate`，只让生成器更新 `backend/openapi.json` 与 frontend schema；运行 contract
      drift check，绝不手改 generated schema。

## Phase 4 — 公众号本地工作台

- [ ] 新增 `OfficialAccountEditorHandoff` 窄组件并接入已选 run 详情；保留现有工作台信息架构和 sandbox
      preview，不重写不相关页面。
- [ ] 在 `api.ts` 从 generated response 映射 readonly view model；在 `hooks.ts` 增加 query key/query，
      不把 GET 交接读取伪装成 server mutation。
- [ ] 显示审核、结构、媒体、rights、mobile 与 bundle gates；明确“本地交接，未同步公众号”及未验证
      新闻图直接使用 warning。
- [ ] 只有 blocking gates 全过才开放复制正文/ZIP；提供正文图、新闻图和封面的独立下载链接。
- [ ] 实现 clipboard HTML/plain-text effect：成功、API 不可用、权限拒绝和复制失败分别反馈；不使用
      `dangerouslySetInnerHTML`，使用 `aria-live`、键盘操作和可见 focus。
- [ ] 更新 CSS Modules，使 320/430 工作台和预览不产生页面横向溢出；图片保持原比例，目录内部可手势
      横向滚动。
- [ ] 添加 mapper/hook/component/clipboard tests、feature flag tests 和 axe 检查；覆盖 blocked/ready、
      warning、copy success/failure、download URLs、sandbox 与无 publish 文案。

## Phase 5 — 浏览器验收与本地导出

- [ ] 增加 deterministic Playwright fixture acceptance：只用本地 fixture/loopback，禁止并断言所有外部
      request；320px/430px 检查图片加载、自然尺寸、页面 overflow、copy root/body equality。
- [ ] 运行项目内 static preflight，并用已安装
      `/root/.codex/skills/gzh-design/scripts/validate_gzh_html.py` 对最终 fixture 纯正文做独立校验，达到
      0 ERROR/0 WARNING。CI/runtime 不依赖该个人路径。
- [ ] 通过受控本地 fixture 路径生成一个新的 output 目录与 ZIP，记录 SHA-256、文件数、图片数、
      mobile 结果和 0 external calls；不调用真实微信编辑器。

## Phase 6 — 文档、回归与收尾检查

- [ ] 用英文更新 backend official-account spec；新增/更新 frontend editor-handoff spec/index；README
      写明 flags、操作步骤、bundle、rights warning、微信图片上传边界和故障处理。
- [ ] 运行 focused Ruff/format/mypy/pytest、API/OpenAPI、frontend lint/typecheck/Vitest/build/Playwright、
      Compose config 与 `git diff --check`。
- [ ] 运行历史 official-account exporter/API/fixture golden regression，确认 V1--V10 字节、manual review、
      fixture/live-local review 导出与恢复不变。
- [ ] 用 Trellis check agent 做独立 spec/数据流/测试/脏工作区审查，修复其发现后再次跑 focused gates。
- [ ] 报告精确改动文件、命令结果、外部调用计数、本地 output 路径和任何未跑的真实微信验收边界；不
      commit。

## 验证命令（实施时按实际环境调整）

```bash
python3 -m ruff format --check backend/app/domain/official_account_editor_handoff.py \
  backend/app/application/services/official_account_editor_handoff.py \
  backend/app/api/v1/routes/official_account_local.py \
  backend/app/schemas/official_account_local.py \
  backend/tests/unit/test_official_account_editor_handoff.py \
  backend/tests/unit/test_official_account_local_api.py
python3 -m ruff check backend/app/domain/official_account_editor_handoff.py \
  backend/app/application/services/official_account_editor_handoff.py \
  backend/app/api/v1/routes/official_account_local.py \
  backend/app/schemas/official_account_local.py \
  backend/tests/unit/test_official_account_editor_handoff.py \
  backend/tests/unit/test_official_account_local_api.py
python3 -m mypy backend/app/domain/official_account_editor_handoff.py \
  backend/app/application/services/official_account_editor_handoff.py
python3 -m pytest backend/tests/unit/test_official_account_editor_handoff.py \
  backend/tests/unit/test_official_account_export.py \
  backend/tests/unit/test_official_account_local_api.py -q
make api-generate
make api-contract-check
npm run test --prefix frontend -- --run src/features/official-account-local src/app/App.test.tsx
npm run lint --prefix frontend
npm run typecheck --prefix frontend
npm run build --prefix frontend
npm run test:e2e --prefix frontend -- --grep "editor handoff"
docker compose --profile official-account-local config --quiet
git diff --check
```

## 高风险文件与回滚点

- 高碰撞：`backend/app/core/config.py`、`backend/app/api/v1/routes/official_account_local.py`、
  `backend/app/schemas/official_account_local.py`、`backend/openapi.json`、生成 TypeScript、现有 Panel/CSS、
  `.env.example`、`compose.yaml`、README、Trellis spec/index。
- 新模块和新组件优先承载大部分行为；高碰撞文件只做 wiring 和 generated changes。
- 不修改 `backend/app/domain/official_account_local.py` 的历史 render dispatch，不修改
  `official_account_export.py` 历史 writer，除非独立检查证明完全不影响 golden；默认方案不需要修改。
- 回滚：关闭 opt-in/移除新 route wiring 与 UI composition 即可；无 migration、无 durable data 回滚。

## task start 前检查

- [ ] `prd.md` 已做最终 convergence pass，且无 Open Question。
- [ ] `design.md`、`implement.md` 完整且与用户“新闻原图直接使用”决定一致。
- [ ] `implement.jsonl`、`check.jsonl` 都含真实 spec/research 条目，不含 seed `_example`。
- [ ] `task.py validate` 通过。
- [ ] 用户在看到最终规划摘要后的后续消息中明确批准实施。
