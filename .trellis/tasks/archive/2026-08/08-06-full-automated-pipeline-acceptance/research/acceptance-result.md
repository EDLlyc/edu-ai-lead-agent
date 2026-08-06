# Real Acceptance Result

## Run Identity

- Preview run: `026d0ca0-eed2-42f9-98c6-887fd9941139`
- Isolated business date: `2026-08-08`
- Output: `output/preview/026d0ca0-eed2-42f9-98c6-887fd9941139/manifest.json`
- Enterprise WeChat flags at execution: `wecom_enabled=false`,
  `wecom_auto_delivery_enabled=false`

## Observed Durable Outcomes

| Stage | Durable ID | Terminal result |
| --- | --- | --- |
| Acquisition | `99d2ec5e-e70c-456e-ab7a-09234e236774` | `succeeded`, 9/9 source jobs succeeded |
| Governance | `5b578bf4-7f46-4084-add5-7a3502e4f40c` | `partially_succeeded`, 17 usable and 4 review outcomes |
| Topic selection | `c1af5794-31bd-4b02-8611-b546449a31cb` | selected official science-policy topic |
| Copy generation | `17214de8-ab45-4836-9d16-b3f8b34f63a4` | `accepted`, validation passed and audit accepted |
| Material package | `77d866b0-0337-4755-bae4-9e236edf5b15` | `awaiting_manual_use` |
| Image artifact | `a329530b-90b4-4777-8243-d88970d1bfa3` | `succeeded`, private immutable PNG, 1024x1024 |

The selected topic was the Ministry of Education's science-education "learning by doing" action.
The selection report recorded `priority_applied=true` and `priority_reason=science_policy` under
`science-policy-priority-v2`; this confirms that only a qualifying science-policy item was given
Top 1 priority.

## Safety and Operational Checks

- Local image export is a valid `1024x1024` RGB PNG; its local API download returned HTTP 200
  with `image/png` and 1,392,227 bytes.
- Querying `wecom_delivery_jobs` for the new material package returned zero jobs.
- The existing locked result for `2026-08-06` remained unchanged.
- Compose services remained running and API health returned OK.
- `python -m pytest backend/tests/unit/test_preview_run.py backend/tests/unit/test_image_generation.py -q`
  passed: 43 tests.
- `git diff --check` passed. The pre-existing user-owned
  `.agents/skills/trellis-break-loop/SKILL.md` modification was not touched.
- The redacted manifest did not contain provider API-key names, MinIO identifiers, the configured
  output-CDN host, or `sk-` tokens.

## Finding: Preview Audit Status Projection

The real material package and copy audit both persisted `accepted=true`, but the generated preview
manifest projected both as `status="pending"`.

Evidence: the manifest's `audit` and `copy.audit` records contain `accepted: true`, `issues: []`,
and `version: "preview-v2"` alongside `status: "pending"`. This is contradictory display data and
can cause the preview UI to imply that an already accepted audit is still in progress.

The root cause was `backend/app/preview_run.py::_quality_snapshot`: it derived a status from
the `passed` boolean but did not derive `accepted`/`rejected` from the audit's `accepted` boolean.
The core content pipeline remains successful; this is a preview/reporting-contract defect that needs
a narrowly scoped repair and regression test before the acceptance task can be called fully clean.

## Repair Result

- `_quality_snapshot` now preserves explicit `status`, maps `passed` to `passed`/`failed`, maps
  `accepted` to `accepted`/`rejected`, and otherwise retains the caller default.
- Regression coverage asserts both audit boolean outcomes, explicit status precedence, and both
  top-level and nested `copy.audit` manifest locations.
- `make backend-check` passed: Ruff format check, Ruff lint, mypy, and all 458 backend tests.
- `make doctor` passed, API health remained OK, and `git diff --check` passed.
- No paid provider call or durable database record was created for this display-only repair. The
  original manifest remains preserved as historical pre-fix evidence; future previews use the
  corrected projection.
