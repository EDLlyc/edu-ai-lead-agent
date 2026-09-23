# September 23 reader-notice correction

The existing unpublished draft “从智能制造到家庭科学教育：家长如何帮孩子准备未来”
contained two copies of the generated internal notice after its two news
context images (image slots 1 and 6 among nine). The words were not Article
prose and should not be reader-visible.

A task-local journaled operator removed exactly those two `<p>` nodes from
the **same** WeChat draft. Read-only plan returned `notices=2`; one
`draft/update` was acknowledged; `draft/get` readback and a separate
reconciliation returned `readback_verified` with `not_published=true`.
The subsequent read-only inspection found zero notice paragraphs and nine
images. Title, author, digest, cover ID, links, other visible prose and image
order/identities were verified unchanged. No `draft/add` or publication call
was made.

For future drafts, the outbound draft service now omits the exact
renderer-generated notice node before submission while leaving immutable
prepared artifacts and internal rights/source records untouched. A same-text
phrase in actual article prose remains visible. This branch diverges from
deployed `3e62b33` and was not deployed wholesale; the narrow production
port and activation are recorded below.

## Narrow production worker activation

The source fix was cherry-picked onto exact deployed source commit `3e62b33`
as `a9db34f` in the separate `release/wechat-notice-production-20260923`
worktree. Its WeChat draft, context-notice and catalog-fallback focused suites
passed together (45 tests); Ruff, formatting and strict mypy passed. The
release-hardening branch was not deployed wholesale.

The running `sha256:2b3a9a7c5e35a3a7173a129a3bd7e0d5322caaeef2c125b9a4d63146e77c9d1a`
image received only the two changed Python modules in a network-isolated
Docker build. The resulting local candidate image is
`sha256:c3f26a9d352332b4cbb63430922babcd71a025ba593fff2e792a4b6c1421e974`.
Its in-image module hashes matched the tested files. A network-isolated
import/notice smoke check and a candidate one-off database/journal preflight
passed. Before and after the worker recreation there were zero active
single-edition leases, zero open draft-item effects and zero single-draft add
intents without ACK; existing delivered/unknown records were untouched.

Only `wechat-official-account-draft-worker` was recreated with the candidate
image and verified running, not restarting. The global `.release.env`, release
markers, other services and database schema were not changed. This is a
service-local production hotfix: Docker's current container/restart policy
retains it, but a later ordinary Compose recreation using the old global
image would revert it. The next managed release must include commit `a9db34f`
before it replaces the draft worker. No public publication occurred.

## Bug analysis

- Root-cause category: cross-layer presentation contract. An internal rights
  warning was rendered as reader HTML for older prepared versions; the V5
  option alone did not cover the still-active draft submission path.
- A current-draft manual correction alone would leave future drafts affected;
  changing the frozen historical renderer would break byte-level replays.
- Prevention: test the actual outgoing `draft/add` HTML, not only local
  prepared HTML; match exact generated markup and retain rights metadata.
- Adjacent exposure: other internal diagnostics must likewise stay in
  preflight/manifest/UI surfaces, not subscriber-visible article content.
