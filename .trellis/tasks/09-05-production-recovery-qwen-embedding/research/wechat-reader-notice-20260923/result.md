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
phrase in actual article prose remains visible. The change must be ported
onto the exact production release base before claiming future production
activation; this branch diverges from deployed `3e62b33` and must not be
deployed wholesale.

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
