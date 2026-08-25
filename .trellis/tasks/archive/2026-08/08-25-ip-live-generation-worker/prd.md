# 恢复 IP 真实生图队列

## Goal

Restore the local IP asset generation worker so already queued jobs are claimed by the configured
real image provider, reach a truthful terminal state, and return generated assets to each
requesting browser-local profile.

## Confirmed Facts

- The API and frontend are running, PostgreSQL and MinIO are healthy, but no IP asset worker process
  or container is running.
- `.env` enables the IP asset hub, worker, generation, and image provider. The configured provider is
  `comfly`, the model is `gpt-image-2`, and the required provider credential is present.
- The repository already provides the supported `make ip-asset-worker` entry point; the worker owns
  durable claim, heartbeat, retry, provider call, verified storage, and terminal status handling.
- PostgreSQL currently contains two distinct `queued` jobs with zero attempts: one created at 09:48
  for Sai Xiansheng with Super Mario, and one created at 11:41 for a rocket beside Sai Xiansheng.
- The user explicitly authorized calls to the real image-generation model and the resulting cost.
- No new generation request is needed. Reusing the existing durable jobs avoids duplicate billing
  and preserves their idempotency/profile relationships.

## Requirements

- Start exactly one supported local IP asset worker lane with the reviewed environment and without
  exposing credentials in commands, output, or logs.
- Keep that worker running alongside the current local IP asset API/frontend session so future jobs
  are claimed automatically instead of remaining queued. Future local platform startup should use
  the supported stack/worker command rather than starting only the API and UI.
- Do not enqueue, clone, retry manually, or mutate either queued job outside the worker's existing
  durable claim/retry contract.
- Monitor the authorized job scope until every included job reaches `succeeded` or `failed`, allowing
  the existing bounded provider polling and retry behavior to run.
- Confirm that a successful job has one output asset and the expected personal-library membership;
  a failed job must expose only its safe error code and must not create an output asset.
- Keep API, frontend, PostgreSQL, MinIO, and unrelated workers running.
- Report the worker process state and final job refs/statuses without exposing prompts beyond the
  already confirmed local task descriptions, provider bodies, credentials, or private object paths.

## Acceptance Criteria

- [x] One IP asset worker is running and logs `generation_enabled=true` without a configuration or
      credential error.
- [x] Every authorized queued job is claimed at most once at a time and reaches a durable terminal
      state under the existing attempt/lease bounds.
- [x] Each succeeded job exposes an `output_asset_ref`, and the corresponding output is available to
      the originating local profile; failed jobs expose a bounded safe error code.
- [x] No duplicate generation job or duplicate provider request is created by this recovery action.
- [x] The frontend no longer remains indefinitely on the queued explanation for the processed job
      and can render the terminal result after its normal status polling/refresh.
- [x] The worker remains alive after the current jobs finish and is ready to claim later jobs during
      the local development session.

## Key Decisions

- Both queued jobs are authorized for real provider processing; there is no need to mutate or skip
  the older job.
- Run one worker lane, matching the current configured concurrency, to keep provider calls bounded
  and preserve queue order.
- Reuse the supported long-running worker entry point. Do not create a one-off direct provider
  script or bypass the durable queue.
- Treat starting the IP asset worker as part of future local IP platform startup.

## Out of Scope

- Changing provider, model, prompt, references, retry policy, generation code, or database schema.
- Re-enqueueing failed work outside the existing UI/idempotency flow.
- Converting the local worker into a production deployment or adding worker-health UI in this task.

## Planning Note

This is a lightweight operational recovery task. `prd.md` is the complete planning artifact; no
product-code change is currently indicated by repository evidence.
