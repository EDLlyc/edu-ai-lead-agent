# Execution

- [x] Inspect prior audit and approval, specs, API boundaries; define ownership.
- [x] Mobile cards/reflow, statistics, controls and statuses.
- [x] Unsaved navigation/form guard and explicit environment badge.
- [x] Draft/published pagination with context/race/error handling.
- [x] Independent review and meaningful behavior regressions.
- [x] Full frontend lint/types/tests, API parity and both builds.
- [x] Browser verify mobile/desktop, history guards, pagination/races, no provider writes.
- [x] Refresh isolated preview; capture screenshots/results and deployment prerequisites.
- [x] Update specs, scoped commit, archive and journal.

Work only in admin worktree on feat/admin-usability-20261010. Preserve frontend/node_modules
symlink and production-linked dist-admin/preview5180. Frontend tests use fakes; root handles final
browser and complete tests after workers stabilize. Python tools use worktree PYTHONPATH=backend.
