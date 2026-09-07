# Research: Prospective strict visual release readiness

- Query: Can the committed native-generation/final-upload-review candidate be safely packaged and activated with the current deployment mechanisms and service configuration?
- Scope: Internal candidate source, committed review evidence, provider-free local configuration probes, and explicitly attributed main-session live observations. No implementation or deployment.
- Date: 2026-09-07, Asia/Shanghai.
- Candidate supplied by main: `4c353b2d924403efda91a5ad1967a6f8c50eaa79`; product commit `69c12c51747c1b80568f64a8e1f36848fd5f6a8d`; candidate worktree `.trellis/worktrees/visual-quality-preview`; base `218015e`, runtime equivalent to live `6154c78`.
- Researcher: `/root/strict_visual_release_research`. No Git operation, SSH, model/provider request, image build, queue creation, service mutation or secret read was performed. Only this research file was written. Research role isolation prohibited loading implement/check JSONL; PRD, design, implement and required specs were read directly instead.

## Findings

### Verdict: NO-GO for deployment or strict activation

The durable strict path has substantial change-relative test evidence, but the committed candidate is **not activatable as-is through the actual Compose topology**. The new marker is not injected into containers, and the inherited generated-visual setting conflicts with intentionally image-disabled services. This is an executable configuration defect, not merely missing documentation or a hypothetical provider outage. Even after repairing that gap, no reviewed current transaction covers this source, schema 0043, scoped configuration, all twelve application processes and rollback conditions.

Do not push, package, deploy, change protected environment bytes or run an old incident operator on the authority of this report. The current user-approved scope is preparation/read-only release checks. Request a narrowly bounded wiring/validation implementation next; release-operation authority and gates remain separate.

### 1. Missing Compose inputs and inherited cross-service startup failure

The new settings exist in `backend/app/core/config.py:301` and `:432`; examples appear in `.env.example:205` and `:346`. However, the entire candidate `compose.yaml` contains neither `OFFICIAL_ACCOUNT_LOCAL_VISUAL_PIPELINE_VERSION` nor `IMAGE_QUALITY_AUDIT_MODEL`.

The primary `.env` is a Compose interpolation input, not an automatic container environment. `backend/Dockerfile:35` sets `/app` and copies only the package manifests, Alembic and app code at `:38`; Compose does not mount `.env` or use service `env_file`. Therefore adding the marker to the protected host file does not expose it to container `Settings`.

The existing `OFFICIAL_ACCOUNT_LOCAL_GENERATED_VISUALS_ENABLED` is shared at `compose.yaml:222`. Every Python service inherits `backend-environment`; the local worker repeats that interpolation at `:580`. Two failure layers result:

1. With generated=true and the missing marker, the API/content/local image-capable services hit the **legacy one-attempt requirement** at `config.py:761`. Production legitimately retains `IMAGE_MAX_ATTEMPTS=3`; strict transport, not the global image setting, owns its one-POST fence. Changing the global count to 1 would alter unrelated workflows and is not an acceptable repair.
2. Image-disabled services fail the preceding unconditional generated-feature validation at `config.py:750` even if the new marker is added. They deliberately lack image enable/provider settings and Comfly credentials. Examples: migration/shared anchor (`compose.yaml:82`), acquisition workers/scheduler (`:350`), governance workers/scheduler (`:366`), weekly scheduler/DAG (`:391`, `:433`), draft consumer (`:455`), and WeCom (`:676`). Passing all image credentials to these services would violate isolation, not solve ownership correctly.

The shared generated/provider coupling predates this change: the clean `weekly-source-preflight` base contains the same dependency check in `backend/app/core/config.py:744` and legacy one-attempt check at `:755`. Strict activation newly exposes it. The missing new marker wiring is specific to this candidate; it was not exercised by the prior Python-only strict success tests. Do not reclassify it as one of the 33 already-baselined pytest failures.

#### Actual offline reproduction

Executed candidate `Settings`, not a mock, against the output of:

```text
docker compose --env-file /dev/null -f compose.yaml --profile '*' config --format json
```

The command was launched through a subprocess with a complete synthetic environment, `COMPOSE_DISABLE_ENV_FILE=1`, no inherited credentials, and capture-only output. Settings ran under an empty process environment with `_env_file=None`; Python bytecode was disabled. There was no Docker service creation, daemon operation, external network call, or output file. Only service names and safe validation messages were printed.

Synthetic overrides reproduced the relevant live shape without live secrets: test environment; local feature/worker true; Zhipu and exact direct base; fake test-only keys only where Compose already injects them; image Comfly/gpt-image-2; `IMAGE_MAX_ATTEMPTS=3`; image window/timeout 300; marker and GLM audit model present in the interpolation environment. Other external-effect flags stayed off.

| Probe | Result over 13 Python services including migration |
| --- | --- |
| Current generated=false | **13/13 Settings constructions pass**; marker absent in every rendered service |
| Global generated=true, host marker set | **13/13 fail**: three image-capable services reject legacy attempt count; ten image-disabled services reject generated prerequisites |
| Same rendered maps, marker added only in memory | API/content/local worker pass; **10/13 still fail** generated prerequisites |

The third row is explicitly an in-memory diagnostic, not a code/config fix. A first exploratory probe omitted the live 300-second window and encountered the pre-existing local Compose fallback `IMAGE_PROVIDER_WINDOW_SECONDS=900` versus the Settings bound 300. The definitive matrix above supplies 300, matching main's live read-only observation, and isolates the actual new activation blocker. Do not present that fallback as a current production failure.

Reproducible diagnostic, from the candidate directory (all shown credentials are synthetic; output contains no input fields):

```sh
env -i PATH=/usr/bin:/bin PYTHONPATH=backend PYTHONDONTWRITEBYTECODE=1 \
  /root/anaconda3/envs/edu-ai/bin/python -B - <<'PY'
import json
import subprocess
from pydantic import ValidationError
from app.core.config import Settings

fixed = {
    'PATH': '/usr/bin:/bin', 'COMPOSE_DISABLE_ENV_FILE': '1',
    'APP_ENV': 'test', 'AI_PROVIDER_MODE': 'zhipu',
    'AI_PLATFORM_BASE_URL': 'https://open.bigmodel.cn/api/paas/v4',
    'AI_PLATFORM_API_KEY': 'local-test-only',
    'COMFLY_API_KEY': 'local-test-only',
    'OFFICIAL_ACCOUNT_LOCAL_ENABLED': 'true',
    'OFFICIAL_ACCOUNT_LOCAL_WORKER_ENABLED': 'true',
    'IMAGE_ENABLED': 'true', 'IMAGE_PROVIDER_MODE': 'comfly',
    'IMAGE_MODEL': 'gpt-image-2', 'IMAGE_MAX_ATTEMPTS': '3',
    'IMAGE_PROVIDER_WINDOW_SECONDS': '300',
    'IMAGE_PROVIDER_TIMEOUT_SECONDS': '300',
    'OFFICIAL_ACCOUNT_LOCAL_GENERATED_VISUALS_ENABLED': 'false',
    'OFFICIAL_ACCOUNT_LOCAL_VISUAL_PIPELINE_VERSION':
        'official-account-visual-pipeline-v1-native-strict',
    'IMAGE_QUALITY_AUDIT_MODEL': 'glm-5v-turbo',
}
services = [
    'backend-migrate', 'acquisition-api', 'acquisition-scheduler',
    'acquisition-worker', 'governance-scheduler', 'governance-worker',
    'content-scheduler', 'content-worker', 'wecom-dispatcher',
    'official-account-weekly-scheduler', 'official-account-weekly-dag-worker',
    'official-account-local-worker', 'wechat-official-account-draft-worker',
]
for mode in ['unchanged', 'global-generated', 'marker-added-in-memory']:
    fixed['OFFICIAL_ACCOUNT_LOCAL_GENERATED_VISUALS_ENABLED'] = (
        'false' if mode == 'unchanged' else 'true'
    )
    rendered = json.loads(subprocess.run(
        ['docker', 'compose', '--env-file', '/dev/null', '-f', 'compose.yaml',
         '--profile', '*', 'config', '--format', 'json'],
        env=fixed, check=True, capture_output=True, text=True,
    ).stdout)
    rows = []
    for name in services:
        fields = {
            key.lower(): str(value)
            for key, value in rendered['services'][name]['environment'].items()
            if value not in ('', None)
        }
        injected = 'official_account_local_visual_pipeline_version' in fields
        if mode == 'marker-added-in-memory':
            fields['official_account_local_visual_pipeline_version'] = fixed[
                'OFFICIAL_ACCOUNT_LOCAL_VISUAL_PIPELINE_VERSION'
            ]
        try:
            Settings(_env_file=None, **fields)
            state = 'PASS'
        except ValidationError as error:
            state = '; '.join(item['msg'] for item in error.errors(
                include_url=False, include_input=False, include_context=False,
            ))
        rows.append({'service': name, 'marker_in_rendered_compose': injected,
                     'result': state})
    print(json.dumps({'scenario': mode, 'rows': rows}))
PY
```

### 2. Minimal remediation: policy identity is not execution capability

`official_account_identity_from_settings` (`backend/app/infrastructure/official_account_runtime.py:15`) currently derives both V4 fields only when generated visuals are enabled (`:45`, `:54`). `Settings` simultaneously requires a generated-enabled instance to have image execution capability. Yet the weekly scheduler only freezes input; the DAG only enqueues, polls and exports. Neither should acquire Comfly capability.

Recommended bounded implementation: separate strict **new-run policy selection** from image **executor availability**, retain literal legacy behavior, and explicitly distribute the flags by service. Use a typed, role-specific composition/validation boundary, not a blanket removal of provider checks or an environment-only workaround. The same strict marker must yield the exact same frozen Article identity in policy-producing services without constructing model clients.

| Service / responsibility | Intended strict activation projection after repair | Credential / capability boundary |
| --- | --- | --- |
| `official-account-weekly-scheduler` | Strict marker; derive complete V4 identity even with generated executor flag false | No Comfly key/client; no new AI secret. Existing scheduler uses provider/model identity only |
| `official-account-weekly-dag-worker` | Same marker for frozen-input/legacy-retry policy; generated executor flag false | Preserve existing Zhipu key dependency; no new Comfly key/client and no WeChat credentials |
| `acquisition-api` | Same marker for prospective Article enqueue identity; no strict generation execution | Preserve existing unrelated image credentials/configuration; do not dispatch strict generation from API |
| `official-account-local-worker` | Strict marker plus generated=true; exact audit-model pin | Sole strict execution owner, using its existing Comfly and Zhipu secrets; retain one-POST transport checks |
| `wechat-official-account-draft-worker` | Marker absent, generated=false; load strict prepared v2 from stored artifact | No image/vision credentials; exact proof/byte validation is provider-free; retain only existing draft capability |
| Migration, acquisition workers/scheduler, governance workers/scheduler, content scheduler/worker, WeCom, unrelated optional fixtures/IP workers | Marker absent and official-account generated=false | Preserve every existing provider/credential/workflow value; do not globally propagate strict execution |

The exact assignment above is a **proposed next implementation**, not something the current validator accepts. In particular simply setting generated=false for the weekly scheduler today yields an invalid incomplete strict identity. The strict predicate and identity builder must change together, with negative executor tests retaining fail-closed provider/model/key validation. Avoid forcing V4 values into `OFFICIAL_ACCOUNT_LOCAL_GENERATED_VISUAL_PLAN_VERSION` or `_PROMPT_VERSION`: current config validates those legacy setting literals at `config.py:768`; the strict identity builder chooses V4 internally.

Exact feature configuration values to bind in a future release:

- `OFFICIAL_ACCOUNT_LOCAL_VISUAL_PIPELINE_VERSION=official-account-visual-pipeline-v1-native-strict` (new prospective policy; only identity owners).
- `OFFICIAL_ACCOUNT_LOCAL_GENERATED_VISUALS_ENABLED=true` (strict executor only after explicit Compose isolation).
- `IMAGE_QUALITY_AUDIT_MODEL=glm-5v-turbo` (explicit worker pin; current default is already correct, but Compose currently ignores a host override).
- Required existing executor values remain `AI_PROVIDER_MODE=zhipu`, `AI_PLATFORM_BASE_URL=https://open.bigmodel.cn/api/paas/v4`, `IMAGE_ENABLED=true`, `IMAGE_PROVIDER_MODE=comfly`, `IMAGE_MODEL=gpt-image-2`, and the existing protected `AI_PLATFORM_API_KEY`, `COMFLY_API_KEY`, `COMFLY_BASE_URL`.
- Keep `OFFICIAL_ACCOUNT_LOCAL_VISUAL_SEMANTIC_ENABLED=false`, `IMAGE_QUALITY_EVAL_MODE=off`, global `IMAGE_MAX_ATTEMPTS=3`, current scoring .11, existing embeddings, schedules, recipients, draft flags/inbox paths and V10 bundle values unchanged. Strict auditing does not require changing `IMAGE_QUALITY_AUDIT_ENABLED` or turning observe on.

Likely narrow affected source: `compose.yaml`; `backend/app/core/config.py`; `backend/app/infrastructure/official_account_runtime.py`; executor startup wiring in `backend/app/official_account_worker_main.py` if needed; scoped unit/Compose/doctor regressions. No database/schema/provider change is needed just to fix distribution. Main must update the reviewed strict spec because its current activation paragraph conflates policy and capability. Do not edit sealed weekly operators.

Required next checks: actual rendered all-profile Compose -> actual per-service Settings for both disabled and strict configurations; unchanged credential field sets; exact identity equality among API/scheduler/DAG and stored-run executor; scheduler/consumer construction with no Comfly key or transport; wrong/missing executor credentials/model/base still fail before work; old V1–V3 fingerprints; new/frozen retry behavior. Include optional non-production profiles for startup leakage even though they are never started in this release. A new implementation/check/commit cycle invalidates the current candidate image/source hash and requires a new artifact identity.

### 3. No existing activation mechanism covers this candidate

#### Ordinary developer-PC release exists but is not currently a viable strict activation path

`scripts/release-prod.sh:578` is not dated and remains an ordinary release entrypoint. Its dry-run branch at `:583` is local-only; the real branch performs remote preflight, authoritative fetch, clean worktree, full gates, image push and deploy (`:591`). It is not a generic read-only status command.

- Exact Codeup source authority and clean fetched source are required (`:278`); local commits or a GitHub-only push are insufficient. The branch/name and remote authority require main's explicit review, not an arbitrary feature ref.
- Full gate commands at `:386` have no known-baseline exception path. The current backend/frontend/release suite results are nonzero. Never synthesize green gate IDs or ignore exits to reach artifact creation.
- `deploy/release/deploy.py:34` owns nine application/migration services, eight long-running processes. It does not quiesce/restart the four currently enabled official-account processes. Current production has twelve application processes plus PostgreSQL/MinIO; partial source/image activation would leave mixed consumers.
- Generic preflight requires root-owned protected files (`deploy.py:402`, `:470`) and matching normal release manifests (`:409`). Main reports production's intentionally application-owned mode-0600 `.env`; changing ownership to satisfy this deployer is not authorized. Manifest compatibility remains to be verified by main, not assumed.
- Generic activation explicitly asserts primary `.env` unchanged (`deploy.py:749`); it does not own this feature's scoped primary-config mutation/rollback. Its previous-head/compatibility logic cannot treat schema0043 as automatically reversible (`:161`).

It may be possible to provision a separately reviewed normal release path later, but not to execute it unchanged now and claim it covers strict activation.

#### Dated task-local weekly operator is definitively unsuitable

`research/weekly-release/weekly_release.py:33` binds old base `5c560da`, old image, head0042 and the `release/weekly-source-preflight-20260907` ref. Its runtime allowlist at `:63` contains only two weekly Python files and Compose's one literal inbox correction; validation at `:248` rejects the strict diff. It explicitly performs no migration or protected-config change (see `research/weekly-release/usage.md`).

Its executable `window` at `weekly_release.py:194` requires September7, a writer boundary at or before **03:00Z / 11:00 CST**, and entry before the 15-minute margin, **02:45Z / 10:45 CST**. Main's fresh read-only observations after 05:21Z prove that window expired. Updating a CLI cutoff or timestamp cannot legitimately renew it. Older substantive-topic/hotfix incident authorization cannot be reused either.

A new task-local transaction may reuse independently reviewed pure validation/backup/source/OCI components, but needs explicit exact scope, new tests, immutable identity and independent release review. It must cover schema0043 and all twelve active application processes, scoped per-service configuration, current ownership/modes, fresh historical-state fences, failure recovery and rollback. This is new implementation/authority, not changing a date constant or running an available command.

### 4. Rollback incompatibility starts before any strict Article

Migration `backend/alembic/versions/20260907_0043_strict_visual_pipeline.py:12` extends actual0042. Its downgrade fence at `:148` checks strict audit rows, non-null generated output_size, and non-null Article policy. It does **not** inspect all new weekly inputs/governance state and cannot itself establish old-application compatibility.

The candidate scheduler unconditionally passes a complete Article identity to `PostgresWeeklyProductionInputPlanner` (`official_account_weekly_scheduler_main.py:91`). The planner emits input v2 whenever that identity is present, even when the visual marker is null (`infrastructure/db/official_account_weekly_production.py:146`). Thus **even a code-only rollout with strict generation off can create new v2 weekly inputs** at the next legitimate due week.

Order matters:

1. Scheduler persists the frozen checkpoint before enqueue (`official_account_weekly_scheduler_main.py:138`).
2. Service creates/ensures governance root before the DAG row (`application/services/official_account_weekly_dag.py:79`).
3. Article rows are created only when a later `build_article` node executes (`application/services/official_account_weekly_production.py:219`).

Old weekly code in clean `weekly-source-preflight/.../application/services/official_account_weekly_production.py:319` accepts only the literal v1 input; current code accepts v1/v2 and strictly decodes v2 at `:340`. Old decoder behavior is not rescued by merely turning strict flags off or keeping Alembic0043. Committed `deploy/release/migration-compatibility.json:5` correctly remains `previous_application_compatible=false` and names this early-input caveat.

Before old runtime restart, a reviewed rollback must prove **all incompatible newly produced state absent**, including new frozen checkpoint files, weekly roots/nodes/attempts/input fingerprints, governed roots/allocations/events, strict Article/render/media/generation/audit state and strict prepared artifacts/draft jobs. Check both database and content-addressed output volumes, not a count of strict Article rows alone. Preserve original old work and all legitimate writes; no SQL deletion/relabel, downgrade, wholesale DB restore or artifact removal is authorized to make the predicate true.

If new incompatible state exists or cannot be proven absent, retain compatible consumers and use a reviewed forward fix. Stopping selection of new strict identities is distinct from disabling the capability needed by already-frozen strict runs; do not strand pending accepted work through a blanket flag reset. If migration was attempted and success/compatibility is uncertain, keep affected writers stopped for explicit incident reconciliation rather than attempt automatic image rollback.

### 5. Three-role timing is not established by one accepted preview

Actual bounds/call paths:

- Weekly Compose runs three node workers (`compose.yaml:425`); `official_account_weekly_dag_main.py:250` gathers three claims concurrently.
- Local Article worker concurrency is independently one in main's live observation and default `config.py:278`; the actual worker creates exactly that many worker loops (`official_account_worker_main.py:234`). Hence the three concurrently waiting Article nodes queue behind one actual generator.
- Each Article generates five scenes sequentially (`application/services/official_account_strict_visual.py:119`) and audits six final normalized subjects sequentially (`:264`).
- Strict generation uses `min(configured window,360)` and timeout `min(configured timeout,300)` (`infrastructure/ai/official_account_visual_strict.py:118`); main observed actual window300. Each strict audit independently has total180/read120 and one attempt (`:171`), not general `AI_TOTAL_TIMEOUT_SECONDS=150`.
- Node Article wait is720 (allowed30..840) and starts immediately after enqueue, **including queue time** (`application/services/official_account_weekly_production.py:230`). Timed-out wait returns retryable capability_timeout; terminal/review/unknown Article returns terminal (`:236`). It does not cancel the separate Article worker.
- Capability/node limit is900 seconds and root elapsed budget3600 seconds (`infrastructure/official_account_weekly_dag_governance.py:60`). These are execution-governance budget limits, not evidence that providers meet an end-to-end SLA. Local lease300/heartbeat60 renew ownership; lease length is not a total runtime ceiling.

One historical preview had 242.121s generation +46.128s audits =**288.249s per Article**. Repeating that one observed visual-only duration three times is **864.747s /14.4min**, before text, storage, export and upload. If all three build nodes begin waiting together, the third can exceed its initial720s wait even at this sample speed. This is a queueing illustration, not a measured three-Article production run or p95 prediction. Frozen retry identity prevents paid duplication; it does not guarantee eventual weekly success within retries/root budget.

Conservative sum of configured per-call ceilings with the observed300s generation window is `5*300 + 6*180 = 2580s` (**43min per Article**). Policy ceiling360 would yield2880s /48min; three such Articles would be129–144min before other work, plainly outside the current overall envelope. These sums are bounds for that serial visual portion, not promised latencies or a guarantee all requests finish successfully at their ceiling.

Before activation, add a provider-free simulated full **three-role** timeline test including serial queueing, retry/backoff, root budget accounting and independent Article completion after a weekly timeout. Preserve failure visibility and identity reuse. If reliable three-role completion requires bounded wait/orchestration redesign or concurrency changes, that is a separately reviewed scope; do not arbitrarily raise900/3600 or worker concurrency and do not open the historical week to test it. A live prospective normal run remains the final acceptance, with one complete new week nominally permitting15 generations and18 audit calls, not a replay of the old sample.

### 6. Current gates and live observations must be attributed separately

The committed independent report `research/visual-production-check-20260907.md:14` grants `IMPLEMENTATION_CHECK_PASS` change-relative, explicitly not `SAFE_TO_DEPLOY`. It records:

- All81 strict tests pass, including16 PostgreSQL strict tests and a real PG/MinIO normal enqueue -> executor -> prepared consumer path with mock providers.
- Full backend2124passed/34failed/0setup errors/80% coverage:33 known baseline failures plus one separately base-reproduced test-environment credential interaction.
- Full integration134passed/2known baseline failures; changed52Python files Ruff/format clean;31runtime modules strict mypy clean. Full format/type retain separate baseline findings.
- Frontend243component tests pass; one known Playwright/Vitest collection failure. Release mocks67passed/1known inbox assertion failure.
- No exact candidate container build, immutable source/image parity, fresh backup, production activation or natural strict-run evidence was established by that review.

These results support reuse of the implemented durable core. They neither excuse the newly reproduced Compose issue nor permit ordinary release scripts to label their mandatory general gates green. Decide and record an explicit policy-compliant remediation or tightly scoped independently reviewed exception path before packaging; never fabricate gate receipts. Any runtime wiring fix requires updated checks on the new source.

Main, not this researcher, supplied fresh read-only live observations:

- At05:21:49Z, schema0042; three original Article runs ready/attempt1; original weekly terminal state retained; same draft job ready with three successful items/attempts; generated table empty and strict audit table absent. Job aggregate attempt_count3 is the sum of its three role attempts, not three repeated drafts.
- Fourteen queue tables had no running work/unexpired lease; seven historical queued copy jobs remained. This is a point-in-time observation, not authorization to mutate or assume later quietness.
- At05:23:20Z, current marker6154c78; fourteen running containers plus one historical exited MinIO initializer; all application containers on the same67a650... digest with restart0; protected mode0600 `.env` unchanged;48.29GB free. Latest backup receipt02:37:05Z is not a fresh post-quiesce backup for this release.
- Main's subsequent read-only remote-ref check found `release/visual-quality-preview-20260907` absent from both Codeup `origin` and `github-backup`; no push was performed. This researcher did not repeat that Git check.
- Actual noon delivery window ends13:30CST; evening preparation begins17:00CST, giving a prospective15-minute margin cutoff16:45. This potential calendar interval is **not a sealed release window**: all writers/claims/queues and current time must be revalidated, and a transaction must be reviewed before any operation. The expired10:45 operator is not renewed by an afternoon quiet interval.

The natural weekly schedule remains Monday09:00/24h catch-up (`domain/official_account_weekly_edition.py:403`). Current scheduler preserves any existing week run, including terminal, before planning (`official_account_weekly_scheduler_main.py:123`). September7's original terminal week will not be recreated; under unchanged scheduling the next prospective new week is September14, not a manual same-day replacement.

### 7. Minimal future activation and failure plan (not executable authorization)

1. Repair only the policy/executor/Compose distribution gap; add exact all-role offline configuration and three-role timing regressions; independently check and commit the new bounded source. Do not modify current production.
2. Main obtains explicit release-source/push and transaction implementation authority. Bind one reviewed authoritative Codeup ref/commit (GitHub publication alone is not the configured release authority), exact allowlist, schema0043 compatibility and all twelve running application entrypoints. Keep dirty main/unrelated .12/Reviewer/Qwen work excluded.
3. Build and seal from that immutable source only after applicable gates. Verify exact OCI graph, source projection, metadata, current Alembic head, non-root/default-off runtime, actual full-profile configuration and entrypoints without credentials/network. Do not use private sample assets or secrets as build input.
4. Prepare a new tested one-shot operator plus failure harness, fresh full source/config/history baseline, exact owned file metadata, preflight/locked/post-quiesce revalidation and a complete new backup. Bind unchanged PostgreSQL/MinIO and existing Article/draft/weekly/copy histories; choose a real current safe window with enough recovery margin.
5. Under explicit operation authority, quiesce the complete affected twelve-process set, migrate once to0043, atomically activate exact source/image/markers and only reviewed per-service config, restart/health/restart-count converge. No publish, replay or model smoke belongs in deployment verification. Preserve immutable artifact/accountability evidence.
6. Failure before migration may restore exact captured source/image/config only after business-state fences. After attempted migration, use compatibility-aware recovery as above; never blindly rerun a consumed operator. No database downgrade/restore or history deletion.
7. Report activation separately from future business success. Observe the next legitimate new weekly run through15native generation intents,18final-upload audit subjects, three exact prepared children and three unpublished drafts, with bounded failures and repeat-pass idempotency. Model acceptance is not human annotation or publication permission. Do not wait silently until next Monday or claim completion before evidence exists.

## Files found / code patterns

All unqualified product paths above refer to the committed candidate worktree, not dirty root.

| Path | Purpose |
| --- | --- |
| `backend/app/core/config.py` | Default-null marker, separate audit model, currently coupled policy/executor validation |
| `backend/app/infrastructure/official_account_runtime.py` | Shared frozen Article identity; current generated-flag dependency |
| `backend/app/domain/official_account_visual_pipeline.py` | Fixed native geometry, provider/model and final-upload audit policy |
| `backend/app/infrastructure/ai/official_account_visual_strict.py` | Lazy one-POST generation/audit, independent per-call budgets |
| `backend/app/application/services/official_account_strict_visual.py` | Sequential durable five-generation/six-audit orchestration |
| `backend/app/official_account_weekly_scheduler_main.py` | Future-only planner, checkpoint-before-enqueue and existing-week preservation |
| `backend/app/application/services/official_account_weekly_production.py` | Frozen/legacy identity dispatch and720s queue-inclusive wait |
| `backend/app/infrastructure/official_account_weekly_dag_governance.py` | 900s node and3600s root budgets; early governance state |
| `backend/app/application/services/official_account_strict_prepared.py` | Provider-free exact-media/proof validation |
| `backend/alembic/versions/20260907_0043_strict_visual_pipeline.py` | Additive migration and incomplete-for-application-rollback SQL downgrade fence |
| `compose.yaml` | Explicit service environment projection and existing credential isolation |
| `scripts/release-prod.sh` | Non-dated authoritative fetch/full gates/build/push/deploy route |
| `deploy/release/deploy.py` | Nine-service ordinary deployer; config/root-owned-file assumptions |
| `deploy/release/migration-compatibility.json` | Reviewed implementation compatibility, old-app incompatibility retained |
| `research/weekly-release/weekly_release.py`, `usage.md` | Expired old-base/source/head/config-immutable incident operator |
| `research/visual-production-check-20260907.md` | Previous change-relative implementation test evidence and explicit exceptions |

## External references / versions

No external browsing was necessary: the question concerns exact locally available committed code and configured mechanisms, not vendor feature claims. No external source is used to infer current model availability, pricing or publishing permission. Route/version literals are project contracts: Comfly/gpt-image-2, direct Zhipu/glm-5v-turbo, Pydantic2.13.4 (locked candidate), schema0043 from0042, weekly input v2 and strict prepared child v2. Historical live model evidence belongs solely to the accepted-preview report.

## Related specs

Read in full: `.trellis/workflow.md`, `.trellis/spec/backend/quality-guidelines.md` (including the complete immutable-release scenario), `.trellis/spec/backend/official-account-strict-visual-pipeline.md`, `.trellis/spec/backend/official-account-weekly-dag.md`, `.trellis/spec/backend/wechat-official-account-drafts.md`; backend index and task PRD/design/implement also reviewed. Historical weekly spec rollout/0040/empty-state language is not current release authority; the strict spec and real schema0043 compatibility qualify it.

## Caveats / Not Found

- No current strict release builder/operator with an unexpired reviewed scope was found. A non-dated generic command exists, but its executable gates/topology/configuration ownership do not fit this activation.
- No full production-shaped rendered-Compose/Settings regression was present in the prior strict acceptance evidence; this pass reproduced the gap locally. No code was repaired here.
- No measured prospective three-role strict latency distribution, live final63621-byte cover audit, or new automatic strict draft receipt exists in this research. Accepted preview calls cannot substitute for those outcomes.
- Exact source authority and fresh production inventories remain main-owned; researcher intentionally did not duplicate Git/SSH/credential checks. Fresh reported live facts must not be treated as an independently recaptured release baseline.
- The recommended role split requires a reviewed implementation and corresponding spec update. It is not permission to relax executor safety or change schedules/providers, nor permission to widen this preparation turn into deployment.
