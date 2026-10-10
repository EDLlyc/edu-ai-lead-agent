# Research: Template integration into the existing production draft consumer

- Query: Identify the actual selection/render/pin paths, minimum legacy-image upgrade closure,
  compatibility risks, tests and truthful UI for operator-selected draft templates.
- Scope: internal; read-only source and extracted legacy-image comparison, provider-free in-memory
  reproduction. No SSH, live process, production mutation or provider request by this researcher.
- Date: 2026-10-10
- Worktree: `admin-pipeline-20261010`, task `10-10-admin-pipeline-integration`; source baseline
  supplied by coordinator: `815bfd0`, existing admin application `0a68c7d`.

## Findings

### Existing data and execution paths

1. The admin API already lists, previews and saves templates. Routes live at
   `backend/app/api/v1/routes/admin_wechat.py:478` / `:497` / `:504`. The service validates the
   known ID and writes an audit in the same transaction at
   `backend/app/application/services/wechat_layout_templates.py:51`. `list_account_layouts`
   returns enabled accounts (`:39`); the runtime fingerprint lookup currently does not filter
   enabled state (`backend/app/infrastructure/db/wechat_layout_templates.py:11`). Preserve
   that existing semantics in a narrow upgrade unless requirements explicitly change it.
2. `wechat_accounts.layout_template_id` exists from migration `20261009_0057` with default
   `xiaosai-blue`; production was reported at `0061`, so no template migration is needed.
   Migration file `backend/alembic/versions/20261009_0057_wechat_layout_template.py:14`;
   current ORM model `backend/app/infrastructure/db/models.py:7084`.
3. `backend/app/wechat_official_account_draft_main.py:78` routes single mode to
   `run_single_runtime(..., plane="consumer")` before the legacy constructor and rejects
   legacy enqueue/reconcile. Consumer validates its configured AppID fingerprint (`runtime:169`),
   imports durable history, claims one eligible edition and reserves the article (`:181–200`),
   validates the prepared child (`:205`), then looks up its account's selected template (`:233`).
   `backend/app/infrastructure/official_account_single_runtime.py` is the runtime file.
4. `backend/app/application/services/wechat_single_edition_delivery.py:202` creates the immutable
   per-edition `single-<edition UUID>-layout.json` pin. Subsequent deliveries use its template
   despite account-setting edits. Delivery constructs the journaled client (`:240`) and passes
   the pinned template to the shared draft service (`:248`). This pin happens at the first
   delivery attempt, not at article generation/admission. UI should say “new single drafts” or
   “first upload attempt”, not claim the selected template was part of an already generated body.
5. `backend/app/application/services/wechat_official_account_draft.py:247` applies colours to
   the submission body after hiding the preexisting generated-context notice, before strict
   headroom validation and before the first upload. It leaves prepared artifact bytes, title,
   author, digest, images and source policy unchanged (`:282–305`).
6. `backend/app/domain/official_account_layout_templates.py:115` maps missing/unknown IDs to
   default; default returns the identical string object (`:125`). Nondefault schemes replace
   fixed six-character hex colours. Header/footer are raster images and remain unchanged.
7. Legacy weekly executor at
   `backend/app/application/services/wechat_official_account_draft_jobs.py:337` constructs the
   service without a template. Its prepared and finalized V2 inputs continue to use default.
   `create_weekly_drafts` accepts an explicitly supplied service template, but no production
   weekly entrypoint fetches the account choice. Do not silently add weekly pin semantics in
   this task; production single mode exclusively bypasses this executor. Direct/offline callers
   also retain default unless they explicitly opt in.

### Exact minimum template overlay against the legacy image

The coordinator extracted image `83a41e41` to `/tmp/edu-admin-pipeline-integration/legacy-source`.
I compared the following source files with that extraction; full sanitized patch is
`research/template-legacy-diff.patch`.

| Candidate file | Legacy comparison / purpose |
|---|---|
| `backend/app/infrastructure/official_account_single_runtime.py` | Only two template additions: helper import and template kwarg lookup. Shared with the producer, so coordinate any producer watcher changes. |
| `backend/app/application/services/wechat_single_edition_delivery.py` | Only template import, pin helper, kwarg and service construction change; needs legacy-pin compatibility fix below. |
| `backend/app/application/services/wechat_official_account_draft.py` | Only template import, optional kwarg and colour pass change. All preexisting prepared/banner/source behavior is byte-identical. |
| `backend/app/domain/official_account_layout_templates.py` | New pure-stdlib domain file. |
| `backend/app/infrastructure/db/wechat_layout_templates.py` | New lookup helper; change dependency strategy before overlaying (below). |

The original draft entrypoint, journal, DB single-edition repository, prepared artifacts, renderer,
strict layout and provider client need no new template logic. Existing dependency versions suffice.
No `MODEL_SECRET_KEY`, `ADMIN_SECRET_KEY` or model-key watcher belongs in this draft-only consumer.
Preserve configured WeChat credentials, production acknowledgement, mode, mounts, schedules and
single-mode flags. Existing source defaults must not overwrite live configuration.

**Important closure issue:** legacy `app/infrastructure/db/models.py` is 6,929 lines and has no
`WeChatAccountModel`. Current models is 7,289 lines, including unrelated source, content-slot and
article ORM changes plus all admin classes. Copying the current helper unchanged would require
this broad model overlay. Instead, use a bound SQLAlchemy read (`text` or Core lightweight table)
for exactly `layout_template_id` where `account_fingerprint=:account_fingerprint`. Keep its
`async_sessionmaker` contract and no-row `None` result. This avoids broad ORM drift and requires
neither encryption nor new runtime packages. Verify helper import against the actual old models.

### Confirmed blocker: old journals do not contain layout pins

`_pinned_layout` currently treats every missing pin as a new draft. Old production delivery code
never wrote pins. If an old default-colour draft has a durable add ACK but SQL save failed, and
the account is now set to a nondefault colour, the upgraded retry reconstructs a different add
request and refuses the previously successful ACK (`single_write_binding_changed` at
`wechat_single_edition_delivery.py:108`, projected as `single_journal_invalid` at `:285`).

Provider-free reproduction is saved in `research/template-legacy-pin-repro.py` and the captured
result in `research/template-legacy-pin-repro.json`. It uses the existing journaled client plus
default draft service to recreate the old code path, then calls current `deliver_single` with
`jade-green` the following day. Result: expected `delivered`; actual `outcome_unknown`, error
`single_journal_invalid`; zero retry writes and zero provider calls. This is a lost reconciliation,
not a duplicate publication, but it violates preserved retry behavior.

Recommended bounded fix:

- Existing valid layout pin wins, regardless of current account selection.
- When no pin exists but a pre-template attempt has already begun, freeze **default**.
  The first possible durable physical-write intent is `single-<id>-inline-0-1-intent.json`
  (with body media) or `single-<id>-thumb-1-intent.json` (without media); these bounded reads avoid
  journal directory scanning/protocol expansion. A more conservative option is inspecting an
  existing matching single-edition claim before constructing `JournaledSingleDraftClient`; do
  not check it only afterwards, since the new constructor just created that claim.
- New eligible editions without a prior attempt pin the current normalized selection.
- Keep current claim validation before accepting another edition's journal and keep fsynced,
  create-only writes under the account lock. Never rewrite or delete an old receipt/pin.
- Validate pin version and known template ID when consuming a pin. Current code checks only
  `str` and silently defaults an unknown ID. A malformed/future-incompatible pin should fail
  closed before provider calls, not silently reconstruct a different body. Current valid version
  is `official-account-layout-template-v1`.
- On rollback to a pre-template worker, a nondefault pinned in-flight journal cannot safely
  reconstruct its body. Release recovery must retain compatible draft code or leave draft
  consumer stopped until forward repair if such history exists. Idle admission and full journal
  inventory reduce risk but do not replace this recovery boundary.

`LocalManualDraftJournal` at `backend/app/infrastructure/wechat_official_account/manual_journal.py:38`
holds a nonblocking account lock; all files are private immutable envelopes. Its `read` validates
content hash and filesystem safety (`:150`), `write` is `O_EXCL` plus fsync (`:186`). The protocol
at `backend/app/application/ports/wechat_official_account_manual_draft.py:10` exposes only read/write.

### Truthful UI without expanding runtime architecture

Current UI simultaneously promises next-draft application in its save success (`LayoutTemplatesPage.tsx:110`)
and displays a hardcoded “9 月 28 日 / 现在还不会生效” warning (`:147–151`). The selected row says
“正在使用” (`:160`), although the endpoint proves only persisted configuration. Its API response has
templates and account selections, **no draft-worker liveness/capability evidence**
(`backend/app/schemas/admin_wechat.py:200`, frontend adapter `layout/api.ts:13`).

For this bounded release, prefer honest non-live wording over a new heartbeat subsystem:

- Selected label: `已保存的模板` / `当前选择`; unchanged button: `已保存这个模板`.
- Save success: `「账号」的模板已保存为「青绿」` with no “已生效” / “服务在线” claim.
- Explain scope: `支持模板的自动单篇草稿流程会在新草稿首次上传时读取这里的选择；重试沿用首次选择，已有草稿不变。只更换配色，文字、版式和图片不变。`
- Keep a short generic notice, for example: `本页显示已保存的配置，未检测草稿服务的实时运行状态；生成后请在草稿箱核对效果。`
- Remove the obsolete dated warning only when the matching upgraded draft service has passed
  deployment source/runtime checks; serve the new frontend after that gate. Keep or restore the
  generic notice on rollback. Conditional wording remains accurate if the worker disconnects or
  an older worker returns; it does not assert “applied”.
- Do not add a model consumer entry or secret solely to fabricate draft capability reporting.

If the product later needs a live “已接入/未上报” badge, add a purpose-specific account-bound
capability report with version and freshness, and expose that truth through the template API.
Existing model-key consumers only prove model-key loading and cannot attest draft template use.
This is unnecessary for the current saved-setting contract. No unresolved user-owned choice is
needed for the conservative wording; the coordinator can make this routine implementation choice.

### Meaningful verification plan

Existing tests and extension points:

| Test file | Existing coverage / necessary additions |
|---|---|
| `backend/tests/unit/test_official_account_layout_templates.py:54` | Renderer colour set, default/unknown identity, scheme preservation, contrast. `:100` selected delivery, `:121` pinned retry, `:158` default output. Add pre-template full ACK reconciliation after expiry, partial known-rejected retry retaining default, unknown write no replay, malformed pin no calls. |
| `backend/tests/unit/test_official_account_single_edition.py:182` | ACK reconciliation after SQL failure/midnight; known rejection skips acknowledged media; ambiguity/expiry behavior. Preserve all. |
| `backend/tests/unit/test_single_edition_runtime_review.py:29` | Runtime prepared-artifact failures and cleanup; `:90` single routing bypasses legacy constructors. Add a fake successful consumer turn that asserts exact configured fingerprint lookup and forwarding; no provider calls. |
| `backend/tests/integration/test_admin_wechat.py:600` | Editor selection + preview + guard + audit + actual DB lookup, unbound account returns None. Re-run against bounded SQL helper and extend account isolation if needed. |
| `backend/tests/unit/test_wechat_official_account_draft.py:195` | Weekly all-three preparation and independent drafts. Preserve default behavior and original tree bytes. |
| `backend/tests/unit/test_official_account_strict_prepared.py:710` | Real prepared owner to MockTransport payload using audited image bytes. Preserve native framing/no-link contracts with selected colour, preferably reuse an existing fixture. |
| `backend/tests/unit/test_wechat_official_account_draft_worker.py` and contract draft CLI/client tests | Legacy fencing/side effects, activation gating, exact HTTP contract and no publication. |
| `frontend/src/features/admin/layout/LayoutTemplatesPage.test.tsx:48` | Preview/selection/save/error/expiry/accessibility; currently explicitly asserts hardcoded warning and optimistic save text. Change expectations to saved configuration and generic status notice. |

Run candidate-image offline smoke with network disabled against the exact five-file closure plus
coordinator-owned model additions. Import real old-image entrypoints, verify selected/default
submitted body, legacy journal reconciliation and template version. Do not start actual worker
loops, create test editions, call a model, rotate keys, upload a draft or publish for smoke tests.
Production checks are read-only configuration/source hashes, idle inventory, preserved journal
hashes, container identity and error/health observations. Capture exact source/image/file manifest.

## Related specs

- `.trellis/spec/backend/admin-console.md`, template settings/version identity and account lookup.
- `.trellis/spec/backend/official-account-single-edition.md`, exclusive routing, history/ACK,
  scheduled defaults and conservative recovery.
- `.trellis/spec/backend/wechat-official-account-drafts.md`, draft-only provider boundary,
  immutable prepared artifacts, native banner/source compatibility and no replay of unknown writes.
- `.trellis/spec/frontend/admin-console.md`, truthful environment/state, focused injected APIs,
  layout/browser checks and compatible deployment bundles.
- `.trellis/spec/guides/production-mainline.md`, exact reviewed release and live/legacy boundary.

## External references and versions

No external research was necessary: this is an internal wiring/compatibility investigation, with
all claims from repository source or extracted production source. Backend targets Python 3.11
(`backend/pyproject.toml:9`) and already includes SQLAlchemy 2 plus `psycopg[binary]==3.3.4`
(`:25`). Template version and migration IDs above are repository-local contracts, not provider API
claims. No provider documentation change or new package is required.

## Caveats / Not Found

- I did not independently query production or inspect its private journal bodies. The coordinator
  owns active-work admission, exact account selection/config, journal inventory and rollout.
- Source lines refer to the supplied baseline and may move during implementation.
- Current global hex substitution also matches identical strings in text/attribute values, not
  just CSS. Existing renderer templates/tests assume colour tokens; this is a latent edge case,
  not a reason to ship an unreviewed HTML-parser rewrite in a narrow legacy upgrade. Add a targeted
  text-preservation fixture if ordinary content can include literal registered colour strings.
- No existing endpoint proves live draft template capability. Generic saved-state UI is truthful;
  deleting the warning and retaining unconditional “正在使用/已生效” would not be.
