# Admin settings reach the remaining production pipeline

## Goal and authorization

The user selected the first two remaining admin-console gaps and approved “好的，请你处理”
after the proposal to create their next Trellis task: apply the selected layout in real draft
generation and connect the remaining three model-key consumers. Complete the bounded integration
and its reviewed release while retaining current publishing/content behavior.

## Confirmed background

- Mainline/application release `0a68c7d` is deployed on six services as image `da052082`; DB is
  at migration 0061. Local mainline including release records is `815bfd0`.
- The draft-only consumer and three missing key consumers still run the legacy image `83a41e41`.
- Layout choice, colour renderer, account lookup and per-edition pinning already exist in source.
- Model-key storage, fallback, watchers and verified heartbeats already exist; only API, content
  and infographic services currently report. Legacy image lineage must be compared before upgrade.

## Requirements

- P1: New eligible automatic single-edition drafts use the bound account's selected template. Default/unbound/unknown
  selections keep previous output. Retrying an existing draft keeps its pinned template/body.
- P2: official-account-local-worker, official-account-weekly-dag-worker and governance-worker
  load the same console key versions as the existing consumers, report fresh verified diagnostics,
  retain environment fallback and finish their current work before a key-triggered restart.
- P3: Upgrade only the necessary production services and configuration. Preserve scheduling,
  job journals, prepared input contracts, existing output policies and all credentials. Compare
  the actual legacy image to source; unrelated behavior changes are not silently bundled.
- P4: The admin UI must accurately describe the deployed capability, including rollback or a
  disconnected worker. Do not remove a deployment warning before runtime evidence supports it.
- P5: Verification is provider-free until a separately selected real test article/key is approved.
  No actual publication, draft upload, key rotation, model probe or additional scheduled job is
  triggered by deployment checks. Existing scheduled production behavior continues normally.
- P6: Before deployment, obtain an exact file manifest, offline image checks, appropriate unit/
  integration gates, independent review, idle admission, backup and a recovery procedure. After
  deployment verify expected images, fresh consumer states, preserved work and no new errors.

## Acceptance

- A1/P1: Production-image offline fixtures prove selected/default templates and retry pinning;
  production configuration and loaded source demonstrate that new eligible drafts take that path.
- A2/P2: All six expected model consumers report fresh heartbeats with verified empty load errors;
  isolated tests cover valid/invalid encrypted configuration and safe restart semantics.
- A3/P3/P6: Target source/config hashes and before/after work inventories match the reviewed
  release. Existing six admin services and unrelated legacy services retain their identities
  unless a documented prerequisite is found and reviewed.
- A4/P4: The user-facing template/model state agrees with runtime evidence; no false “applied”.
- A5/P5: Verification receipts contain no secrets and document that no real article was published
  or uploaded and no production key was rotated for a smoke test.

## Out of scope

Public HTTPS, dashboard, poster styles, provider/model/URL changes, new layout variants, historical
draft rewriting, schedules, external publication and credential replacement.

## Technical constraints established by research

The four targeted services run identical legacy image `83a41e414fee1636c8d4897ae175ee5549afd9a7d4b37df0897b838c9b714851`.
Its shared configuration has unrelated changes on mainline, so port only the model-secret field
and Settings overlay getter onto the verified legacy file. Twelve overlay files cover both scopes;
no migrations or dependency installation are required (legacy PyCryptodome 3.23.0 verified).
The draft consumer runs single mode, and its configured account matches the bound database account.
Legacy weekly/manual paths stay unchanged. Existing pre-template journals require default-colour
pinning for safe ACK reconciliation; malformed template pins must fail closed before writes.
The template page will report saved choices and explain first-upload/retry behavior; it cannot
claim live worker readiness. Three model consumers receive the existing model secret, while the
draft worker receives no additional secret. Provider-free tests plus current-host live heartbeats
prove connection without rotating a real key. No user-owned scope decision remains unresolved.
