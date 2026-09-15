# Deploy WeChat no-source-link rule to production

## Goal

Deploy the reviewed, versioned no-source-link rule to the production WeChat
Official Account draft pipeline so every newly prepared current V5 article keeps
readable publisher attribution while exposing neither a reader-facing source URL
nor WeChat's native `阅读原文` target.

The business value is predictable draft output that follows the user's current
editorial rule without erasing internal source evidence or changing historical
artifact reconstruction.

## Background

- Production currently runs application revision
  `d2e709c0b6a5e47d1b91d2ec623de734aa3c0eb2` on immutable image digest
  `sha256:baffc27e9dc4ccbd9fed5ab248e4e00784f80ecfb25f966fe8c63ee286601d8d`.
- The production baseline has 12 healthy application services, two healthy
  dependencies, schema `20260914_0047`, about 38 GiB free, and an active backup
  timer. Standard `release-manifest` and `current-release-state` metadata remain
  absent, so this remains an explicitly scoped offline release.
- The release worktree contains the reviewed rule implementation in five product
  files, two focused test files, and three backend spec files. Focused testing has
  passed 135 cases plus changed-file Ruff and mypy checks. The full backend gate
  retains unrelated pre-existing format/mypy failures outside this change.
- One existing demonstration draft was already corrected separately through an
  acknowledged target-only update. That operation is not a migration mechanism
  and is outside this deployment.

## Requirements

1. Current native V5 prepared artifacts must opt into
   `wechat-source-presentation-v2-no-links`.
2. V2 body HTML must retain deduplicated publisher names and contain no `<a>`,
   `href`, literal source URL, `查看原文`, or `阅读原文` prompt.
3. V2 manifests must bind `content_source_url=null`; the preparer must reject a
   caller-supplied URL override, and `draft/add` must omit the field.
4. Historical unversioned and V1 artifacts must reconstruct byte-for-byte under
   their existing link behavior. No stored artifact or existing draft is migrated.
5. Deployment must use a locally built immutable overlay on the exact production
   image, preserving M/W/F single-edition behavior, live Zhipu integration,
   permanent banners, Compose configuration, secrets, database, and object data.
6. Deployment must make no model call, image-generation call, draft creation or
   update, publication, mass-send, deletion, or provider configuration change.
7. The release must be committed and pushed only to the existing Codeup release
   branch. The disabled GitHub backup push remains untouched.
8. Activation must be fenced by the production deployment lock, exact baseline
   identities, queue-idle checks, protected configuration backups, and automatic
   rollback to the exact prior image and markers on failure after quiescence.
9. Deployment evidence must contain only safe hashes, counts, status, and version
   identifiers; it must not expose credentials, tokens, provider bodies, raw media
   IDs, private URLs, article HTML, or private storage paths.

## Out of Scope

- Editing, deleting, or republishing historical drafts.
- Creating a new draft or triggering the scheduled M/W/F edition early.
- Adding publication, mass-send, homepage-pin, or browser-login automation.
- Database migrations, environment/configuration changes, frontend changes, model
  changes, media uploads, or standard release-pipeline bootstrapping.
- Repairing unrelated repository baseline failures.

## Acceptance Criteria

- [ ] The exact change passes focused source-presentation, framing, strict
  preparation, draft worker/client, legacy compatibility, Ruff, formatting, mypy,
  static no-social-call, and archive/OCI validation gates.
- [ ] The resulting commit is present on
  `origin/release/wechat-two-banner-framing-20260914` before activation.
- [ ] Production release markers and every application container resolve to the
  new immutable candidate revision/image; all 12 application services and both
  dependencies are healthy with zero restarts after the readiness window.
- [ ] Production schema remains `20260914_0047`; protected `.env`, Compose,
  scheduler mode, database/object state, private manual journal, and unrelated
  application bytes remain unchanged.
- [ ] A network-disabled runtime probe proves current V5 output contains publisher
  names, no reader-facing link affordance, `content_source_url=null`, and no
  outgoing `draft/add` source field, while V1 reconstruction remains unchanged.
- [ ] Queue and ownership checks prove no work was replayed or newly admitted by
  deployment, and the release receipt reports zero model and social calls.
- [ ] If any post-quiescence gate fails, the exact prior image/config markers are
  restored and the 12 application services return healthy; no partial success is
  reported.
