# 公众号本地自动化与视觉优化 V2

## Goal

把已完成的 development-only 微信编辑器交接升级为真正可无人值守的本地流程，并提升小赛公众号正文的
新闻感、语义配图位置和视觉节奏。V2 必须允许通过已经持久化的确定性校验、模型审校和图片质量状态自动
放行，不要求人工点击批准；同时保留 V1 人工审核交接的版本身份、字节和历史阻断语义。

## Background and confirmed facts

- V1 已提交并归档，拥有独立 renderer/style/template/bundle/preflight/rights-policy 身份，默认测试和导出
  零外部请求，不调用微信或企微。
- V1 application gate 在
  `backend/app/application/services/official_account_editor_handoff.py:234-260` 强制要求不可变人工批准；
  这与用户最新确认的“不需要人审”目标冲突。
- V1 新闻上下文图只记录 `assigned_section_index`，renderer 在章节标题后、正文块前统一插入，见
  `backend/app/domain/official_account_editor_handoff.py:212-237`；它不能精确解释图片对应哪个正文块，且可能
  与正文图相邻。
- V1 `_emphasized()` 只用正则取每段第一个 4--14 字短语，见
  `backend/app/domain/official_account_editor_handoff.py:586-601`，不满足 `gzh-design` 每段 1--3 个语义重点的
  规则。
- 当前 V2 评审样例的 manifest 只有 3 张 body 图和 1 张 cover，未包含 context 新闻图；Playwright 已证明
  320px/430px 无页面溢出、3 张图片加载和 0 external requests，但交接包内 `mobile-validation.json` 仍为
  `not_run`，外部 sidecar 才记录 `passed`。
- 当前标题字号固定为 26px，目录卡固定宽 110px；样例标题 24 字、章节标题 22--24 字，并且 4 个 callout
  都渲染成同一深蓝卡，造成拥挤和模板重复感。
- 当前工作区有大量其他任务的未提交修改；公众号文件没有重叠 diff。实现必须检查每个高碰撞文件的局部
  diff，保留政府要闻及其他任务的所有改动。

## Requirements

### R1 — V2 additive compatibility

- 新增 V2 editor-handoff renderer/template/style/bundle/preflight/release-policy 身份；不得修改 V1 常量、V1
  golden、历史 Article Package fingerprint、历史 exporter 或恢复字节。
- V2 继续只从已持久化的 run/article/render/draft/media/audit 状态派生，不修改已批准文章，不新增微信、
  企微或社交发布动作。
- 运行时不读取 `/root/.codex/skills`；小赛主题组件和规则仍由项目内静态、哈希绑定的定义拥有。

### R2 — 可审计的自动放行

- 增加显式、版本化的 release policy：`manual_only` 保持 V1 行为；`quality_auto` 允许没有 manual review 的
  V2 运行在所有质量门禁通过时自动放行。
- `quality_auto` 至少要求：run/draft ready、simulation、Article fingerprint 与固定 render 谱系一致、
  deterministic validation passed、model audit accepted、全部所需媒体完整且图片质量状态没有明确失败。
- 已存在的人工 `rejected` 决定必须优先阻断，不能被自动策略绕过；已存在 `approved` 可以作为 manual
  release。没有人工记录时生成确定性的 machine release projection，记录 policy/version/input fingerprints
  和 gate codes，并进入 V2 manifest/ZIP；不得伪装成人工批准。
- 默认离线 fixture 与测试使用 `quality_auto` 且不构造 provider client；生产/非 development 环境和 flag
  关闭时继续 fail closed。

### R3 — 正文块级新闻图计划

- V2 为每张 context 图生成确定性的 placement projection：section index、目标 block index、插入方向、
  匹配理由/版本。优先使用 alt/caption 与正文块的语义词重合，信息不足时回退到章节第一个完整正文段后。
- 新闻图是 IP 正文图的补充，不替换 body image block；同一章节内按 block 顺序交错，两张图片之间至少有
  一个可见正文块。冲突时稳定顺延，不能丢图。
- manifest、article JSON/Markdown、API 和工作台展示 placement 与原始 source/credit/rights；
  `publish_permission_unverified` 仍只产生明确的非阻断 warning，绝不改写为已授权或事实证据。

### R4 — 确定性语义重点

- 不改变 Article Package 或调用模型。V2 从标题、digest、章节标题、数字/专名和正文已有短语中确定性评分，
  每个正文段落选择 1--3 个不重叠的 4--15 字重点；无可信候选可少标，但不能凭空生成文字。
- renderer 只切分并转义原文，将选择结果用小赛 AI 蓝下划线组件包裹；全文输出文本逐字拼回必须等于原始
  文本。选择规则和版本进入 V2 identity，并以中文、数字、危险字符和稳定重放测试覆盖。

### R5 — 自适应小赛版式

- 保持“小赛蓝（摸鱼绿原结构）”单主题和微信兼容骨架，不跨主题、不引入外部 CSS/字体、`class`、`id`、
  `display:grid` 或复制正文内脚本。
- 根据文章结构确定一种稳定 recipe（至少新闻解读、教程/清单、观点/案例），只改变组件组合与节奏，不
  改写文章事实或短文案。
- 标题按长度分档，目录卡按精选标题长度使用受控宽度/字号；保留最多 3 个核心目录项。深色锚点卡全文
  不超过 5 个，重复 callout 改用同主题的浅底提示/左竖条金句变体。
- 图片继续 `max-width:100%;height:auto;display:block;margin:0 auto`，所有可见文本仍使用 `span leaf`。

### R6 — 新闻场景离线样例与移动验收

- 新增一套含 3 张互异 IP body 图、1--2 张本地新闻 context 图和独立 2.35:1 cover 的确定性样例。来源、
  署名、未验证权利和 context-only-not-evidence 必须在正文、rights、manifest、API/UI 中可见。
- 默认 fixture/单元/浏览器测试不得联网；测试必须证明新闻图没有替换 IP 图、图片顺序符合 block plan、
  全部图片加载、320px/430px 无页面级横向溢出且 external request count 为 0。
- 浏览器报告必须绑定被验证的 content fingerprint/body SHA/media SHA。V2 本地导出采用两阶段身份：先固定
  content identity，再把通过的 browser report 纳入最终 artifact identity/ZIP，避免同一 artifact
  fingerprint 对应 `passed` 与 `not_run` 两套字节。普通 API runtime 未运行浏览器时必须诚实显示
  `not_run`。
- 工作台文案明确区分“当前运行未做浏览器验收”和“与当前 content fingerprint 精确匹配的离线验收已
  通过”，不得套用其他文章的 fixture 结果。

### R7 — 合同、测试、输出和文档

- 所有新增状态和 placement/release/mobile 字段通过 FastAPI schema、生成 OpenAPI 和生成 TypeScript
  传递；前端不得手写第二份 wire schema或使用 `dangerouslySetInnerHTML`。
- 更新 focused backend/frontend tests、独立 `gzh-design` validator、Playwright 和本地导出脚本；默认
  全套调用模型、Embedding、生图、新闻抓取、微信和企微均为 0。
- 生成一个新的本地 V2 output 目录，包含干净正文、独立预览、完整 ZIP、新闻图、IP 图、封面、通过的
  fingerprint-bound mobile report 和校验摘要；不得覆盖既有 V1/V2 输出目录。
- 文档用英文记录 release policy、新闻图 placement、recipe、浏览器报告身份和永久 no-publish 边界。

### R8 — 正文块驱动的 IP 参考生图

- 正文 body 图不得仅因为来自公司目录就称为 IP 图。每张新图必须从一个稳定正文块提取场景 brief，先从
  已批准的小赛视觉目录选择与该块语义和角色动作匹配的参考资产，再把参考图作为人物身份/造型锚点连同
  brief 提交给生图模型；最终正文使用新生成的场景图，不直接把目录原图当成正文成图。
- 生产路径优先复用现有 Qwen3-VL 完整索引的正文块级检索；离线 fixture 使用冻结且可校验的选择投影，
  但不得伪装成真实 embedding 调用。两种路径都必须保留 block index/fingerprint、safe public ref、角色
  `xiao-sai` / `sai-xiansheng`、选择方式、生成计划和输出校验谱系。
- 三张本地验收 body 图都必须能肉眼识别小赛或赛先生；整组三张必须同时覆盖小赛和赛先生，且不得把人物
  缩成角标、Logo、玩具、背景装饰或无法辨认的剪影。场景仍须对应各自正文块，并保持 3:2、无水印、无
  额外文字和独立图片内容。
- 默认测试继续使用本地 bytes/fake transport，模型、Embedding 和生图外部请求为 0；明确授权的本地成品
  生成可调用图片模型，但仍禁止任何微信、企微、上传、发布或群发调用。

## Acceptance criteria

- [ ] `manual_only` 仍复现 V1 pending/approved/rejected 行为；V1 identities/goldens/ZIP byte regression 全部
      不变。
- [ ] `quality_auto` 在无 manual review 且所有 durable quality gates 通过时生成明确的 machine release；
      任一 deterministic/model/image gate 明确失败或已有人工 rejected 时返回稳定 blocking code。
- [ ] 一次 development-only 本地流程可从已持久化 Article Package 自动生成正文、新闻图+IP 图交错排版、
      封面、预览和 ZIP，无人工批准动作、无 durable side effect。
- [ ] 每张 context 图的 manifest/API placement 指向稳定 block；正文中两图不相邻，新闻图不替换现有 body
      image block，来源/署名/rights/事实边界完整。
- [ ] 每个有可信候选的正文段落包含 1--3 个语义下划线短语；移除标签后正文文字与输入逐字一致；重复构建
      的 HTML、content fingerprint 和 ZIP 字节一致。
- [ ] 长标题和 22--24 字目录项在 320px/430px 下无页面溢出；相同深蓝 callout 不再机械重复，锚点层不
      超过 5 处；最终纯正文通过 `gzh-design` 0 ERROR/0 WARNING。
- [ ] 新离线新闻 fixture 包含至少 3 body + 1 context + 1 cover；Playwright 绑定 content/body/media hash，
      所有图片加载、320/430 无页面溢出、0 external requests，最终 ZIP 内状态为 `passed`。
- [ ] runtime 未验浏览器时仍显示 `not_run`；只有 content fingerprint 精确匹配的报告才显示 passed。
- [ ] 三张 body 图都有可见且可识别的小赛/赛先生人物，整组覆盖两名角色；每张图的正文块 brief、参考
      public ref/角色、选择方式、生成计划和输出 hash 可追溯，且生产语义检索结果确实作为生图参考输入。
- [ ] focused Ruff/format/mypy/pytest、OpenAPI drift、frontend lint/typecheck/Vitest/build、Playwright、历史
      official-account regression 与 `git diff --check` 通过；没有微信/企微调用或账号凭据字段。

## Out of scope

- 微信 `uploadimg`、永久素材、草稿箱、发布、群发、公众号登录或真实编辑器自动粘贴。
- 自动判断新闻图片版权、把 `publish_permission_unverified` 改成已授权，或把品牌知识当作外部事实证据。
- 修改新闻采集、文章生成、Embedding/生图 provider 本身；本任务只消费其已持久化结果和本地 fixture。
- 删除 V1 人工审核能力、迁移或重写历史包；`manual_only` 继续作为兼容/回滚路径。
