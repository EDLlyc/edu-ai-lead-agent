# Governed Reviewer opt-in live A/B evidence

This package is an evidence harness, not a provider integration. It freezes a paired experiment,
accepts externally produced attempt ledgers, blinds the output artifacts for human review, and
recomputes quality/cost evidence from human adjudication. The checked-in dataset is synthetic and
contains no production article, user, credential, prompt, or provider response.

## Safety boundary

- `prepare` is a provider-free dry run. It writes a hash-bound manifest, a local `0600` blinding
  key, and an `authorization_missing` failure ledger with `live_model_calls=0`.
- An authorization is a separate operator-approved local data artifact, not a cryptographic
  signature or provider receipt. Provider, model, sample count,
  repetitions, exact maximum request count, per-call ceiling, total ceiling, manifest hash, and
  time window must all match.
- `preflight` validates that artifact only. It never reads environment credentials and never
  contacts a provider.
- `live` deliberately fails closed with `executor_not_installed`. A concrete provider adapter must
  be separately reviewed, authorized, and injected through `AttemptExecutor` before any run.
- Every attempt is invoked once. There is no per-case or whole-suite retry. An ambiguous executor
  exception stops the suite and writes a safe ledger without copying the exception or raw body.
- Baseline and treatment are bound to the exact same initial Article SHA-256. Baseline may make
  zero provider calls; treatment can only record the prefix `reviewer_r1 -> repair_writer ->
  reviewer_r2`, with no second repair.
- Every attempt binds the canonical authorization SHA-256 as well as the manifest SHA-256. A future
  live adapter must still revalidate the local authorization immediately before every provider
  boundary; this provider-free package makes no authenticity claim for a hand-authored artifact.
- Private evidence inputs must be regular files without group/other permissions. Outputs are
  exclusive `0600` files in a new `0700` directory; symbolic-link targets and overwrites fail
  closed.

## Provider-free dry run

Use an ignored output directory. Pricing values and hashes are inputs because the repository must
not silently fetch a mutable price page.

```bash
cd backend
python -m evals.official_account_reviewer_live_ab.runner prepare \
  --output-dir ../output/reviewer-live-ab/example \
  --run-ref reviewer-ab-example \
  --git-sha 0000000000000000000000000000000000000000 \
  --provider provider-name --model model-name \
  --window-start 2026-09-03T01:00:00Z --window-end 2026-09-03T02:00:00Z \
  --max-cost-per-call-usd 0.05 \
  --pricing-effective-date 2026-09-02 \
  --input-usd-per-million 1 --output-usd-per-million 2 \
  --reasoning-usd-per-million 2 \
  --pricing-source-sha256 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --registry-sha256 bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
```

For the default 12 cases and one repetition, the manifest freezes exactly 36 maximum provider
calls. With a `$0.05` per-call ceiling, the total ceiling is exactly `$1.80`; it is derived rather
than entered independently.

## Evidence files

- `manifest.json`: immutable dataset, initial-article, version, model, time, bootstrap, and budget
  identity.
- `authorization.json`: the explicit local approval bound by canonical hash to every attempt,
  report, and calibration candidate. It is retained separately from the blinded worksheet.
- `attempts.jsonl`: one durable terminal row per case/repetition/arm, including each provider-call
  phase, status, latency, usage or explicit unknown usage, and safe failure code.
- `worksheet.jsonl` / `worksheet.csv`: candidate `A/B` hashes and non-semantic blinded artifact IDs
  without source artifact refs, arm, system verdict, provider, or model identity.
- `blind-map.jsonl`: separately retained operator mapping from blind IDs to arms and source artifact
  refs; never distribute it with the worksheet.
- `judgments.jsonl`: independent human annotations. `adjudications.jsonl` is the primary gold
  input. LLM judge data is intentionally not accepted by the report builder.
- `report.json` / `report.md`: hash-bound inputs, Pass@1/Pass@2, critical-defect recall, false
  accept/reject, manual
  review, P50/P95 latency, tokens, known/unknown cost, paired bootstrap CI, repeat variance,
  failure taxonomy, and bad cases.
- `failure-ledger.json`: safe blocked outcome with no uplift claim.

False-accept rates use human-gold negatives as their denominator; false-reject rates use
human-gold positives. A missing gold class remains `unknown`. Bootstrap resampling is paired and
clustered by case so repetitions are not treated as independent articles, while repeat variance is
reported separately.

The report emits no paired estimate and no resume claim when attempts or human labels are missing,
any provider failure is present, usage/cost is unknown, the calibration subset lacks independent
double annotation, or the minimum sample gate fails. `confirm-report` only creates a
non-activating calibration candidate from an eligible report and the exact human confirmation;
the operator must also supply the exact canonical report SHA-256 printed by `report`. It never
changes `OFFICIAL_ACCOUNT_REVIEWER_MODE`.

The `report` command requires an explicit `--failure-ledger` output path. An ineligible report is
retained for diagnosis, a no-uplift ledger is written atomically, and the command exits with status
`2`; an eligible report exits with status `0` and does not create that failure file.
