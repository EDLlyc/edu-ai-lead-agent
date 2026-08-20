# Local acquisition rerun contract

## Allowed

- Load root `.env` without printing credentials.
- Reuse healthy local PostgreSQL and MinIO.
- Start exactly `app.api_main` and `app.worker_main` on loopback/local process boundaries.
- POST once to `/api/v1/acquisition-runs` with a unique bounded `Idempotency-Key` and an empty body.
- Poll only the created run and its jobs until a bounded deadline.
- Read safe aggregate counts needed to prove downstream deltas are zero.

## Forbidden

- No scheduler, governance worker, content worker, rerank call, copy/image/OCR, dispatcher or delivery.
- No source mutation, manual SQL writes, deletion, retry/requeue, provider call outside normal source fetches,
  production access, SSH, deploy, commit or push.
- No secrets, fetched article bodies or private paths in the report.

## Cleanup

Track PIDs started by this task and terminate only those exact processes. Verify the loopback API
port and acquisition worker process are absent afterward. Preserve pre-existing infrastructure.
