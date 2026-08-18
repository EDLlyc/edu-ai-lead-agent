# Agent Workbench 真实运行素材包 — Implementation Plan

## Ordered checklist

### 1. Freeze baseline

- [ ] 记录 HEAD、Workbench OpenAPI/schema、canonical report 和旧 fixture screenshot hash。
- [ ] 跑 focused Workbench/API/UI gate，确认三类 query 的当前 typed behavior。
- [ ] 保留并排除用户修改的 `reports/**` 与无关任务文件。

### 2. Build one source of truth for cases

- [ ] 增加三个 sanitized case manifest，绑定 query、expected status、tools、citation rules 和 screenshot label。
- [ ] API/browser/case-study 生成都消费同一 manifest。
- [ ] 增加 manifest schema/uniqueness/safe-text tests。

### 3. Real local capture

- [ ] 增加受控 launcher/capture command，强制 deterministic fixture/no-live 和 exact loopback ports。
- [ ] 通过真实 HTTP 保存三条 typed responses，不使用 TestClient 或 route fulfillment 冒充运行。
- [ ] 启动真实 Vite UI，用 Playwright 输入同一 query、提交并等待 terminal state。
- [ ] 截取三个结果区域与一张总览图，清理 metadata 并生成 hashes。
- [ ] 对比 API/UI terminal、tool/citation/step semantics，动态 run/latency 仅作诊断。
- [ ] 在 success/failure/signal 下清理全部子进程和临时目录。

### 4. Evidence package and narrative

- [ ] 生成 machine-readable `manifest.json` 和 human-readable `overview.md`。
- [ ] 更新 `docs/portfolio/agent-workbench.md`，加入三案例真实运行表、截图和生成命令。
- [ ] 更新 README 的作品集块，只引用 manifest 中的真实数字。
- [ ] 整理三条简历 bullet 和三分钟讲解，不声称 live-model accuracy。

### 5. Single authorized live Zhipu run

- [ ] 执行用户已明确授权的一条智谱多工具案例。
- [ ] 强制 fixture-only、多工具单案例、最多四次 model decision、无整条重试。
- [ ] 保存 typed result/screenshot/usage/latency，失败同样 fail closed 且不二跑。

### 6. Verification

- [ ] Focused backend Agent API/runner/model contract tests。
- [ ] Focused frontend Agent component/api/accessibility tests。
- [ ] Workbench OpenAPI/generated schema drift 与 deterministic 42/42 canonical check。
- [ ] Capture harness：host rejection、API interception forbidden、port collision、semantic mismatch、cleanup。
- [ ] Screenshot/image metadata、manifest hash、relative-link 和 secret/private-path scan。
- [ ] Production build tree-shaking 与 production OpenAPI unchanged。
- [ ] 独立 Trellis check 复核“真实运行”声明、素材一致性和隐私边界。
- [ ] `git diff --check`。

## Expected file areas

- `docs/portfolio/agent-workbench.md`
- `docs/portfolio/runs/agent-workbench/**`
- `docs/portfolio/assets/agent-workbench-*.png`
- capture scripts and focused tests under existing portfolio/dev tooling areas
- minimal README portfolio block
- task result/spec updates only where a reusable capture contract is introduced

## Explicit exclusions

- No GitHub Actions, Pages, LICENSE/NOTICE, repository push or public deployment in this narrowed task.
- No production/server/DB/WeCom access.
- No provider call beyond the single authorized Zhipu multi-tool case.

## Approval boundary

The user approved this narrowed plan and one bounded Zhipu live case. Approval never authorizes GitHub push,
Pages deployment or production deployment.
