# 修复 IP 相册翻页交互

## Goal

修复独立 IP 资产网站中翻页相册的可见交互与视觉问题，让用户在桌面端和移动端都能自然、稳定地翻页，并获得与操作一致的即时反馈。

## Background

- 当前相册入口位于独立 IP 资产站点 `/ip-assets`，相册页面位于 `/ip-assets/flipbook`，不挂载到共享开发控制台。
- 相册使用项目原生 React/TypeScript 组件封装 `react-pageflip@2.0.3`。真实 Chromium 连续帧已复现封面翻转中途消失、背面内页从舞台底部进入的问题。
- 根因位于 `frontend/src/features/ip-assets/IpAssetFlipbookRenderer.module.css:104`：`.leaf { position: relative; }` 与翻页引擎的动画绘制契约冲突。浏览器运行时仅注入绝对定位规则后，同一动画恢复正常，详见 `research/browser-diagnosis.md`。
- `frontend/src/features/ip-assets/IpAssetFlipbookRenderer.tsx:238` 还引用了不存在的 `styles.imageLeaf`，普通内页 DOM 因此带有字面量 `undefined` class；桌面跨页状态当前显示单页起始索引，形成 `1 → 2 → 4` 的不直观跳号。
- 现有组件测试 mock 了翻页库，静态截图又会快进有限动画，因此上一轮验证只覆盖了翻页终态，没有覆盖动画过程。

## Requirements

- 让所有项目叶片在翻页引擎动画期间保持绝对定位，修复页面跌出书本坐标系、穿透、跳层和异常裁切。
- 清理无效 CSS Module 映射，页面 DOM 不得出现 `undefined` class token。
- 桌面端双页和移动端单页都必须保持图片比例、页面顺序和清晰的当前页反馈。
- 桌面内容跨页显示实际可见页范围；移动端、封面和封底显示单页位置。
- 尊重 `prefers-reduced-motion`；降低动态效果时仍须完成页面切换且不会锁死控件。
- 保留现有按钮、键盘、鼠标/触摸和并发保护，并提供与真实翻页状态一致的可感知反馈。
- 保留现有 2–20 张图片、首图封面、重排/移除、登录门禁和一次性内存草稿约束；不得产生后端写入或提供方调用。

## Acceptance Criteria

- [x] 真实 Chromium 连续帧显示封面和软页始终围绕书脊翻转，翻页中不跌出舞台、不从底部进入。
- [x] 桌面端连续向前、向后翻页时，书页不穿透、不跳层、不异常裁切，控件状态与实际页码一致。
- [x] 390px 窄屏下以单页模式正常显示并可触摸/按钮翻页，不产生横向溢出或页面错位。
- [x] 封面、内容页、必要空白页和封底顺序确定，首尾边界不会出现错误空页或无法返回。
- [x] 桌面跨页状态显示 `2–3` 一类可见范围，移动端和单独封面/封底显示一个页码，不再出现含义不清的 `1 → 2 → 4` 文案。
- [x] 普通内页 DOM class 全部有效，组件测试会在字面量 `undefined` 再次出现时失败。
- [x] 鼠标点击、触摸/拖动、上一页/下一页按钮和键盘操作均有可感知反馈，连续操作不会锁死。
- [x] `prefers-reduced-motion` 下页面直接切换，页码、按钮禁用态和可访问状态同步更新。
- [x] 修复不会产生资产、生成任务、下载计数或其他后端写入。
- [x] 焦点组件测试、TypeScript、ESLint、生产构建以及桌面/移动端真实浏览器回归通过。

## Key Decisions

- 保留 `react-pageflip`，通过项目叶片的窄范围 CSS 定位契约修复根因；不修改 `node_modules`，也不重写翻页引擎。
- 本次同时修复无效 class 和桌面跨页状态，因为两者都直接影响翻页质量且不改变业务范围。
- 保持现有折角悬停、拖动和动画期间的并发保护语义；此次不扩大为新的手势或动效设计。
- 连续动画帧是必需验收证据，静态终态截图不能单独证明修复完成。

## Out of Scope

- 保存或分享相册、PDF/视频导出、背景音乐、自动排版和 AI 生成相册内容。
- 更换 IP 资产来源、调整上传/收藏/下载排行或生图流程。
- 引入新的后端接口或持久化模型。

## Completion Evidence

- 实现把 CSS Module 叶片与全局 `.stf__item` 组合为绝对定位契约，并增加编译后 CSS 回归断言；普通内页不再生成 `undefined` class。
- 独立 Chromium 检查覆盖 1440px 硬封面/软页前后翻、按钮、键盘、Home/End、封底边界，以及 390px 触摸前后翻和横向溢出；连续动画帧中的所有叶片均为绝对定位。
- 桌面状态按 `1 → 2–3 → 4–5 → 6` 显示，移动端按单页显示；reduced-motion 直接翻页后保持 `aria-busy=false` 且控件未锁死。
- 浏览器回归没有控制台/页面错误，也没有 POST/PATCH/DELETE 请求。
- `vitest --run src` 通过 34 个文件、230 项测试；ESLint、严格 TypeScript、Prettier、生产构建和 production-only audit 全部通过。
- 顶层无过滤 Vitest 会误收集并行任务新增的公众号 Playwright 文件；开发依赖 audit 另有 4 个既有 high 告警。两者均与本任务代码无关，未越界修改。
