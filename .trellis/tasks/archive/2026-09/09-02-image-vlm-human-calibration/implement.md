# 六源图片 GLM-5V-Turbo 盲测：实施计划

## Dependency gate

- [x] 父任务 shared contracts、transport、budget/auth/private I/O 已通过 provider-free focused tests。
- [x] Manifest 固定 shared contract version/SHA，不复制共享 schema。
- [x] Reviewer 子任务无结果依赖，不读取其 blind map、votes 或报告。

## Implementation

- [x] 新建 `backend/evals/image_quality_panel/` 与 `sources.v1.json`；冻结 6 source families、blob/content SHA、
      MIME/dimensions/derivatives 和用户授权依据，拒绝 dirty/private/missing-rights inputs。
- [x] 实现 hash-seeded Pillow transforms 与 48 derived pair cases，六维/36-12/24-24 平衡；按 family 分组 split。
- [x] 定义每臂 1–2 图、optional reference、HMAC blind map、gold A/B balance 和 hash-bound grouping/order。
- [x] 扩展共享 image vote profile：pair choice + A/B decision/critical/issues；实现完整 BA arm inversion。
- [x] 把旧五模型计划收缩为唯一智谱 `glm-5v-turbo` 的 `1*120<=120` plan；四图 diversity 仍为首 call，失败停止其余计划。
- [x] 保留 objective pair/arm metrics、critical FAR/FRR，移除 target-excluded proxy consensus/κ，改为
      单模型 position/repeat stability；继续报告 calibration/holdout 分层、有效 source-cluster n、
      coverage/abstention、latency/cost/confusion/bad cases。
- [x] 将 `IMAGE_QUALITY_AUDIT_MODEL` 默认值改为 `glm-5v-turbo`，保持 factory 独立 wiring 和 default-off/observe/history/canonical。
- [x] 将 subjective report 改为单模型 position/repeat stability，明确 `external_label_n=0`，移除 proxy gold、panel consensus/κ 和 target-to-proxy claim；保留 private/safe reports、privacy scan、non-activating candidate artifact 和 truthful claim gate。

## App-level live composition

- [x] 收缩 app composition root，只构造一个 `glm-5v-turbo` 智谱直连 one-shot transport，彻底移除图片 live 路径中的 ToAPIs/`glm-4.6v` endpoint、credential 和预算；
      provider-free runner 继续 fail closed。
- [x] 新增 hash-bound Zhipu-only frozen pricing schema，以 CNY 原生单位和 token rates 计算保守单次预留，保留
      unknown usage，不做汇率换算；pricing 有效期覆盖整个 frozen execution window。
- [x] 先验证 source/derived dataset/manifest/authorization/requests/pricing 及每个 request artifact，再只读取
      `AI_PLATFORM_API_KEY`；live output directory 必须由 safe store 新建为空目录，
      incomplete 返回非零，报告仍为 safe/non-activating。
- [x] 以 fake-httpx/CLI 覆盖精确智谱 endpoint、单 transport、identity/pricing/auth mismatch、无重试、密钥读取
      顺序、原生预算单位和 incomplete exit。
- [x] 冻结 `zhipu-vision-v1` 请求方言：视觉路径移除 `response_format`，固定禁用 thinking/sampling，拒绝任意
      provider options；默认 Reviewer JSON-object 方言不变，并将 provider-envelope 与 judge-content
      failure 分离为安全闭集 code，兼容旧 `invalid_provider_output` evidence。
- [x] 将 Zhipu judge-content 进一步拆成 framing/schema-or-invariant/allowlist-policy 安全失败码；仅该 profile
      允许外围空白或单个独立 lowercase `json` fence，随后复用 duplicate-key rejecting strict schema；v2
      图片 prompt 明确 exact keys、accept/reject/abstain 不变量与 unique/sorted/allowed issue arrays。
- [x] 生成并审核新的 Zhipu-only frozen pricing snapshot 后授权 live；此前五模型 snapshot 未复用。

## Validation

```bash
conda run --name edu-ai pytest \
  backend/tests/unit/test_model_panel.py \
  backend/tests/unit/test_image_quality_eval.py \
  backend/tests/unit/test_image_quality_panel.py \
  backend/tests/unit/test_image_quality_panel_app.py \
  backend/tests/unit/test_image_validation_ai.py \
  backend/tests/unit/test_content_worker_validation_wiring.py \
  backend/tests/unit/test_official_account_worker.py -q --no-cov
conda run --name edu-ai ruff check \
  backend/evals/image_quality_panel \
  backend/evals/model_panel \
  backend/app/image_quality_panel_main.py \
  backend/app/infrastructure/ai/image_quality_panel.py \
  backend/app/infrastructure/ai/factory.py \
  backend/app/core/config.py \
  backend/tests/unit/test_image_quality*.py
conda run --name edu-ai mypy --strict \
  backend/evals/image_quality_panel \
  backend/evals/model_panel \
  backend/app/image_quality_panel_main.py \
  backend/app/infrastructure/ai/image_quality_panel.py \
  backend/app/infrastructure/ai/factory.py \
  backend/app/core/config.py
cd backend && conda run --name edu-ai python -m app.image_quality_panel_main --help
make image-quality-panel-provider-free-smoke
make image-quality-eval
docker compose config --quiet
git diff --check
```

## Live completion

- [x] Preflight 验证 120-call ceiling、6 families、48 cases、family-disjoint split、rights/model/pricing/auth hashes，且图片路径不读取或引用 ToAPIs/`glm-4.6v` credential/identity。
- [x] 对 `glm-5v-turbo` 执行一次 v3 计划；首 case capability 通过，完整发送 120 个 frozen attempts，未选择性补跑。
- [x] 复算 holdout report/artifact hashes/privacy scan；119 completed + 1 provider-rejected，输出 non-activating single-model evidence，不改生产选择。

Evidence summary: `research/glm-5v-turbo-live-evidence-2026-09-03.md`.
