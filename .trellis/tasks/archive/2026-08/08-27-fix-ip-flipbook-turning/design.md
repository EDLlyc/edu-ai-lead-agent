# 技术设计：修复 IP 相册翻页交互

## Architecture and Boundaries

- 只修改 `frontend/src/features/ip-assets/` 下的翻页渲染器、CSS Module 和焦点测试；如需新增浏览器回归，放入现有前端 E2E 目录。
- 继续使用已安装的 MIT `react-pageflip@2.0.3`；不修改依赖源码、不更换渲染器、不引入后端接口。
- 相册草稿仍为一次性模块内存投影，资产查询缓存、数据库、生成任务和下载计数均不参与翻页。

## Rendering Contract

- 项目页面元素在引擎附加 `.stf__item` 后必须是绝对定位。使用 CSS Module 本地类与全局引擎类的组合选择器，确保动画 `drawHard()` / `drawSoft()` 即使重写 `cssText` 也不会回到普通流。
- `.leaf` 保留页面内部 Grid、背景、边框和裁切；定位责任单独落在“叶片 + 引擎项”组合规则上，避免对编辑器缩略图或其他组件产生影响。
- 普通内页使用真实、已定义的修饰类或不附加空修饰类，DOM class 列表不得出现 `undefined`。

## State and Status

- 订阅 `onChangeOrientation`，维护 `portrait | landscape`。
- 移动端显示当前单页；桌面端封面/封底显示单页，内容跨页显示规范化范围，例如“第 2–3 / 6 页”。
- 现有翻页并发保护、按钮、键盘、触摸和 reduced-motion 直接切换保持不变；本次不重定义折角悬停的锁定语义。

## Validation Design

- 组件测试覆盖：普通内页无 `undefined` class、方向事件更新页码范围、封面/跨页/封底状态正确、现有 reduced-motion 和控制器调用不回退。
- 添加定位契约检查，保证引擎项的绝对定位不会被以后重构删除。
- 真实 Chromium 回归必须通过连续截图/录屏或 CDP screencast 观察动画中间帧；只截终态不算通过。
- 桌面 1440px 和移动 390px 均检查顺序、溢出、前后翻、按钮/键盘以及控制状态。

## Risk and Rollback

- 风险主要在 CSS specificity：规则过宽可能影响库内部阴影，规则过窄则动画期间仍失效。选择只匹配项目叶片自身的组合选择器。
- 方向事件可能在初始化和 resize 时重复触发；状态更新必须幂等，并以引擎实际事件为准。
- 回滚只需撤销渲染器/CSS/测试的任务提交；不涉及数据迁移或后端恢复。
