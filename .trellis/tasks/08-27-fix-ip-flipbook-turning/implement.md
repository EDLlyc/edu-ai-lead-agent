# 实施计划：修复 IP 相册翻页交互

1. 在翻页叶片 CSS 中建立 `.leaf` 与引擎 `.stf__item` 的绝对定位契约，保留项目原有页面内部布局。
2. 清理普通内页缺失的 CSS Module 映射，确保生成的 class token 全部有效。
3. 记录引擎方向并把桌面双页状态改为可见页范围；移动端、封面和封底保持单页文案。
4. 扩展组件测试，覆盖 class、定位契约、方向变化、跨页文案、按钮状态和 reduced-motion。
5. 运行前端焦点测试、全部测试、ESLint、严格 TypeScript、Prettier、生产构建和依赖审计。
6. 用真实 Chromium 在 1440px/390px 下回归前翻、后翻、连续翻、按钮、键盘和触摸，并保留至少一组动画中间帧证据。
7. 复核页面访问期间没有 POST/PATCH/DELETE 请求或相关数据库计数变化；更新 IP 资产前端规范中的第三方渲染器定位契约。

## Validation Commands

```bash
cd frontend
npm test -- --run src/features/ip-assets/IpAssetFlipbookRenderer.test.tsx src/features/ip-assets/flipbookLeaves.test.ts
npm test -- --run
npm run lint
npm run typecheck
npm run format:check
npm run build
npm audit --audit-level=high
```

## Risky Files / Rollback Points

- `frontend/src/features/ip-assets/IpAssetFlipbookRenderer.module.css`：定位 specificity 是主风险点。
- `frontend/src/features/ip-assets/IpAssetFlipbookRenderer.tsx`：方向与页码范围必须跟随引擎事件，不能自行猜测断点。
- `frontend/src/features/ip-assets/IpAssetFlipbookRenderer.test.tsx`：mock 需真实表达方向回调，不得只验证方法被调用。
- `.trellis/spec/frontend/ip-asset-hub.md`：只记录已验证的可执行契约，不扩大产品范围。
