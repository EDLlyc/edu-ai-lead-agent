# 恢复 IP 本地服务

## Goal

Restore the standalone local IP asset platform after the development runtime stopped, making the
login page, gallery, AI creation studio, API, storage, and one real generation worker available
again at their documented local addresses.

## Confirmed Facts

- PostgreSQL is healthy and still contains all five generation jobs: four succeeded and one safely
  failed. There are no `queued` or `running` jobs, so service startup will not immediately invoke the
  paid image provider.
- MinIO reports healthy, but the current restarted container set must be normalized through the
  supported Compose stack before application services rely on its network/ports.
- No API, Vite frontend, or IP asset worker process/container is running. Ports `8000` and `5173`
  are free, and both local HTTP checks currently return 502.
- `.env` still enables the IP asset hub, worker, real generation, and `comfly / gpt-image-2` provider.
- The reviewed runtime contract defines `make ip-asset-stack-up` for API plus exactly one Worker and
  `make ip-asset-ui` for the standalone Vite frontend.
- The user previously authorized real provider processing and explicitly asked that future IP
  platform startup include the Worker.

## Requirements

- Start the supported IP asset Docker stack with `acquisition-api` and exactly one
  `ip-asset-worker`, preserving PostgreSQL/MinIO data and the existing unrelated containers.
- Start one standalone Vite process on `127.0.0.1:5173` with the IP asset feature enabled.
- Do not start duplicate API, UI, or Worker processes; resolve ports and process/container identity
  before and after startup.
- Do not enqueue, retry, mutate, or delete generation jobs. With no queued work, startup must make
  zero image-provider calls.
- Verify API health, UI HTTP availability, IP capabilities, login-route rendering, PostgreSQL and
  MinIO health, one Worker lane, and zero queued/running generation jobs.
- Leave API, UI, and Worker running after verification so the supplied IP asset URL remains usable
  and later user-submitted jobs can be processed by the normal durable queue.
- Keep credentials, provider bodies, profile tokens, and private storage paths out of output and
  logs.

## Acceptance Criteria

- [x] `http://127.0.0.1:8000/healthz` returns 200 from one API service.
- [x] `http://127.0.0.1:5173/ip-assets` returns 200 and the browser route presents the standalone
      demo login before loading the protected gallery/studio.
- [x] Exactly one effective IP asset Worker lane remains running with generation enabled.
- [x] PostgreSQL and MinIO are healthy and all pre-existing job/asset data remains intact.
- [x] Generation queue counts remain `queued=0` and `running=0`; startup creates no job and makes no
      provider call.
- [x] API, frontend, and Worker remain alive after the smoke checks finish.

## Key Decisions

- Prefer the documented detached Compose stack for API/Worker so `restart: unless-stopped` can
  recover those services with the Docker runtime.
- Keep the Vite development UI as one persistent local process because no production frontend
  container is part of the current IP asset MVP.
- This is operational recovery only; repository evidence does not indicate a product-code or schema
  defect.

## Out of Scope

- Changing application code, Compose definitions, environment values, database schema, provider,
  model, prompts, or retry policy.
- Retrying the historical `provider_rejected` job or creating a new paid generation request.
- Deploying the platform to a public or remote host.

## Planning Note

This is a lightweight operational task. `prd.md` is the complete planning artifact.

## Completion Evidence

- Independent runtime verification passed: API health and capabilities returned 200; the real
  browser flow displayed the demo login, loaded 42 shared assets, and opened the AI creation page
  without console errors.
- PostgreSQL and MinIO remained healthy. The five historical generation jobs remained four
  succeeded and one failed, with `queued=0` and `running=0`; startup created and claimed no job and
  emitted no provider request.
- One API, one Vite process, and exactly one generation-enabled Worker remained alive through a
  delayed second check. No application, configuration, schema, or database-data change was made.
- Deferred: `backend-migrate` does not inherit the image-provider environment needed by current
  Settings validation. The database was already at Alembic head `20260825_0036`, so this did not
  block the recovered runtime; fixing the cold-start Compose contract remains separate work.
