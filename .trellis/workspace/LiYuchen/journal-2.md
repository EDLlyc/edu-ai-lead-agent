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
