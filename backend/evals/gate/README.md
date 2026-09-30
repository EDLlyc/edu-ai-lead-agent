# Pre-deploy gate

Run before building any production image:

```bash
make predeploy-check            # all suites + unit/contract tests (about 10 minutes)
make predeploy-check-fast       # evaluation suites only (about a minute)
```

- Needs no database, model or network. Exit code 0 = pass, 1 = fail.
- Runs every provider-free evaluation (`topic_golden`, `same_topic_golden`, `topic_rerank`,
  `brand_retrieval`, `agent_workbench`, `image_quality`, `ip_asset_retrieval`, `visual_retrieval`,
  grounded seed). A suite that cannot run on this machine for a documented reason is **skipped**,
  never passed.
- Unit and contract tests are compared with `backend/tests/known-failures.txt`. A failure that is
  not in the baseline fails the gate; a baseline entry that now passes asks you to remove it. The
  baseline may only shrink: fix or delete a broken test, do not add to the list to get a release
  out.
- Paste the last line of the report (`predeploy gate PASS @ <commit> …`) into the rollout note.

Evaluations that spend model calls (`copy_replay`, `copy_quality`) are not part of the gate; run
them when a prompt, rule or model version changes.
