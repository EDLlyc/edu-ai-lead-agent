# Journal - LiYuchen (Part 2)

> Continuation from `journal-1.md` (archived at ~2000 lines)
> Started: 2026-09-02

---



## Session 87: 统一评测门禁与 Grounded Seed V2

**Date**: 2026-09-02
**Task**: 统一评测门禁与 Grounded Seed V2
**Branch**: `main`

### Summary

完成七套 provider-free 统一 eval-check，接入云效质量阶段与 Grounded Seed V2 三项检查；新增小赛和赛先生在空间站检索回归，修复 Grounded V1 在无私有清单干净检出中的可复现性，并用纯 Git index 快照验证完整门禁。

### Git Commits

| Hash | Message |
|------|---------|
| `05a54e7` | (see git log) |
| `50e82ed` | (see git log) |

### Status

[OK] **Completed**


## Session 88: Deploy weekly WeChat draft automation

**Date**: 2026-09-02
**Task**: Deploy weekly WeChat draft automation
**Branch**: `main`

### Summary

Implemented and deployed the Monday 09:00 Asia/Shanghai three-role WeChat draft-only workflow, verified all 12 application services on the immutable image with zero restarts and zero rollout jobs, recorded rollback evidence, and documented SSH heredoc stdin isolation after diagnosing the activation cutoff.

### Git Commits

| Hash | Message |
|------|---------|
| `40e4dec0ae82569fc798355d4515ab0009697c6f` | (see git log) |
| `a4a3c00` | (see git log) |

### Status

[OK] **Completed**


## Session 89: 真实 IP 检索 V2/V3 成对评测

**Date**: 2026-09-02
**Task**: 真实 IP 检索 V2/V3 成对评测
**Branch**: `main`

### Summary

新增 Seed V2 严格成对比较器与本地 live/报告/manifest 入口；在 41 张真实 IP 图片上完成 V2/V3 各 124 次 Alibaba Qwen3-VL Embedding 查询。V3 总体仅小幅提升且置信区间跨 0，holdout Recall@5 与 nDCG@5 下降，因此不升级。定位 6 条 partial_index 为硬过滤后零候选，并验证产物身份、隐私与业务聚合无副作用。未推送或部署。

### Git Commits

| Hash | Message |
|------|---------|
| `82b488a` | (see git log) |
| `c4fb010` | (see git log) |

### Status

[OK] **Completed**


## Session 90: Governed Reviewer enforce repair

**Date**: 2026-09-02
**Task**: Governed Reviewer enforce repair
**Branch**: `main`

### Summary

Implemented and independently verified a default-off calibrated Reviewer enforce flow with one bounded Writer repair, immutable revision lineage, durable execution/budget evidence, concurrency and crash recovery, exact downstream review binding, PostgreSQL migration guards, and provider-free regression evidence. No live provider was called.

### Git Commits

| Hash | Message |
|------|---------|
| `b8835d4` | (see git log) |

### Status

[OK] **Completed**


## Session 91: Governed Reviewer paired evidence harness

**Date**: 2026-09-02
**Task**: Governed Reviewer paired evidence harness
**Branch**: `main`

### Summary

Added and independently audited a provider-free paired Reviewer A/B evidence harness with frozen manifests and budgets, explicit local authorization, zero-retry attempt ledgers, HMAC-blinded human review, adjudication-first metrics, case-clustered confidence intervals, immutable evidence hashes, privacy-safe atomic files, and fail-closed no-uplift reporting. No provider, model, credential, or network call was made.

### Git Commits

| Hash | Message |
|------|---------|
| `c9db9a6` | (see git log) |

### Status

[OK] **Completed**


## Session 92: Governed Worker Reviewer Agent integration

**Date**: 2026-09-02
**Task**: Governed Worker Reviewer Agent integration
**Branch**: `main`

### Summary

Completed the four-part governed Worker-Reviewer program: strict editorial contract and provider-free canonical eval; default-off independently governed observe mode; calibrated one-repair enforce mode with immutable PostgreSQL lineage and crash-safe budgets; and a provider-free paired A/B evidence harness with human adjudication and no-uplift truth gates. Parent integration verified one Alembic head, scoped regression evidence, Compose, shell syntax, and diff integrity. No live model call or uplift percentage was claimed.

### Git Commits

| Hash | Message |
|------|---------|
| `ae525f1` | (see git log) |
| `d8daca0` | (see git log) |
| `b8835d4` | (see git log) |
| `c9db9a6` | (see git log) |

### Status

[OK] **Completed**


## Session 93: Agent retrieval compatibility canary

**Date**: 2026-09-03
**Task**: Agent retrieval compatibility canary
**Branch**: `main`

### Summary

Added strict Zhipu JSON-mode Agent compatibility guidance, a private two-cell retrieval A/B canary harness, and verified the live canary: both Agent arms completed without provider failures while enhanced Top-3 ranking failed the retrieval gate, so no uplift claim was made.

### Git Commits

| Hash | Message |
|------|---------|
| `cb03851` | (see git log) |

### Status

[OK] **Completed**


## Session 94: IP asset filter and GLM-5V metadata repair

**Date**: 2026-09-03
**Task**: IP asset filter and GLM-5V metadata repair
**Branch**: `main`

### Summary

Separated inferred IP search hints from explicit hard filters; added audited GLM-5V-Turbo V2 metadata repair with private artifacts, transient circuit breaking, verified MinIO content binding, row-locked CAS apply/restore, and locally applied 41 validated metadata updates idempotently without deployment or push.

### Git Commits

| Hash | Message |
|------|---------|
| `419243b` | (see git log) |
| `5c0ab05` | (see git log) |

### Status

[OK] **Completed**
