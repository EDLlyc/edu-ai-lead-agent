# IP 翻页相册浏览器诊断

## Reproduction

- 2026-08-27 在 `http://127.0.0.1:5173/ip-assets` 使用真实 Chromium 登录，选择 5 张 `ready` 共享图片并进入 `/ip-assets/flipbook`。
- 桌面视口为 1440 × 1100；另检查了 390 × 844 的单页布局。
- 浏览器控制台和页面错误均为空。导航离开图库时有两个读请求被中止，和翻页渲染无关。

## Primary Root Cause

- `frontend/src/features/ip-assets/IpAssetFlipbookRenderer.module.css:104` 把 `.leaf` 设为 `position: relative`。
- `page-flip/src/Page/HTMLPage.ts` 的静态 `simpleDraw()` 会写 `position: absolute`，但动画 `drawHard()` / `drawSoft()` 使用的 `commonStyle` 不包含定位规则；因此动画开始后，项目 CSS 会让翻动页重新进入普通文档流。
- 连续帧显示：封面先正常绕书脊旋转，随后整页消失，背面的第一张内页从舞台底部进入；软页也受同一定位契约影响。这就是静态终态截图没有发现、用户实际翻页却明显感觉错误的原因。
- 参考实现明确要求叶片在获得引擎类名后保持 `position: absolute`，且特别注明不能使用 `position: relative`。

## Controlled Experiment

- 仅在浏览器运行时注入 `.stf__item[data-density] { position: absolute; }`，未修改项目源码。
- 注入后同一 680ms 封面翻页的所有连续帧都保持在书本坐标系内：封面围绕书脊旋转，内页作为背面随动，终态稳定落成左右跨页。
- 该单变量对照证明定位冲突是主因，不需要替换 `react-pageflip` 或重写翻页引擎。

## Secondary Findings

- `frontend/src/features/ip-assets/IpAssetFlipbookRenderer.tsx:238` 引用了不存在的 CSS Module 键 `styles.imageLeaf`，导致每个普通内页都输出字面量 class `undefined`。
- 桌面跨页的引擎索引从封面 `0` 跳到跨页起点 `1`、再跳到 `3`；当前状态文案因此显示“第 1 / 6 页 → 第 2 / 6 页 → 第 4 / 6 页”，没有表达实际可见的 `2–3`、`4–5` 跨页。
- `onChangeState` 把悬停折角 `fold_corner`、用户拖动 `user_fold` 和真实动画 `flipping` 统一当成忙碌态。是否放宽悬停态不是修复主因所必需，本次保持现有并发保护，避免扩大交互语义变更。
- 现有组件测试 mock 了翻页库，只验证调用和最终状态；Playwright 静态截图也会快进有限动画，二者都无法覆盖动画中的定位契约。

## Recommended Fix Boundary

- 在项目叶片样式上新增与引擎类组合后的绝对定位契约，不修改 `node_modules`，不复制外部仓库源码。
- 清理缺失的 `imageLeaf` 映射，确保 DOM 不再出现 `undefined` class。
- 监听横竖屏方向，把桌面状态显示为可见跨页范围，移动端保持单页状态。
- 增加静态 DOM/样式契约测试与真实时间轴浏览器回归；继续保留现有相册数据、登录和后端零写入边界。
