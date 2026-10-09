# 后台模型 API key 与链接配置（运营后台第 8 项）

Parent `10-08-admin-console`. Planned 11/11–11/16 (3 d). Owner-only section.

## Today

- Everything is in env Settings (`core/config.py`):
  - Text, vision and audit: `ai_platform_base_url` / `ai_platform_api_key`, `ai_chat_model`
    (glm-5.2), `image_quality_audit_model`, `brand_ocr_model`, `image_ocr_model`,
    `ip_asset_recognition_model`. `ai_embedding_model` is validated to equal `embedding-3`.
  - Image: `toapis_*`, `comfly_*`, `image_model`.
  - Visual embedding: `visual_embedding_*`.
  - Agent workbench settings: `agent_workbench_openai_*`.
- `STRICT_VISUAL_POLICY` pins the comfly image model and the audit base URL (enforced in config).
- `get_settings()` is lru-cached. About 33 `*_main` processes read it once at start-up, so a
  change means restarting the services. Some entry points build Zhipu clients directly.

## Scope

- `model_endpoints` table: provider, purpose (chat, audit, OCR, image, embedding), base URL,
  encrypted key (same scheme as item 5), model name, enabled.
- Effective config = database row if valid, else env.
  - Processes reload it at the start of each job (no cache longer than one run), so no restart is
    needed.
  - The API and long-running workers re-read on a short TTL.
- Guards:
  - "测试连接" sends one tiny request and shows latency and the error before saving.
  - The base URL must be https on an allowlisted host pattern; no private IPs.
  - Pinned values (strict visual policy, embedding model/dimensions) are shown read-only; changing
    them needs a code release, because stored vectors and image policies depend on them.
  - Keys are write-only and shown as `••••1234`. Every change is audited (field names only).
- Roll back to the previous version with one click.

## Open

- Should operators be able to switch providers (e.g. Zhipu to another OpenAI-compatible API), or
  only rotate keys and URLs for the current ones? First cut: rotate and change the URL;
  switching providers comes later.

## Design (2026-10-09, first cut)

Production facts (10-09):
- Six long-running services hold model keys: acquisition-api, content-worker,
  official-account-local-worker, weekly-dag-worker, wecom-infographic-producer and
  governance-worker. All have `restart: unless-stopped`.
- Each builds its provider clients once at start-up.
- On SIGTERM, every worker finishes its current job, then exits.
- `ai_platform_base_url` and the Comfly/ToAPIs hosts are pinned by settings validation and the
  strict visual policy. Model names are tied to prompts and stored vectors.

Decisions:
- Scope is key rotation only, for three providers:
  - 智谱 `ai_platform_api_key` (text, audit, OCR, embeddings);
  - Comfly `comfly_api_key` (generated images);
  - 阿里云百炼 `visual_embedding_api_key` (image vectors).
  - Base URLs and model names are shown read-only. Changing them needs a code release.
  - ToAPIs is not used in production and is not shown.
- Storage: `model_api_keys`, an immutable version history per provider.
  - Each version holds a sealed key (AES-GCM, purpose-bound) or "use env".
  - Rolling back writes a new version that copies an old one.
- A separate `MODEL_SECRET_KEY` (not `ADMIN_SECRET_KEY`), so workers can open model keys but not
  WeChat AppSecrets.
- Effective key: `get_settings()` overlays the latest version per provider. It reads with a sync
  psycopg query and falls back to env on any failure. With `MODEL_SECRET_KEY` unset, nothing
  changes.
- No manual restart: a long-running service starts a watcher thread. When the latest versions
  differ from those it loaded, the watcher sends the process its own SIGTERM.
  - The service finishes its current job and exits; Docker restarts it with the new key, usually
    within about 2 minutes.
  - There is no restart in a process's first 2 minutes, at most one per process, with jitter.
- Guards:
  - Saving or restoring a version first makes one tiny request with that key and must succeed:
    智谱 a 1-token chat, Comfly `GET /v1/models`, 百炼 a short text embedding.
  - Owner only. Keys are write-only and shown as `••••1234`. The audit records provider and
    version only.

## Built (2026-10-09)

- Migration 0058: `model_api_keys` (provider, version, sealed key or null = env, last4, note,
  restored_from, probe latency, who/when).
- `Settings.model_secret_key` (`MODEL_SECRET_KEY`). `get_settings()` calls
  `infrastructure/model_api_keys_overlay.with_console_model_keys`.
  - Without the key it is a no-op. With it, a sync psycopg read gets the newest version per
    provider; any failure keeps env.
- `start_model_key_watch(settings)` runs in api_main (lifespan) and in the content, official
  account, weekly DAG (worker command only), infographic producer and governance workers.
- Probes: `infrastructure/ai/model_key_probe.py`.
- Owner API `/admin/models`: list, `POST {id}/test`, `POST {id}/keys`, `GET {id}/history`,
  `POST {id}/restore`, `POST {id}/use-env`.
  - Audit actions: `model_key.rotated`, `model_key.restored`, `model_key.env_restored`.
  - The 操作记录 page has a 模型 filter.
- Page 系统 · 模型配置: a card per provider (current key, status, fixed URL and models), change
  key (test, then save), history with restore, and back to the server key.
  - It re-reads every 30 s while a change waits for the restart.

## Deploy notes

- Generate `MODEL_SECRET_KEY` (`python -c "from app.domain.secret_box import new_key;
  print(new_key())"`) into the server `.env`.
- Pass it to acquisition-api, content-worker, official-account-local-worker,
  weekly-dag-worker, wecom-infographic-producer and governance-worker, plus any cron service
  that uses model keys.
- Keep the env keys as they are: they are the fallback and the "改回服务器配置" target.
- Saving a key restarts those six services between jobs within about 2–3 minutes. Avoid the
  slot hours for the first real rotation.

## Tests

- Unit:
  - providers map to Settings secrets;
  - probes (request shape, key scrubbing, timeout);
  - overlay (no key, stored keys, misplaced ciphertext, DB down);
  - `keys_changed`;
  - the watch sends SIGTERM after a change.
- Integration:
  - owner only, the write guard and 404;
  - a failed test refuses the save; rotate, restore, use-env and 409s; history; audit without
    keys;
  - the overlay reads Postgres; another `MODEL_SECRET_KEY` keeps env; no key gives 503.
- Frontend: tests and the menu.
- Local smoke:
  - the page;
  - a worker-shaped process stopped itself 1 s after the save, and a fresh one loaded ••••1111;
  - the API stopped itself 133 s after start.
- Predeploy gate PASS.

## Follow-up (2026-10-09): honest per-service status

Production finding: only six services run the 10-08 image. The 公众号 pipeline, governance and two
schedulers still run the 09-28 image (`83a41e41`). Three of those hold the 智谱 key:
official-account-local-worker, weekly-dag-worker and governance-worker. Until they are upgraded,
they ignore console keys.

- Migration 0059 `model_key_consumers`: every watched process upserts (service, host, versions
  it loaded, started_at, seen_at) once a minute and at start. Rows older than a day are pruned.
- `GET /admin/models` returns `consumers`: the six expected services (`MODEL_KEY_SERVICES`) and
  whether each reported in the last 5 minutes.
- The page shows, per provider, "已在 x/y 个服务生效", how many wait for a restart and how many
  are not connected. It also has a per-service table, and a notice naming the services that are
  not connected: keep the server's old key valid until they are upgraded.
- The watch now waits out the 2-minute minimum uptime only when a change is found.
