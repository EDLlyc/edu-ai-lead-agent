# 六源图片 Model-Panel Proxy：实施计划

## Dependency gate

- [ ] 父任务 shared contracts、transport、budget/auth/private I/O 已通过 provider-free focused tests。
- [ ] Manifest 固定 shared contract version/SHA，不复制共享 schema。
- [ ] Reviewer 子任务无结果依赖，不读取其 blind map、votes 或报告。

## Implementation

- [ ] 新建 `backend/evals/image_quality_panel/` 与 `sources.v1.json`；冻结 6 source families、blob/content SHA、
      MIME/dimensions/derivatives 和用户授权依据，拒绝 dirty/private/missing-rights inputs。
- [ ] 实现 hash-seeded Pillow transforms 与 48 derived pair cases，六维/36-12/24-24 平衡；按 family 分组 split。
- [ ] 定义每臂 1–2 图、optional reference、HMAC blind map、gold A/B balance 和 hash-bound grouping/order。
- [ ] 扩展共享 image vote profile：pair choice + A/B decision/critical/issues；实现完整 BA arm inversion。
- [ ] 生成三 panel + 两 candidates 的 `5*120<=600` plan，把四图 diversity 放到每模型首个 call；失败停止该模型。
- [ ] 实现 objective pair/arm metrics、critical FAR/FRR、target-excluded proxy consensus、κ eligible coverage、
      position/repeat bias、coverage/abstention、latency/cost/confusion/bad cases。
- [ ] 新增 `IMAGE_QUALITY_AUDIT_MODEL=glm-4.6v` 并修正 factory，保持 default-off/observe/history/canonical。
- [ ] 实现 private/safe reports、privacy scan、non-activating candidate artifact 和 truthful claim gate。

## Validation

```bash
conda run --name edu-ai pytest \
  backend/tests/unit/test_model_panel.py \
  backend/tests/unit/test_image_quality_eval.py \
  backend/tests/unit/test_image_quality_panel.py \
  backend/tests/unit/test_image_validation_ai.py \
  backend/tests/unit/test_content_worker_validation_wiring.py \
  backend/tests/unit/test_official_account_worker.py -q --no-cov
conda run --name edu-ai ruff check \
  backend/evals/image_quality_panel \
  backend/app/infrastructure/ai/factory.py \
  backend/app/core/config.py \
  backend/tests/unit/test_image_quality*.py
conda run --name edu-ai mypy \
  backend/evals/image_quality_panel \
  backend/app/infrastructure/ai/factory.py \
  backend/app/core/config.py
make image-quality-eval
git diff --check
```

## Live completion

- [ ] Preflight 验证 600-call ceiling、6 families、48 cases、family-disjoint split、rights/model/pricing/auth hashes。
- [ ] 对五模型各执行一次计划；首 case capability failure 停止该模型，不选择性补跑。
- [ ] 复算 holdout report/artifact hashes/privacy scan；输出 proxy evidence 或 insufficient-evidence，不改生产选择。
