# September 23 same-draft cover correction

Target: the existing unpublished draft “从智能制造到家庭科学教育：家长如何帮孩子准备未来”.
The preceding five-body-illustration correction was required and verified
before the cover operation.

The old 1175×500 cover was an extreme close-up of Xiaosai and did not show
the article's family science education or intelligent manufacturing theme.
A new panoramic image was generated with the built-in image tool, using that
old cover only as a character reference. The final crop shows a parent and
child experimenting at home, Xiaosai with a visible AI chest badge, and a
smart-factory scene. The final local JPEG is
`output/wechat-cover-2026-09-23-v1/cover.jpg` (1175×500, 62,413 bytes,
SHA-256 `0797be8fe22ba0f809a6bb35b2e07bc86fdadc24639499f22cc0f7ae90ad5029`).

The operator returned `planned`, then uploaded exactly one permanent
thumbnail and made one `draft/update` call on the original draft ID. Its
subsequent `reconcile` returned `readback_verified` with
`not_published=true`; it did not replay either write. The first apply run
stopped after the upload because whole-object equality included changing
WeChat response metadata. The second apply reused the journaled upload ACK
and reached the update. Its strict raw-HTML readback then stopped because
WeChat reserialized the body. The final reconciliation accepted only unchanged
article contract fields, visible prose, links and nine-image order/identities,
with the existing bounded CDN display-URL normalization.

`material/get_material` returned the new cover image, which was visually
inspected. WeChat re-encoded it to 99,512 bytes; the displayed content and
1175×500 geometry remain correct. No public publication, new draft,
production service restart or deploy occurred. The body/source/footer
materials and SQL visual records were not rewritten by this operator.
