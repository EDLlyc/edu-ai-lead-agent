# Design: narrow integration over the live legacy pipeline

## Boundaries and source ownership

Use the actual legacy image/source as the four-service base. The model integration contributes
three watcher entrypoints, model overlay, provider contract, secret box and a narrow legacy Settings
port. The template integration contributes single runtime, single delivery, shared draft service,
colour domain and a bound account-layout query independent of the new admin ORM. The combined
closure is twelve files; exact old/new hashes and deterministic config-port source are release
artifacts. Preserve every other legacy app file byte-for-byte. Do not replace the current six
admin/core containers, schedulers, prompts, scoring rules, generated-image policy or dependencies.

## Data flows

- New single draft: configured account fingerprint → bound DB layout query → immutable edition
  layout pin → existing body rendering/colour mapping → existing journaled upload.
- Existing edition: valid prior pin wins. If a pre-template physical-write intent exists without
  a pin, bind default before reconstruction. Validate pin version and ID and existing claim binding;
  preserve original artifacts and no-replay semantics for unknown results.
- Model consumers: unchanged environment Settings → latest console key overlay → immutable provider
  clients → fresh verified version/error heartbeat. On later version change, self-SIGTERM drains
  existing work; Docker starts a new process. Grant the existing MODEL_SECRET_KEY only to the
  three added consumers. No ADMIN_SECRET_KEY and no extra secret on the draft worker.

## User interface

The layout page displays saved selection, says only colour changes, scopes application to first
upload of a supported automatic single draft, and explains retry pinning. Remove the obsolete dated
legacy-warning only after the worker release. Retain a concise note that saved settings do not
prove live worker status and generated drafts should be inspected. No new runtime-status API/table.

## Deployment/configuration

Add an optional per-service ADMIN_PIPELINE_IMAGE pin for exactly four services, defaulting to the
ordinary APP_IMAGE for local development. Keep production APP_IMAGE untouched. Production patch
adds only that pin and MODEL_SECRET_KEY mapping to the three missing consumers; preserve all other
environment values, commands, mounts, flags and scheduling. Source Compose should express the six
known model-consumer mappings consistently, without sharing the model secret via the common env.

Build legacy-derived candidate offline with no network/dependency changes. Source gate runs on the
final commit; additional candidate tests exercise real legacy Settings/dependency imports and
all template/model regressions. Before cutover verify image/config hashes, current schema0061,
no running/leased/runnable target work and existing historical unknowns separately. Stop only the
four idle targets, recheck inventory, save DB/config and journal-volume backups and restore listing,
then recreate without build/pull. No schema migration, seed, enqueue, upload, model call or publish.

## Verification and recovery

Bind each new heartbeat to the current container hostname and process start; require two fresh
observations spanning a poll, clean load errors and agreement with latest stored versions. Empty
stored versions currently prove DB reads/env fallback, not a real production encrypted-key rotation.
Verify all twelve image files, every non-overlay legacy file, original mode/account binding and
preserved journal/state counts. Include long-operation SIGTERM and old ACK regression tests.

Rollback never downgrades DB or edits business journals. Restore old model-worker pins/config
where safe; a draft consumer that might encounter a new nondefault pin must remain on compatible
code or stopped for a forward repair. Stop/recheck and inspect durable state before choosing recovery;
never infer non-application from timeout. Preserve previous frontend and restore it with the matching
release. Frontend preview5180 is refreshed only after the backend checks pass; demo5181 remains isolated.
