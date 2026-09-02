# IP 检索 Grounded Evaluation：仓库证据

## 已有能力

- `backend/evals/ip_asset_retrieval/` 当前有 41 条 provider-free case，覆盖 8 个类别。case 保存的是合成候选及冻结的 metadata/semantic rank，runner 复用生产 `rank_ip_asset_candidates` 比较 V2 direct blend 与 V3 weighted RRF。
- 现有指标是 Recall@5、MRR@5、nDCG@5 和 zero-result rate。当前实现把 relevance grade `>0` 当作 relevant，并把无 relevant 的 case 记为 1.0；新的 grounded runner 必须把无答案查询单列，避免宏平均虚高。
- 私有批准清单当前有且仅有 41 个 `approved=true` 资产；每项包含稳定 catalog identity、受控视觉元数据和校验信息。清单中的私有路径、文件名、checksum 和原图不得进入普通评测导出。
- 动态 IP 资产库已有安全 `ipa_...` 浏览器引用、受控缩略图/预览 API、共享/ready 访问检查和 41 图导入流程。服务可以在内部按 blob checksum 把批准清单映射到动态资产行，但 API/报告只投影安全引用。
- `IpAssetService.search_text` 当前执行自然语言 filter extraction、最多 500 条 metadata candidate pool、可选 multimodal embedding、vector search 和生产 V2/V3 rank selector；成功搜索会写匿名结果/无结果聚合。
- 现有匿名搜索统计只保存日期、search version、mode、event kind 和 count；不保存 query、asset、profile、session 或请求身份。Grounded evaluation 不能从线上统计反推 labels，也不能污染这些聚合。
- 前端已有独立 `/ip-assets`、`/ip-assets/create`、`/ip-assets/flipbook`、`/ip-assets/login` 路由，统一演示登录门、本地 profile、生成 OpenAPI mapper、TanStack Query、缩略图卡片和无障碍反馈模式。
- 当前数据库迁移 head 已到 `20260901_0042_wechat_mp_draft_jobs.py`；新迁移必须从 0042 继续，不能复用旧的 IP 资产迁移编号。

## 设计结论

- 保留现有 41-case synthetic suite 作为快速 CI 排序回归；新增 grounded suite，不重写旧 schema 或 canonical。
- Codex 完成 100×41 初始视觉相关性标签，但来源必须是 `codex_seed`，不能宣称人工 Gold。
- 用户明确取消站内评测页；V1 不增加前端、API、数据库表、profile reviewer 或多人协作能力。
- 后续若需要人工 Gold，使用独立任务和 offline review template 规划；本任务的 maturity 始终为 `seed`。
- 真实评测通过 application service 的内部 evaluation mode 关闭 search aggregate side effect；普通 API 行为不变。
- 41 图 asset-set fingerprint 必须绑定安全 catalog refs，并在映射缺失、重复、非 ready 或非 shared 时拒绝标注/评测。

## 已知工作树风险

- 工作区同时存在 P0 评测、图片质量、周刊 DAG、微信草稿等未提交任务；本任务不得重置、格式化或修复无关文件。
- `models.py`、OpenAPI、`Application.tsx`、路径解析和 IP feature 文件是高碰撞区域；实施前后都要检查 task-scoped diff。
- 全量检查若被无关在途修改阻断，必须记录 focused pass 与既有 failure，禁止为变绿改写其他任务的 canonical 或契约。
