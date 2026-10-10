# Implementation and verification

- [x] Review approved findings, specs, existing tests, and current mainline; establish ownership.
- [x] Repair publication wording, uncertain outcome occupancy, recheck and audited resolution.
- [x] Repair bounded statistics backfill, date coverage and independent loop scheduling.
- [x] Repair model loaded/error state with migration and restart-loop regression tests.
- [x] Repair admin document routing in local development and built preview.
- [x] Regenerate backend/openapi.json and frontend generated schema.
- [x] Run targeted backend unit/integration and frontend behavior tests, lint/types and builds.
- [x] Run independent cross-layer check and final predeploy gate; fix material findings.
- [x] Verify browser hard navigation and mock failure/recovery states; expose validated preview.
- [x] Update contracts, prepare deployment/rollback evidence and commit scoped work.

Use /root/anaconda3/envs/edu-ai/bin/python. Frontend dependencies are the existing node_modules
symlink. No installs or production writes during development. Do not run integration suites in
parallel: shared local fixtures may reset the same database. Do not print credentials.
