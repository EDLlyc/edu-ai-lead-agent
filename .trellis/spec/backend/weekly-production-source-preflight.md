# Weekly Production Source Preflight

## 1. Scope / Trigger

Apply this contract to production material selection and the frozen material-to-article enqueue
boundary. The September 7 incident exposed a cross-layer mismatch: shallow package acceptance
allowed an HTTP source, while the article source contract required safe HTTPS. Repeating that
immutable input consumed all three attempts without ever enqueueing an article.

This supplements the [weekly DAG](./official-account-weekly-dag.md) and
[weekly edition](./official-account-weekly-edition.md) contracts. It changes no business identity,
selection version, schema, model, or publication policy.

## 2. Signatures

- `PostgresWeeklyProductionInputPlanner.plan(week_start=..., cutoff=...)` selects only materials
  accepted by the pure `material_package_source_snapshot(package, image)` projection.
- `ProductionWeeklyDagHandlers._build_article(claim)` delegates enqueueing to
  `OfficialAccountRepository.enqueue_material_package(material_package_id=..., identity=...)`.
- The deterministic enqueue-error projection is
  `WeeklyDagNodeFailure("invalid_selection", retryable=False)`.

## 3. Contracts

- Run the complete source projection before per-event newest-eligible-package selection and
  ranking. Do not let an invalid newer package hide a valid older package for the same event.
- Reuse the article source validator for URL, evidence, brand, source-image, and field bounds.
  Preflight is pure: no article rows, artifacts, provider calls, or network URL rewrites.
- An HTTP source is ineligible; do not substitute HTTPS without independently approved source
  handling. Evidence text and inherited review gates remain unchanged.
- An incompatible candidate is skipped; insufficient remaining roles still produce the existing
  no-selection result. Never relax role eligibility or duplicate events to fill the edition.
- Enqueue revalidates the frozen material. Preflight is not a substitute for this last gate.
- Log only the safe event `official_account_weekly_materials_skipped`, week, fixed
  `material_source_incompatible` reason, and skipped count; no raw validation exception or content.
- Recovery of an exhausted original DAG must retain its terminal history. A task-local recovery
  may reuse validated ready siblings and enqueue a qualified replacement once through the ordinary
  article repository. Prepared-artifact validation and the existing independent draft worker stay
  authoritative. Record recovery separately; never label the original failed DAG ready.
- Draft staging creates three independent unpublished drafts, not a public article or mass send.
- A first-ever inbox may be absent if its parent is an existing physical directory. Read-only
  planning must not create it; the existing aggregate owner creates it only during execution.
- Read-only sessions that return loaded ORM rows to the planner must detach them before rollback
  (`expunge_all()` then `rollback()`), or rollback expires the rows used after session exit.
- The recovery enqueue holds short `FOR SHARE` locks on only the sealed material and image,
  rechecks source/request hashes, and delegates to the normal enqueue transaction. These locks
  block source updates but remain compatible with the enqueue's foreign-key `KEY SHARE` locks.
  Release locks after bounded enqueue; never hold them while waiting for model generation.

## 4. Validation & Error Matrix

| Boundary / condition | Required outcome |
|---|---|
| Pure material projection rejects URL, evidence, brand, image, or field shape | Skip candidate before ranking; no model/article side effect |
| Valid earlier package follows invalid later package for the same event | Earlier eligible package remains selectable |
| No complete three-role selection after filtering | Existing no-selection behavior; no manufactured fallback |
| Enqueue raises `ConflictError`, `NotFoundError`, or Pydantic `ValidationError` | `invalid_selection`, terminal on the first attempt |
| Enqueue/database has an unexpected runtime or transient infrastructure failure | Preserve existing infrastructure/retry handling; do not classify as bad material |
| Original run is terminal or exhausted | Ordinary retry remains rejected; no reset of original rows or successful siblings |
| Recovery intent already exists or frozen identities drift | Fail closed before any new enqueue/aggregate operation |
| Recovery result is unknown or incomplete | Retain audit and known run identity; do not blindly replay |

## 5. Good / Base / Bad Cases

- Good: the top-ranked invalid application source is excluded and the next fully qualified
  application case fills that role; the other two roles remain unchanged if ranking selects them.
- Base: all three candidates satisfy the source contract, so the selection and source fingerprints
  remain identical to the previous valid behavior.
- Bad: force an HTTP evidence source into an article, retry the same deterministic input three
  times, or reset a failed week to conceal recovery. None is permitted.
- Bad: regeneration of two already-ready siblings to repair one branch wastes calls and changes
  accepted artifacts; recovery must preserve their run and artifact identities.

## 6. Tests Required

- Unit: safe HTTPS positive; HTTP, credentials/fragments, malformed evidence/brand data, missing
  image acceptance, and final source field bounds rejected using the real source projection.
- Selection: invalid top candidate replaced; invalid newest same-event package does not hide older
  valid material; too few roles remain no-selection; projection does not enqueue or call providers.
- Handler: conflict, missing material, and final Pydantic bounds become terminal invalid-selection;
  unrelated runtime failure preserves the existing retry path.
- Isolated PostgreSQL governed DAG: invalid frozen material ends on attempt one; repeated polling
  creates no additional attempt or article; successful sibling checkpoint behavior stays intact.
- Recovery operator: sealed read-only plan, exact original/sibling binding, state/tamper rejection,
  no-clobber audit, duplicate-execution rejection, and failures around enqueue/aggregate.
- Real PostgreSQL: loaded ORM rows remain readable after read-only rollback; `FOR SHARE` blocks
  material/image updates while permitting ordinary article insertion. A missing first inbox stays
  absent throughout planning, and a symlink or missing parent is rejected.
- Production acceptance requires observed article readiness and actual draft-worker success;
  passing offline tests alone is not evidence of staging or publication.

## 7. Wrong vs Correct

Wrong: check only package status and nonempty source JSON, rank it, then discover the source
cannot become an article after the weekly run is already frozen.

Correct: call the same pure source projection used by article enqueue before ranking, then repeat
the validation at enqueue. Preserve deterministic terminal failures and recover with a separately
audited, explicitly bounded operation that reuses successful work.
