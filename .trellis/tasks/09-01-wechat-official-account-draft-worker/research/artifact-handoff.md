# Research: Weekly DAG / V2 artifact handoff to an independent draft worker

- Query: How should a downstream WeChat draft worker discover a ready weekly three-article run, resolve its finalized V2 children without persisting private paths, preserve role identity, and build durable idempotency?
- Scope: internal
- Date: 2026-09-01

## Findings

### Files found

- `.trellis/spec/backend/official-account-weekly-dag.md` — authoritative durable weekly-DAG, opaque-artifact, ready-state, and no-private-path contract.
- `.trellis/spec/backend/official-account-weekly-edition.md` — authoritative three-role aggregate and finalized-child identity contract.
- `.trellis/spec/backend/official-account-editor-handoff-v2.md` — authoritative V2 release, mobile-validation, content/artifact fingerprint, and local-only contract.
- `.trellis/spec/backend/wechat-official-account-drafts.md` — current draft-only adapter contract, including all-three preflight and three independent drafts.
- `backend/app/domain/official_account_weekly_dag.py` — code-owned graph, artifact descriptor, status projection, and ready derivation.
- `backend/app/application/services/official_account_weekly_dag_fixture.py` — current local artifact owner and exact aggregate/child directory layout.
- `backend/app/application/services/official_account_weekly_edition.py` — strict finalized-child loader and aggregate builder/writer.
- `backend/app/application/services/wechat_official_account_draft.py` — current local V2-to-WeChat preparation and provider-write orchestration.
- `backend/app/infrastructure/db/official_account_weekly_dag.py` — durable run status and aggregate artifact metadata binding.
- `backend/app/infrastructure/db/models.py` — indexed weekly-run ready state and metadata-only checkpoint columns.
- `backend/app/official_account_weekly_dag_main.py` — configured local artifact root remains process configuration, not database state.
- `compose.yaml` — weekly DAG owns a persistent `/app/output` volume that a downstream worker can share read-only.

### Existing artifact identity and readiness

1. The weekly business unit is exactly three independent roles in canonical order: `official_anchor`, `industry_trend`, `application_case` (`official_account-weekly-edition.md:5-10`; `backend/app/domain/official_account_weekly_edition.py:78-89`). The code-owned DAG builds four nodes per role and gates `aggregate` on all three `validate_child` nodes (`backend/app/domain/official_account_weekly_dag.py:129-168`).
2. A weekly run is `ready` only when the `finalize` node is `succeeded` (`backend/app/domain/official_account_weekly_dag.py:455-462`). PostgreSQL stores and indexes the run status by `(status, week_start)` and carries only aggregate ref/fingerprint/media type/byte size (`backend/app/infrastructure/db/models.py:5924-5979`). This is sufficient for bounded downstream discovery without reading node bodies.
3. `WeeklyDagArtifact` is intentionally only `opaque_ref`, lowercase SHA-256 fingerprint, media type, and byte size (`backend/app/domain/official_account_weekly_dag.py:298-311`). The fixture owner creates refs as `weekly.<run hex>.<node ordinal>` (`backend/app/application/services/official_account_weekly_dag_fixture.py:318-319`); this is a safe identifier, not a path.
4. The aggregate node writes a content-addressed directory named `weekly/official-account-weekly-edition-<batch fingerprint first 16>` under its configured artifact root and persists the batch fingerprint and outer ZIP byte size in the artifact descriptor (`backend/app/application/services/official_account_weekly_dag_fixture.py:206-253`). Finalize forwards the aggregate descriptor unchanged as the run aggregate (`backend/app/application/services/official_account_weekly_dag_fixture.py:255-270`; `backend/app/infrastructure/db/official_account_weekly_dag.py:350-395`).
5. The aggregate contains each complete finalized child beneath the code-owned paths `articles/01-official_anchor`, `articles/02-industry_trend`, and `articles/03-application_case`. The builder copies every child file, including its manifest and child ZIP, byte-for-byte into that prefix (`backend/app/application/services/official_account_weekly_edition.py:415-440`). Therefore those three subdirectories are already valid inputs to `WeChatDraftLocalSource`; no extraction or duplicate copy is needed.
6. The strict child loader validates a real non-symlink directory, finalized/local-only/unpublished truth, `quality_auto` release, exact 320/430 mobile report, file hashes/sizes, body identity, required files, child ZIP, and undeclared-file absence (`backend/app/application/services/official_account_weekly_edition.py:103-232`). The current WeChat preparation service reuses that loader before parsing article fields and media (`backend/app/application/services/wechat_official_account_draft.py:141-209`).
7. A read-only local check against the current reviewed weekly aggregate successfully prepared all three canonical child directories with distinct Article/content fingerprints and five body images each. The fake client raised on every provider method, proving the compatibility without any WeChat write.

### Recommended safe handoff boundary

Add a provider-neutral source resolver port rather than teaching the MCP/worker or database how a filesystem path is laid out:

```python
class WeeklyDraftArtifactOwner(Protocol):
    def resolve_ready_source(
        self,
        source: WeeklyDraftSourceRef,
    ) -> WeeklyDraftSourceSet: ...
```

`WeeklyDraftSourceRef` should carry only safe durable identity already owned by the weekly run: weekly run UUID/task ref/week, aggregate opaque ref, aggregate fingerprint, media type, and byte size. `WeeklyDraftSourceSet` should return exactly three runtime-only `WeChatDraftLocalSource` values plus their validated Article/content/artifact fingerprints. It must never be serialized, logged, or stored with its resolved directories.

The local implementation should receive its trusted artifact root from process configuration. It may derive the current local target as:

```text
<configured root>/weekly/official-account-weekly-edition-<aggregate fingerprint[:16]>
```

This path stays inside the artifact-owner object and process memory. The database stores neither the configured root nor the derived target. In Compose, mount the same `official_account_weekly_dag_output` volume into the draft worker read-only; the weekly worker already owns it at `/app/output` (`compose.yaml:390-414`). A future MinIO owner can implement the same port without changing job/schema/application code.

The resolver should fail closed unless all of the following are true:

- the source run is `ready`, completed, on current frozen versions, and has a complete aggregate descriptor;
- the aggregate media type is `application/zip`, the opaque ref is the exact code-owned aggregate ref for that run, and the stored fingerprint is lowercase SHA-256;
- the derived directory is a real, non-symlink descendant of the configured root;
- `manifest.json`, `weekly-index.json`, the outer ZIP, and the stored descriptor agree on batch fingerprint, byte size, versions, `article_count=3`, `local_only=true`, `published=false`, and canonical role order;
- the aggregate batch fingerprint is recomputed from its version/schedule/selection/binding/child identities, rather than merely trusting the value repeated in JSON;
- the outer ZIP has the deterministic expected root/file set and byte-for-byte contents;
- each code-derived role subdirectory passes `load_finalized_v2_child`, and the resulting run/Article/content/artifact/child-ZIP identities equal the corresponding aggregate row.

There is no public strict aggregate loader today; `_verify_existing_weekly` is fixture-private and compares against an already rebuilt in-memory artifact (`backend/app/application/services/official_account_weekly_dag_fixture.py:344-360`). The clean implementation point is a public `load_finalized_weekly_edition(...)`/resolver validation function beside `load_finalized_v2_child`, reused by both the downstream owner and tests.

### Ready discovery without coupling provider writes to the weekly DAG

Keep the weekly DAG unchanged and free of WeChat imports, as required by its spec. The draft worker repository can perform a bounded reconciliation scan:

```text
weekly run status = ready
+ complete aggregate descriptor
+ current supported versions
+ no existing draft batch for weekly_run_id/account_ref
-> resolve and preflight through WeeklyDraftArtifactOwner
-> transactionally insert one batch and three canonical child jobs
```

The scan is safe because `ready` is an indexed durable state and discovery performs no provider call. Use a restrictive foreign key from the new batch row to the weekly run and a unique source/request fingerprint so concurrent scanners converge on one batch. Do not add a WeChat call to `OfficialAccountWeeklyDagService._complete_if_terminal`; it currently has the correct boundary of only closing governance after terminal state (`backend/app/application/services/official_account_weekly_dag.py:216-218`).

Suggested parent identity:

```text
fingerprint(
  draft-worker-policy-version,
  account_ref="default",
  weekly_run_id,
  weekly_request_fingerprint,
  aggregate_opaque_ref,
  aggregate_fingerprint,
)
```

Suggested child identity additionally binds canonical role, Article fingerprint, content fingerprint, artifact fingerprint, and child ZIP SHA-256. Use database uniqueness for `(batch_id, role)` and the child request fingerprint. A second uniqueness guard on `(account_ref, article_fingerprint)` prevents a regenerated weekly aggregate from automatically drafting the same article again; an intentional replacement should require an explicit operator action/version rather than weakening automatic idempotency. Persist `account_ref="default"`, not raw AppID or a credential.

### Three independent draft outcomes

The current `create_weekly_drafts` correctly preflights all three sources before its first provider write and rejects duplicate Article/content identities (`backend/app/application/services/wechat_official_account_draft.py:114-139`). It then performs three writes sequentially in one method. If article 2 raises, the already returned article-1 receipt exists only in the local list and is lost to the caller. A durable worker therefore should not treat the entire method call as one atomic job.

Use one parent batch plus exactly three role child rows. Before the first provider write for any unresolved child, resolve and preflight the complete three-source set. Then execute only the claimed role and persist that role's success immediately before claiming another role. A succeeded role is immutable and never replayed; sibling failure does not erase it. Parent `ready` means all three children succeeded, while `partial` truthfully represents a mixed batch.

Since WeChat draft creation has no application idempotency key, exact-once behavior cannot be guaranteed across a crash after provider acceptance but before the database commit. Mark a child/attempt as provider-started durably before the first upload. An expired lease or process crash after that point must become `outcome_unknown` and must not be auto-reclaimed. This is stricter than ordinary retry, but it prevents duplicate drafts. Known rate-limit/transient failures may use bounded backoff; the adapter's existing write timeout already exposes `wechat_mp_outcome_unknown` and forbids replay (`wechat-official-account-drafts.md:97-101`).

### Important product-data caveat

The current `official-account-weekly-dag-worker` is a durable **fixture demonstration**, not the real weekly live-news producer. Its handler always calls `build_fixture_selection()` and `build_fixture_children()` (`backend/app/application/services/official_account_weekly_dag_fixture.py:105-146,206-237`), and the CLI always constructs `LocalWeeklyDagFixtureHandlers` (`backend/app/official_account_weekly_dag_main.py:74-89`). A run becoming `ready` today therefore proves durable orchestration and artifact integrity, but does not prove that the batch contains the latest business/news content.

Do not silently enable automatic real WeChat drafting for every current DAG `ready` row. One of these must be explicit in the task design:

1. implement/register a production weekly artifact handler whose aggregate is the actual finalized live V2 output; or
2. keep this worker development-only and default-disabled, and limit the initial end-to-end path to fixture/mock provider validation; or
3. require an authenticated live-acquisition provenance gate in the aggregate before real provider writes, rejecting `fixture_truth=aggregate_consumed_frozen_finalized_children_only`.

Without this gate, the automation can be technically correct yet draft fixture articles to the real account.

## Code patterns

- Metadata-only, private-path-free artifact descriptor: `backend/app/domain/official_account_weekly_dag.py:298-311`.
- Code-owned three-role/aggregate graph: `backend/app/domain/official_account_weekly_dag.py:129-168`.
- Durable `ready` truth: `backend/app/domain/official_account_weekly_dag.py:455-462`.
- Indexed ready-run/aggregate columns: `backend/app/infrastructure/db/models.py:5924-5979`.
- Artifact-root stays CLI configuration: `backend/app/official_account_weekly_dag_main.py:36-43`.
- Aggregate local owner layout: `backend/app/application/services/official_account_weekly_dag_fixture.py:206-253`.
- Strict child validation: `backend/app/application/services/official_account_weekly_edition.py:103-232`.
- Aggregate embeds complete role children: `backend/app/application/services/official_account_weekly_edition.py:415-440`.
- All-three preparation before provider writes: `backend/app/application/services/wechat_official_account_draft.py:114-139`.

## External references

None required. This topic is governed by the repository's existing internal artifact, weekly edition, and WeChat adapter contracts.

## Related specs

- `.trellis/spec/backend/official-account-weekly-dag.md`
- `.trellis/spec/backend/official-account-weekly-edition.md`
- `.trellis/spec/backend/official-account-editor-handoff-v2.md`
- `.trellis/spec/backend/wechat-official-account-drafts.md`
- `.trellis/spec/backend/execution-governance.md`
- `.trellis/spec/backend/wecom-delivery.md` (analogous durable job/attempt, unknown-outcome, and no-temporary-media persistence pattern)

## Caveats / Not Found

- No generic artifact-owner resolver exists; current opaque refs are stored and validated as metadata, while the fixture owner privately knows the filesystem layout.
- No public strict weekly-aggregate loader exists; child validation is strong, but downstream code also needs aggregate fingerprint/archive verification.
- No query currently lists unconsumed ready weekly runs; `completed_week_starts()` only returns week dates and is insufficient for downstream artifact resolution.
- The current one-call weekly draft method cannot durably preserve article-1 success if article 2 fails.
- The current durable weekly DAG produces fixture artifacts. Treating every current `ready` row as real business content is unsafe until provenance/handler ownership is made explicit.
