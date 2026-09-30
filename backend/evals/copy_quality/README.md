# Copy quality: seeded defects and hook rubric

Two questions about the headline-hook Moments copy (generator v26 / auditor v20 / rules v13) that
the in-pipeline gates cannot answer about themselves:

1. **Do the gates stop a known defect?** For real accepted topics a first draft is generated with
   the production bundle. The unmodified draft is the control; each mutant carries exactly one
   defect (see `mutations.py`): anxiety or sales promises in the hook, a hook unrelated to the
   news, invented numbers or policy, a claim whose numbers trade places, a swapped organisation,
   a reversed meaning, an invented brand effect. Every draft passes through the production order:
   deterministic validator, then the model auditor only if no rule blocked, with the production
   audit policy. Outcome per mutant: blocked by the rules / blocked by the auditor / warned only /
   missed. A warned-only draft would still be pushed.
2. **Is the hook any good?** A judge model scores each hook on four yes/no criteria (`rubric.py`):
   about this news, parent-child oriented, natural, safe. The same judge also scores the seeded
   bad hooks, which shows whether it can tell a bad hook at all.

## Running (spends model calls)

Runs in a one-off container of the production image, reads the database read-only, writes nothing
to it. Avoid slot hours (06:00-08:30, 11:00-13:30, 17:00-19:30 CST).

```bash
scp -r backend/evals edu-ai-production:/tmp/evals && ssh edu-ai-production 'mkdir -p /tmp/evals-out && chmod 777 /tmp/evals-out'
# on the server, in /opt/edu-ai-lead-agent
sudo docker compose -p edu-ai-lead-agent --env-file .env --env-file .release.env run --rm --no-deps -T \
  -v /tmp/evals:/app/evals:ro -v /tmp/evals-out:/out -e PYTHONPATH=/app --entrypoint python content-worker \
  -m evals.copy_quality.runner run --from 2026-09-23 --to 2026-09-29 --limit 10 --output-dir /out --plan
```

- `--plan` lists the topics and stops without a model call. Drop it to run.
- `--max-calls` (default 220) is a hard cap over generation, audit and judge calls; when it is
  reached the run stops and the report says it is incomplete. Expect about 18 calls per topic.
- Outputs: `defects-report.md`, `hooks-report.md`, `hooks-sheet.csv`, `results.json`.
  `results.json` contains brand text; keep it out of the repository. Dated reports go to
  `reports/`.

## Human spot check

Open `hooks-sheet.csv`, fill the `human_*` columns with 1 or 0 (leave blank to skip), then:

```bash
cd backend && python -m evals.copy_quality.runner agreement --sheet hooks-sheet.csv
```

## Reading the results

- Every ratio shows its denominator; each draft is run once (temperature 0), so a single missed
  case is an observation, not a rate.
- Judge scores are model judgments by the same model family that wrote the hook. They are never
  human labels. Only the filled sheet is.
- "应由谁拦" is the design expectation. A defect assigned to the auditor that is only warned
  about is a policy finding for the operator, not a bug in this harness.
