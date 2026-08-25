# Recovery Result

## Worker

- Started through the supported `make ip-asset-worker` entry point.
- One effective worker lane remains running with concurrency `1` and generation enabled.
- API and UI return HTTP 200; PostgreSQL and MinIO remain healthy.
- Queue state after recovery: `queued=0`, `running=0`.

## Authorized Jobs

- `ipg_404f7f6e408a4716a39e`: `failed`, one attempt, safe error
  `provider_rejected`, no output asset, and no generated membership.
- `ipg_86afdfb0d2d8403bba6d`: `succeeded`, one attempt, output
  `ipa_134a6fc1557b48a3b417`; the asset is ready, private, and linked by exactly one generated
  membership to the originating profile and job.

## Integrity

- The database still contains three total generation jobs; recovery created no duplicate job,
  fingerprint, profile/idempotency identity, asset membership, or manual retry.
- No credentials, provider bodies, profile tokens, complete prompts, or private storage locations
  were recorded in the task result.
