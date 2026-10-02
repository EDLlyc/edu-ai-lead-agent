# Journal - LiYuchen (Part 2)

> Continuation from `journal-1.md` (archived at ~2000 lines)
> Started: 2026-09-17

---



## Session 88: Deploy WeChat marketing-header spacing

**Date**: 2026-09-17
**Task**: Deploy WeChat marketing-header spacing
**Branch**: `release/wechat-two-banner-framing-20260914`

### Summary

Released the versioned Cheng Yue marketing-header body spacer without a schema migration; corrected Compose variable loading during restart and verified the production runtime.

### Main Changes

- Added one WeChat-safe visible line between the V5 marketing header and article cover for newly prepared drafts, with immutable manifest/fingerprint versioning and legacy-byte compatibility.
- Loaded the immutable overlay image on production and restored standard .env-based Compose interpolation while passing the candidate APP_IMAGE explicitly.

### Git Commits

| Hash | Message |
|------|---------|
| `abfb89d` | (see git log) |

### Testing

- [OK] Scoped pytest, Ruff, mypy, HTML validator, isolated image smoke test, production /healthz, 12-container revision checks, schema check, and aggregate draft/article preservation checks passed.

### Status

[OK] **Completed**

### Next Steps

- Existing prepared drafts retain their frozen HTML; newly prepared V5 drafts receive the spacing automatically.


## Session 89: Repair agent, read-only ops tools, auditor v22 and two releases

**Date**: 2026-10-01
**Task**: Repair agent, read-only ops tools, auditor v22 and two releases
**Branch**: `feat/repair-agent-20260930`

### Summary

Built the tool-using copy repair agent on one typed tool registry shared by function calling, MCP and evals; gave tools a SELECT-only production role; ran the agent in nightly shadow; shipped auditor v22 with a brand-repeat check, a delivery watchdog and eval regression; deployed the a8 session's fresh candidate pool and held human picks. Work spans 09-30 evening to 10-01.

### Main Changes

- Repair agent (check_draft, find_evidence, replace_claim, drop_claim, rewrite_hook): eval v3 repairs 25/28 blocked seeded drafts, the same as full regeneration, 28/28 combined, with fewer input tokens per repair.
- Read-only role edu_ai_ops_ro (column grants, TEMP revoked, fail-closed verify), ops MCP servers, day trace dashboard, repair shadow job at 21:10; live 10-01 11:32-11:43 with seven write/privacy probes refused.
- Prompt-injection eval: the generator followed 0 of 30 instructions hidden in evidence. Ops assistant: reads run at once, draft edits wait for operator approval (sandbox only).
- Auditor v22 (closed error codes, system-decided severity): 26/26 vs v21 18/26 on seeded drafts, 0/5 clean blocked; brand-repeat check; delivery watchdog (alerts only to a separate ops webhook); eval repeats and regression; known-failure baseline 28 -> 0. Live 22:30 (image 7bffe4ed).
- Fresh candidate pool + held human picks (release 765fe1e, a8 session) deployed 23:12 (image 5887bce7).

### Git Commits

| Hash | Message |
|------|---------|
| `d15cf11` | (see git log) |
| `42e636e` | (see git log) |
| `4c330d8` | (see git log) |
| `ff70cb8` | (see git log) |
| `c9d12f9` | (see git log) |
| `2236e58` | (see git log) |
| `ae0825a` | (see git log) |
| `a6d5115` | (see git log) |
| `13cf91d` | (see git log) |
| `d9b534b` | (see git log) |
| `fc3e732` | (see git log) |
| `9644d63` | (see git log) |
| `72a4930` | (see git log) |
| `cc958d8` | (see git log) |
| `1d4d8b2` | (see git log) |
| `60bc652` | (see git log) |

### Testing

- [OK] Deploy gate PASS at c9d12f9, 72a4930 and 765fe1e; offline smoke in the overlay image; base file hashes matched the running image each time; six services healthy, 0 restarts, 0 errors after each release.

### Status

[OK] **Completed**

### Next Steps

- Owner: internal ops group webhook key for watchdog alerts.
- Decide a gradual repair-agent rollout once shadow data has enough valid cases (10-01-repair-shadow-ops).


## Session 90: Pool-aware visual planning live; Trellis records backfilled

**Date**: 2026-10-02
**Task**: Pool-aware visual planning live; Trellis records backfilled
**Branch**: `feat/repair-agent-20260930`

### Summary

Found why selector v3 reused cooled images (two-person pool had 2 prop-free images; PNGs over the 6 MiB budget were never selectable), made the planner aware of the fresh action pool, resized 12 oversized action images, replayed 186 production briefs and deployed. Backfilled Trellis task records for 09-30..10-02.

### Main Changes

- action_pool_capacity + planner penalty (1,500 empty / 300 one left), only with selector v3 and prop labels; evals/visual_replay/plan_sim.py.
- Replay: cooled reuse 56% -> 2%, distinct action images 15 -> 21, top image share 16% -> 8%.
- Live 13:31 (image b8fa7ada): 12 PNGs resized to 1536 px, host manifest rebuilt, backups under /var/backups/edu-ai/brand-materials/before-visual-pool-20261002T133009/.
- Trellis: task.json/PRD for four tasks; three delivered tasks archived; 10-01-repair-shadow-ops stays in progress.
- Resume v3 draft prepared locally (tmp/resume-draft), awaiting the owner; the official resume file was not changed.

### Git Commits

| Hash | Message |
|------|---------|
| `11ad19c` | (see git log) |
| `ff398b2` | (see git log) |
| `0cb0eca` | (see git log) |

### Testing

- [OK] Deploy gate PASS at 11ad19c; smoke on staged and live materials: 41 assets verified, 26 action images within budget; no job running; six services healthy, 0 restarts, 0 errors.

### Status

[OK] **Completed**

### Next Steps

- After the evening slot, compare live cooldown-exhausted picks with the replay.
- Owner review of resume v3.
