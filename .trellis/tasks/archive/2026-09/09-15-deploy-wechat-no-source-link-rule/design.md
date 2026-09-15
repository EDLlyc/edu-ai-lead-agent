# Production deployment design

## Boundary

This is a code-only, no-migration release of the prospective source-presentation
policy. The application change is limited to these runtime files:

1. `app/domain/official_account_source_presentation.py`
2. `app/domain/official_account_editor_handoff_v2.py`
3. `app/application/services/official_account_strict_prepared.py`
4. `app/application/services/wechat_official_account_draft.py`
5. `app/infrastructure/wechat_official_account/prepared_artifacts.py`

Tests and Trellis specifications ship in Git but do not enter the runtime overlay.
The production database, MinIO data, Compose file, `.env`, provider credentials,
and scheduling configuration are immutable inputs to this release.

## Compatibility model

Source presentation is explicitly versioned:

- Missing version: preserve the legacy renderer and historical artifact identity.
- V1 (`wechat-source-presentation-v1-readable`): preserve deduplicated attribution,
  the historical native source URL, and its frozen read-more behavior.
- V2 (`wechat-source-presentation-v2-no-links`): show publisher names only and bind
  the native URL to `None`.

Only the current prepared-artifact owner changes its default from V1 to V2.
Validation reconstructs the selected version and binds version, body, and
URL-or-null into the content identity. The draft preparer rejects any override of
the frozen null value, and the HTTP client retains its established rule of omitting
`content_source_url` when the request value is `None`.

## Immutable image construction

Build locally from the exact current production image
`offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:baffc27e9dc4ccbd9fed5ab248e4e00784f80ecfb25f966fe8c63ee286601d8d`.
Load the already retained canonical OCI archive for revision `d2e709c`, verify its
archive and graph identities, and overlay only the five committed application
files. Preserve every base runtime configuration field and every untouched
application-file hash, including the live Zhipu integration and permanent banner
bytes. Label and export the candidate by the new commit revision and immutable
digest; validate a canonical reload before transfer.

The offline smoke runs with no network and proves:

- current owner selects V2;
- V2 HTML has source names but no URL/link/read-original text;
- V2 prepared manifest and draft request carry `None` and the outgoing add payload
  omits the source field;
- V1 and unversioned rendering remain unchanged;
- permanent header/footer and live Zhipu bytes match the base image.

## Activation data flow

```text
reviewed commit on Codeup release branch
  -> local exact-base OCI overlay and canonical validation
  -> checksum-bound transfer to production staging
  -> manifest validation without execution
  -> exclusive deployment lock and under-lock baseline fence
  -> protected marker/config backup
  -> quiesce 12 application writers
  -> recheck queues and exact baseline
  -> atomically switch image reference and both revision markers
  -> recreate only 12 application services, without dependencies/build/pull
  -> readiness, schema, runtime policy, queue, and preservation checks
  -> protected success receipt
```

PostgreSQL and MinIO containers are never recreated. No migration command or
social/model endpoint exists in the deployment operator.

## Rollback

Before quiescence, failure stops without changing production. After quiescence,
any failure triggers a best-effort ordered rollback:

1. stop application services;
2. atomically restore the exact `.release.env`, `.release-commit`, and
   `RELEASE_COMMIT` bytes with original ownership/mode;
3. recreate all 12 application services on the exact previous immutable image;
4. wait for health, schema, dependency identity, protected-config, and queue gates.

Because this release has no schema or data mutation, rollback requires neither a
database restore nor Alembic downgrade. A failed rollback is reported as a
terminal incomplete recovery, never as deployment success.

## Risks and controls

- **Incomplete standard release provenance:** retain the explicit scoped-offline
  label and protected receipt; do not claim pipeline bootstrap completion.
- **Mixed working tree:** commit only the ten reviewed rule/spec/test files plus
  this task's evidence; reject unrelated paths before build.
- **Base-image drift:** bind the full running digest, configuration, layers, and
  untouched file tree before overlay and again on production.
- **Queued work during restart:** require no live, retryable, ambiguous, or due
  M/W/F delivery before and after quiescence. Historical sealed rows remain
  retained and unmodified.
- **Accidental provider action:** use network-disabled smoke tests and a deployment
  operator with no model/social routes; do not start manual generation commands.
