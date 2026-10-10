# Research: remaining model-key consumers

- Query: Connect `official-account-local-worker`, `official-account-weekly-dag-worker`, and `governance-worker` to console model keys without changing their existing production behavior; determine minimal legacy-image closure, drain safety, and truthful readiness.
- Scope: internal source/spec analysis plus root-provided sanitized production snapshot; no provider calls, SSH, production mutations, or Git operations by this researcher.
- Date: 2026-10-10
- Worktree: `/root/projects/edu-ai-lead-agent/.trellis/worktrees/admin-pipeline-20261010`.
- Legacy snapshot: `/tmp/edu-admin-pipeline-integration/legacy-source`, supplied by root from running image `83a41e41`; sanitized manifest/config observations are `research/live-research.json`. Source references below are current worktree unless labelled legacy.

## Findings

### Files found

| File | Responsibility |
| --- | --- |
| `backend/app/core/config.py` | `Settings.model_secret_key` and cached console-overlaid settings. |
| `backend/app/domain/model_api_keys.py` | Provider-to-secret-field map and six expected consumer identities. |
| `backend/app/domain/secret_box.py` | AES-GCM encrypted-secret format and purpose-bound decryption. |
| `backend/app/infrastructure/model_api_keys_overlay.py` | Startup overlay, attempted/loaded/error state, daemon heartbeat and restart trigger. |
| `backend/app/official_account_worker_main.py` | Article worker provider/client construction and graceful drain. |
| `backend/app/official_account_weekly_dag_main.py` | Weekly entrypoint, single-edition routing, watcher admission and worker drain. |
| `backend/app/governance_worker_main.py` | Governance graph/client construction and concurrent worker drain. |
| `backend/app/infrastructure/official_account_single_runtime.py` | Single producer runtime, signal handlers and next-iteration boundary. |
| `backend/app/application/services/official_account_single_edition.py` | Single-edition producer claim and durable progress. |
| `backend/app/application/services/official_account_local.py` | Article lease heartbeat and protected paid-generation execution. |
| `backend/app/application/services/governance_worker.py` | Governance attempt/heartbeat/checkpoint lifecycle. |
| `backend/app/infrastructure/db/governance_repositories.py` | Claimable governance states and fencing. |
| `backend/app/infrastructure/db/official_account_local.py` | Article queue claims, lease recovery and frozen retry policy. |
| `backend/app/infrastructure/db/official_account_single_edition.py` | Producer/delivery claim windows, leases and history barrier. |
| `backend/app/application/services/model_api_keys.py` | Five-minute consumer visibility and latest-host projection. |
| `backend/app/api/v1/routes/admin_models.py` | Owner-only read projection of verified heartbeat metadata. |
| `compose.yaml` | Development service environment and stop/restart settings; root owns actual production override comparison. |
| `backend/tests/unit/test_model_api_keys.py` | Startup fallback, decryption, watcher timing and failure recovery. |
| `backend/tests/integration/test_admin_models.py` | Real PostgreSQL rotation, heartbeat upsert and nullable legacy diagnostics. |
| `backend/tests/unit/test_single_edition_runtime_review.py` | Single-mode routing stays outside legacy construction. |

### 1. Existing key contract is sufficient; all three entrypoints are already wired in source

- `get_settings()` is `@lru_cache` and invokes `with_console_model_keys(Settings())` once per process (`core/config.py:1319`). The new field is separate from `admin_secret_key` (`core/config.py:74`). Provider adapters must receive this returned Settings object; creating fresh `Settings()` elsewhere bypasses console values.
- Providers are `zhipu -> ai_platform_api_key`, `comfly -> comfly_api_key`, and `alibaba-visual -> visual_embedding_api_key` (`domain/model_api_keys.py:22`). The three targets are already in the fixed six-service consumer registry (`domain/model_api_keys.py:48`).
- Local article worker calls the watcher at `official_account_worker_main.py:129`, then constructs text generation/audit clients from the returned key at `:163`; lazy visual/image adapters retain the same Settings at `:65`, `:103`, `:181`, and `:232`.
- Governance calls the watcher at `governance_worker_main.py:35` and passes the same Settings into `governance_models` at `:60`.
- Weekly starts its watcher only for a persistent `worker` invocation, excluding `--once` and `--drain` (`official_account_weekly_dag_main.py:117`). It starts before single-mode routing (`:120`), so the actual single producer is covered. Status and CLI inspection commands do not start a watcher.
- In current single mode, the producer never creates a social/model client (`application/services/official_account_single_edition.py:1`); it delegates the real generation to durable article runs. Its consumer heartbeat means it loaded the shared settings, not that it personally made a model call.
- Source Compose has **no** `MODEL_SECRET_KEY` mapping. Root's production snapshot confirms the three target containers lack it. A `.env` entry by itself does not populate an unmapped container environment. Add only the existing model encryption key to these three services, not `ADMIN_SECRET_KEY`, not changed provider keys or URLs.

### 2. Verified startup diagnostics, caching and rotation behavior

`infrastructure/model_api_keys_overlay.py` implements the required verified contract:

1. Missing/blank encryption key returns original environment settings and does not start a watcher (`:71`, `:95`, `:149`).
2. It performs one short sync PostgreSQL read of latest versions; DB read failure preserves environment values, leaves loaded versions unknown, and records safe `configuration_unavailable` codes (`:82`, `:99`).
3. Attempted versions are recorded separately from successfully loaded versions (`:107`). Null ciphertext is explicit environment restore and counts as loaded (`:119`). Invalid master key / ciphertext retains the original provider value with `encryption_key_invalid` / `key_unreadable` (`:122`). It reports no plaintext/ciphertext in diagnostics.
4. Watcher singleton is process-wide (`_watch_started`, `:68`, `:153`). Its Settings object and loaded/attempted versions are immutable for the rest of that process; there is no in-place mutation of long-lived HTTP clients.
5. Heartbeat uses raw psycopg SQL, not SQLAlchemy admin models: `(service, host)` upsert of versions/errors/start/seen, and pruning only consumer rows older than one day (`:52`, `:162`). It introduces no content/publish work.
6. Poll interval is 60 seconds, minimum process uptime 120 seconds, plus 0–30 second jitter (`:44`). On a new attempted version it sends itself SIGTERM and returns (`:183`). An unchanged bad ciphertext does not cause a restart loop; a later version still does (`:142`).
7. A failed startup DB read with no stored keys will not restart merely to change diagnostic `configuration_unavailable` to `{}` (`keys_changed(None, {}) == False`, `:142`). Therefore deployment readiness must actually require clean startup reads rather than accepting an alive process.

`Settings()` validates environment prerequisites **before** overlay. For example governance in Zhipu mode requires a nonblank environment API key (`core/config.py:1031`). Preserve existing environment fallbacks; do not remove them because a console key exists.

Encryption dependency is **PyCryptodome**, `from Crypto.Cipher import AES` (`domain/secret_box.py:15`), not the `cryptography` package. Root's absence-of-cryptography observation is not a blocker. Root subsequently confirmed the actual legacy image has **PyCryptodome 3.23.0 and a successful `Crypto.Cipher.AES` import**; no dependency installation is needed. Retain an offline in-memory AES-GCM fixture roundtrip in the candidate smoke. Runtime lock currently pins `pycryptodome==3.23.0` (`backend/requirements/runtime.lock:1209`). Other dependencies are psycopg (snapshot 3.3.4), Pydantic, structlog and standard library. The overlay's only runtime `app.*` imports are the two new domain modules; `Settings` is TYPE_CHECKING except the deliberately separate environment helper.

### 3. Minimal legacy overlay closure: seven files, with a narrow config port

Compared actual files in root's legacy snapshot with current source (no Git operations):

| Release path under `/app` | Minimum change |
| --- | --- |
| `app/official_account_worker_main.py` | Current source differs only by watcher import + start call. |
| `app/official_account_weekly_dag_main.py` | Current source differs only by watcher import + persistent-worker start guard. |
| `app/governance_worker_main.py` | Current source differs only by watcher import + start call. |
| `app/infrastructure/model_api_keys_overlay.py` | New; copy verified overlay source. |
| `app/domain/model_api_keys.py` | New; copy provider/consumer contract. |
| `app/domain/secret_box.py` | New; copy encrypted-secret helper. |
| `app/core/config.py` | **Port only** `model_secret_key: SecretStr | None = None` and the cached `get_settings()` overlay wrapper into legacy Settings. |

The old config insertion point is `legacy/app/core/config.py:67`; its plain getter is `:1286`. Do not copy the complete current config: actual diff also changes scoring defaults, copy prompt/rules/repair, slot ranking, image budget fields and visual-selector validation. Those changes are not necessary for keys and can alter or reject the old runtime configuration.

Derived-config build recipe: first assert the legacy file SHA-256 equals the root-supplied manifest; assert exactly one `business_timezone: str = "Asia/Shanghai"` field and one cached getter returning `Settings()`; insert the typed optional model-secret field after that field; replace only the getter body with its lazy overlay import and `return with_console_model_keys(Settings())`. Assert the before/after diff contains only those two changes, record the derived output SHA-256 in the candidate manifest, and test the derived file itself. If the template work needs another config field, enumerate it as a separate approved insertion in the same recipe. This keeps every unrelated byte/version/validation rule from the actual running image.

No SQLAlchemy `db/models.py` upgrade is required by model overlay itself; heartbeat uses raw SQL against already deployed admin tables/0061. No new migration is required for these consumers. No complete AI factory, provider adapter, job repository, scheduler, dependency lock or runtime package upgrade is indicated by this closure. The template work has its own additional closure; union it explicitly, not by replacing an entire source tree.

Root reports global Compose `APP_IMAGE` currently renders the newer admin image while these containers still run the legacy image. Recreating a target without a specific narrowed candidate pin would silently bundle the newer behavior. Pin only the reviewed target services to the legacy-derived candidate and preserve unrelated container identities and configuration hashes.

### 4. Graceful key restart vs administrative deployment stop

The source loops already finish their in-flight unit of work after SIGTERM:

- Local: stop signal sets an event (`official_account_worker_main.py:130`); `finally` sets stop and awaits all worker tasks before closing clients/engine (`:264`). Each worker awaits full `executor.execute_next` before the next stop check (`:285`). The executor maintains a lease heartbeat around `_execute_claimed` and finishes it in `finally` (`application/services/official_account_local.py:873`).
- Governance: signal sets stop (`governance_worker_main.py:36`), main awaits workers after stop (`:93`), and loop awaits `execute_claimed_governance_job` before any next claim (`:109`). The job maintains its own heartbeat and checkpoint lineage (`application/services/governance_worker.py:60`, `:73`, `:148`).
- Weekly DAG: signal sets stop, current concurrent `process_once` batch is awaited, then no next batch starts (`official_account_weekly_dag_main.py:273`, `:283`). Single-mode producer uses its own signal handlers and awaits current `producer.process_once` (`infrastructure/official_account_single_runtime.py:33`, `:143`), removing handlers/disposing engine at the end (`:252`).

The watcher's self-SIGTERM is not a `docker stop` operation and does not itself schedule a later SIGKILL. `restart: unless-stopped` can restart the process after it exits. Administrative stop/recreate has a timeout that can force a still-busy worker to die; weekly has explicit 90 seconds, local/governance do not have an explicit source-Compose grace (`compose.yaml:390`, `:403`, `:586`). Do not equate any fixed short grace with a guarantee that a multi-model article finishes. Deploy only after idle admission, and recheck after controlled stop. Existing active work must not be killed just because an upgrade is ready.

Watch thread returns after sending SIGTERM, so a long drain can stop consumer heartbeats while it safely finishes its work. UI may subsequently show disconnected; do not relabel this as a successful key application or force-kill it to make the indicator green.

### 5. Queue/restart admission must include runnable work, not just running rows

- Governance claims queued/retry_scheduled jobs already available, or running jobs whose lease expired, without a schedule guard (`db/governance_repositories.py:368`). Claims increment attempt count and create a new lease (`:397`). A restart with a ready queue will make provider calls as ordinary worker behavior.
- Article worker similarly claims due queued work or expired running work (`db/official_account_local.py:1033`). Frozen retries can become failed/result_unknown when the old attempt budget or deadline is exhausted (`:1054`). Do not restart an active paid generation and rely on retry as though it were side-effect free.
- Single producer claims admitted/generating/preparing work, requiring fresh history-import barrier, due/available timestamps and no live lease (`db/official_account_single_edition.py:139`). The consumer's ready/delivering state matters for the combined template upgrade as well. Queued producer work can enqueue article generation as soon as the replacement starts (`application/services/official_account_single_edition.py:111`).
- Legacy weekly DAG may have pending/retryable nodes or active children even when a top-level summary is quiet; include run/node/attempt and execution allocation/reservation inventories for the actual production mode.

Before stop and before candidate start, capture all relevant queue/status/attempt/lease counts and identifiers, including future scheduled entries separately from runnable entries. Preserve rows/artifacts. If new work arrives in the admission gap, abort/retry the deployment window or drain normally; do not reset attempts or delete leases. A provider-free deployment smoke must not call worker `--once` or `--drain` against production: both can claim real queued work.

Root's current `research/queue-state.json` resolves the historical-state distinction: zero active leases and zero queued/running target jobs; sixteen pending weekly nodes belong to two terminal_failed runs, and two legacy draft jobs are ready but the active single-mode consumer bypasses them. Preserve those rows rather than treating all pending/ready counts as runnable work. Single mode is enabled in weekly/draft runtimes since 2026-09-16; legacy weekly worker/scheduler and draft auto-enqueue flags are false. Preserve ten delivered single editions through October 9, one expired/unknown September 16 edition, and five historical article result_unknown rows without leases. Re-evaluate admission against current mode/parent status and fresh time immediately before deployment; do not change these flags to satisfy the release.

### 6. Truthful readiness proof

The admin projection accepts the most recent heartbeat for a service from **any host** within five minutes (`application/services/model_api_keys.py:82`). A leftover old-host row alone is insufficient to prove the new container is connected.

Require all of the following after release:

1. Expected candidate image, source-file manifest, current container hostname and start time; no unexpected restarts.
2. For the six expected services, fresh real heartbeat. For the three upgraded services specifically bind DB `(service, host)` to the current container, with `started_at` consistent with the new process and `seen_at` after deployment. Prefer two observations spanning one 60-second poll, without creating a new key version.
3. `load_errors == {}` (not null), non-null loaded versions, and equality to latest stored provider versions. Zero stored keys legitimately yields `{}`/`{}`: it proves console read/heartbeat plus environment fallback, **not** a production decrypt of a stored ciphertext.
4. Compare mapped model-encryption-key equality/format server-side without printing values. In-memory isolated valid/invalid fixtures prove decryption behavior; no production key save/probe is needed.
5. Preserved work inventories/artifacts and no new lease-loss, generation-unknown, console-read or heartbeat errors. Container health/online state alone is insufficient.

`model_key_consumers` should not be reused as a template-capability heartbeat. Its fields mean loaded key versions; draft worker is not in `MODEL_KEY_SERVICES`; watcher refuses to run without model secret. Granting a draft worker MODEL_SECRET_KEY just for template reporting violates the separation and invents misleading evidence. Template runtime readiness needs its own narrowly named evidence/contract, owned by that workstream.

### 7. Existing tests and required gaps

Existing tests inspected (not rerun by this research-only agent):

- `tests/unit/test_model_api_keys.py:102`: no key means no DB access/watch; `:112` successful/failing decryption; `:135` DB failure preserves env; `:157` heartbeat/read/restart behavior; `:184` startup delay; `:198` unchanged bad version avoids restart storm; `:226` environment restore; `:241` DB recovery with a stored key.
- `tests/integration/test_admin_models.py:198`: real PostgreSQL startup overlay, repeated heartbeat upsert, six-service projection, valid `{}` verification, failed decryption and legacy null verification semantics. Existing fixture mostly exercises `content-worker`, not all target entrypoints.
- `tests/unit/test_single_edition_runtime_review.py:90`: once-only single mode returns before legacy construction; does not prove persistent mode starts watcher or real SIGTERM drain.
- Article worker fixtures cover partial/resume/paid-intent unknown handling (`tests/unit/test_official_account_worker.py:906`, `:1244`, `:1374`). These are job-level tests, not process-lifecycle tests.

Meaningful additions for implementation/check:

1. Provider-free tests for persistent watcher registration in each target, including weekly single mode and suppression for once/drain/status CLI paths.
2. Deterministic signal/drain tests for local, governance, weekly normal and single producer: hold one fake operation in flight, deliver registered SIGTERM, prove the operation is not cancelled, then release it and prove no subsequent claim and proper cleanup. No real `os.kill` in the test runner.
3. Candidate-image offline fixtures using **legacy-ported Settings**, proving existing default/version validation is preserved aside from the added field/getter; valid/invalid/missing key behavior and actual crypto import work.
4. Compose contract proves only model consumers receive MODEL_SECRET_KEY, the four target image pins are explicit, and unrelated secrets/environment/commands/mounts are preserved.
5. Heartbeat receipt checks bind current host/start and latest versions, not just existing service rows. If a product test is added, cover stale and legacy null verification so no false applied state appears.

## External references and versions

No external web references were needed or consulted; findings derive from repository code, project contracts and root-provided snapshot. Snapshot package metadata reports psycopg 3.3.4, SQLAlchemy 2.0.52, Pydantic 2.13.4, Alembic 1.18.5. Root separately confirmed PyCryptodome 3.23.0 and `Crypto.Cipher.AES` import in the actual legacy image. No provider requests were made.

## Related specs

- `.trellis/spec/backend/admin-console.md:128`: model key separation, process overlay, watcher and verified heartbeat contract; `:207` safe load error/restart comparison.
- `.trellis/spec/backend/logging-guidelines.md`: safe lifecycle/error metadata and secret/content redaction.
- `.trellis/spec/backend/quality-guidelines.md`: real DB tests for locking/upserts, offline provider-free defaults, typed config and deployment checks.
- `.trellis/spec/backend/governance-event-organization.md:122`: durable graph/checkpoint, SKIP LOCKED, heartbeat and fencing.
- `.trellis/spec/backend/execution-governance.md:150`: authorization, bounded capability timeout, cancellation reconciliation, preserved ledger.
- `.trellis/spec/backend/official-account-weekly-dag.md`: SIGTERM drains process_once, distinct worker/scheduler, checkpoint preservation and provider-free activation gates.
- `.trellis/spec/guides/production-mainline.md`: idle release, exact image lineage, narrow target service preservation and current production model-secret mapping.

## Caveats / Not Found

- Actual production source/config operations and package import probes remain root-owned; this research performed no remote access or production verification. Root's reported crypto probe passed; final candidate acceptance remains required.
- No direct process signal/drain tests for these three target entrypoints were found in the inspected unit/integration suite.
- The seven-file model-only closure is based on the supplied actual legacy source. The combined release must union the separately reviewed template closure and verify the built candidate imports, because shared runtime/config files overlap.
- There is no reason from this scope to add a new key table, migration, generic capability platform, provider rotation, provider call, scheduler rewrite, or broad Settings/client upgrade.
