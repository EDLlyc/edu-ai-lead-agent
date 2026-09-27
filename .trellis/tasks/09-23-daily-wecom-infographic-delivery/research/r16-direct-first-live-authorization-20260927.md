# R16 direct-first-live decision record

- Date: 2026-09-27 (Asia/Shanghai)
- Scope: the existing ordinary Enterprise WeChat group used by the daily news
  copywriting and original-image dispatcher; not a new recipient, Moments
  feed, or WeChat Official Account draft/publish path.
- Question asked: “第一张成功生成的长图，可以跳过固定测试群，直接发到日常企业微信群吗？”
- User answer: “可以”.
- Prior clarification: the user wants long-image attempts enabled for every
  delivered news item, not a default-off release as the final outcome, and
  accepts that an unavailable image service leaves that supplement absent
  while the original copywriting and image continue.

Operational interpretation: this waives the three-distinct-preview and
fixed-test-group *pre-enable* gates for this rollout. It does **not** waive
same-package/formal-base identity, source/date/full-URL footer binding,
recipient webhook identity, final JPEG size/geometry, one image intent per
package/policy and nine per business day, unknown-result non-replay, or the
protected backup/migration/release checks. The first successful poster may
be the first live group send only after its own hard checks pass. Advisory
OCR/visual findings remain warnings and must not be labeled passes. The
existing text/original-image delivery and Official Account flow stay intact.

This file is an operator-readable record of the conversation decision, not
a cryptographic user signature or proof of the group's current members. Its
SHA-256 may be pinned in a release/enablement manifest; the real operator
must separately capture and compare the live current-group webhook key
fingerprint under lock before enabling.
